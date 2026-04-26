"""
VXI-11 Proxy GUI Application

Place this file in the root directory of python-vxi11-server.
Run with: python vxi11_proxy.py

Forwards VXI-11 requests from a local server (this machine) to a remote VXI-11
instrument, allowing instruments to be re-exposed on a different network interface
or shared across networks.
"""

import os
import sys
import socket
import logging
import threading
from datetime import datetime
from queue import Queue, Empty

import webview

# Make the bundled vxi11_server package importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vxi11_server as Vxi11
from vxi11_server import vxi11 as vxi11_proto


# ---------------------------------------------------------------------------
# Logging plumbing
# ---------------------------------------------------------------------------

class QueueLogHandler(logging.Handler):
    """A logging handler that pushes formatted records into a thread-safe queue.
    The main GUI thread drains this queue and forwards it to the JS side."""

    def __init__(self, queue: Queue):
        super().__init__()
        self.queue = queue

    def emit(self, record):
        try:
            msg = self.format(record)
            self.queue.put(msg)
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Proxy device factory
# ---------------------------------------------------------------------------

def make_proxy_device_class(target_resource: str, log: logging.Logger,
                            on_fatal_error):
    """Build an InstrumentDevice subclass bound to a specific upstream target.

    A new class is created per proxy session because the framework calls the
    class (not an instance) and we need to inject configuration.
    """

    class ProxyDevice(Vxi11.InstrumentDevice):

        def device_init(self):
            self.upstream = None
            try:
                # Connect to the real instrument we are proxying
                self.upstream = vxi11_proto.Instrument(target_resource)
                self.upstream.open()
                log.info("[link %s] upstream opened: %s",
                         self.device_name, target_resource)
            except Exception as e:
                log.error("[link %s] failed to open upstream %s: %s",
                          self.device_name, target_resource, e)
                # Trigger a controlled shutdown - the GUI should react
                on_fatal_error(f"Upstream connection failed: {e}")

        def _ensure_upstream(self):
            if self.upstream is None:
                raise IOError("upstream not connected")

        # ----- VXI-11 procedures forwarded to the upstream instrument -----

        def device_write(self, opaque_data, flags, io_timeout):
            try:
                self._ensure_upstream()
                self.upstream.timeout = max(io_timeout / 1000.0, 1)
                self.upstream.write_raw(bytes(opaque_data))
                log.info("[link %s] WRITE %d bytes: %r",
                         self.device_name, len(opaque_data),
                         bytes(opaque_data)[:80])
                return Vxi11.Error.NO_ERROR
            except Exception as e:
                log.error("[link %s] WRITE error: %s", self.device_name, e)
                return Vxi11.Error.IO_ERROR

        def device_read(self, request_size, term_char, flags, io_timeout):
            try:
                self._ensure_upstream()
                self.upstream.timeout = max(io_timeout / 1000.0, 1)
                data = self.upstream.read_raw(request_size if request_size > 0
                                              else -1)
                log.info("[link %s] READ  %d bytes: %r",
                         self.device_name, len(data), data[:80])
                return (Vxi11.Error.NO_ERROR,
                        Vxi11.ReadRespReason.END,
                        data)
            except Exception as e:
                log.error("[link %s] READ error: %s", self.device_name, e)
                return Vxi11.Error.IO_ERROR, 0, b""

        def device_trigger(self, flags, io_timeout):
            try:
                self._ensure_upstream()
                self.upstream.trigger()
                return Vxi11.Error.NO_ERROR
            except Exception as e:
                log.error("[link %s] TRIGGER error: %s", self.device_name, e)
                return Vxi11.Error.IO_ERROR

        def device_clear(self, flags, io_timeout):
            try:
                self._ensure_upstream()
                self.upstream.clear()
                return Vxi11.Error.NO_ERROR
            except Exception as e:
                log.error("[link %s] CLEAR error: %s", self.device_name, e)
                return Vxi11.Error.IO_ERROR

        def device_readstb(self, flags, io_timeout):
            try:
                self._ensure_upstream()
                if hasattr(self.upstream, "read_stb"):
                    stb = self.upstream.read_stb()
                else:
                    stb = 0
                return Vxi11.Error.NO_ERROR, stb
            except Exception as e:
                log.error("[link %s] READSTB error: %s", self.device_name, e)
                return Vxi11.Error.IO_ERROR, 0

        def device_abort(self):
            try:
                if self.upstream is not None:
                    self.upstream.abort()
            except Exception as e:
                log.error("[link %s] ABORT error: %s", self.device_name, e)
            return Vxi11.Error.NO_ERROR

        def __del__(self):
            try:
                if self.upstream is not None:
                    self.upstream.close()
                    log.info("[link %s] upstream closed", self.device_name)
            except Exception:
                pass

    return ProxyDevice


# ---------------------------------------------------------------------------
# Proxy session lifecycle
# ---------------------------------------------------------------------------

class ProxySession:
    """Owns a running InstrumentServer and the upstream binding."""

    def __init__(self, target_resource: str, device_name: str,
                 log: logging.Logger, on_fatal_error):
        self.target_resource = target_resource
        self.device_name = device_name
        self.log = log
        self.on_fatal_error = on_fatal_error
        self.server = None

    def start(self):
        device_cls = make_proxy_device_class(
            self.target_resource, self.log, self.on_fatal_error)

        # InstrumentServer auto-creates an inst0 default device. We replace it
        # with our proxy device by creating a server with our class as default,
        # then optionally adding it under a custom name as well.
        self.server = Vxi11.InstrumentServer(default_device_handler=device_cls)
        if self.device_name and self.device_name != "inst0":
            self.server.add_device_handler(device_cls, self.device_name)

        self.server.listen()
        self.log.info("Proxy server started; "
                      "forwarding %s -> %s",
                      self.device_name or "inst0", self.target_resource)

    def stop(self):
        if self.server is not None:
            try:
                self.server.close()
                self.log.info("Proxy server stopped")
            except Exception as e:
                self.log.error("Error during shutdown: %s", e)
            finally:
                self.server = None


# ---------------------------------------------------------------------------
# JS <-> Python bridge
# ---------------------------------------------------------------------------

class Api:
    """Methods exposed to the JS frontend via pywebview's js_api."""

    def __init__(self):
        self.window = None
        self.session: ProxySession | None = None
        self.lock = threading.Lock()

        # Logger setup
        self.log_queue: Queue = Queue()
        self.logger = logging.getLogger("vxi11_proxy")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S"))
        self.logger.addHandler(handler)

        # Also capture vxi11_server framework logs (WARNING+ only — INFO/DEBUG
        # is very chatty and would flood the GUI bridge)
        framework_logger = logging.getLogger("vxi11_server")
        framework_logger.setLevel(logging.WARNING)
        framework_logger.addHandler(handler)

        # Pump thread that forwards queued log lines to JS
        self._pump_running = True
        threading.Thread(target=self._pump_logs, daemon=True).start()

    def attach_window(self, window):
        self.window = window

    # ----- helpers -----

    def _push_logs(self, msgs: list):
        # Wrapped in `void(...)` so the expression evaluates to `undefined`.
        # If we returned the JS value, pywebview's bridge would try to
        # reflect/serialize it and recurse on window.native.AccessibilityObject
        # .Bounds.Empty.Empty... until Python hits its recursion limit.
        if self.window is None or not msgs:
            return
        import json
        payload = json.dumps(msgs)
        try:
            self.window.evaluate_js(
                f"void(window.proxyApp && window.proxyApp.appendLogs({payload}))")
        except Exception:
            pass

    def _push_status(self, running: bool, info: dict | None = None):
        if self.window is None:
            return
        import json
        payload = json.dumps({"running": running, "info": info or {}})
        try:
            self.window.evaluate_js(
                f"void(window.proxyApp && window.proxyApp.onStatus({payload}))")
        except Exception:
            pass

    def _pump_logs(self):
        # Batch up to BATCH_MAX lines per push. Per-line dispatch saturates
        # the webview bridge under heavy VXI-11 traffic.
        BATCH_MAX = 200
        while self._pump_running:
            try:
                first = self.log_queue.get(timeout=0.2)
            except Empty:
                continue
            buf = [first]
            for _ in range(BATCH_MAX - 1):
                try:
                    buf.append(self.log_queue.get_nowait())
                except Empty:
                    break
            self._push_logs(buf)

    def _on_fatal_error(self, message: str):
        # Called from background threads when the proxy can't continue
        self.logger.error("FATAL: %s", message)
        try:
            self.stop()
        except Exception:
            pass
        if self.window is not None:
            import json
            payload = json.dumps({"message": message})
            self.window.evaluate_js(
                f"void(window.proxyApp && window.proxyApp.onFatalError({payload}))")

    # ----- public API exposed to JS -----

    def get_local_ip(self):
        """Return the machine's primary outbound IPv4 address."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()

    def get_status(self):
        return {"running": self.session is not None}

    def start_proxy(self, target_resource: str,
                    bind_address: str = "0.0.0.0",
                    device_name: str = "inst0"):
        """Start forwarding. Returns {ok, message}."""
        with self.lock:
            if self.session is not None:
                return {"ok": False, "message": "Proxy already running"}

            target_resource = (target_resource or "").strip()
            if not target_resource:
                return {"ok": False, "message": "Target address is required"}

            # Normalize target - if user gave a bare IP, wrap in TCPIP::...::INSTR
            if "::" not in target_resource:
                target_resource = f"TCPIP::{target_resource}::INSTR"

            self.logger.info("Starting proxy: %s -> %s (device=%s, bind=%s)",
                             device_name or "inst0", target_resource,
                             device_name or "inst0", bind_address)

            try:
                session = ProxySession(
                    target_resource=target_resource,
                    device_name=device_name or "inst0",
                    log=self.logger,
                    on_fatal_error=self._on_fatal_error,
                )
                session.start()
                self.session = session
            except Exception as e:
                self.logger.error("Failed to start: %s", e)
                return {"ok": False, "message": f"Start failed: {e}"}

        self._push_status(True, {"target": target_resource,
                                 "device": device_name or "inst0",
                                 "bind": bind_address})
        return {"ok": True, "message": "Proxy started"}

    def stop_proxy(self):
        with self.lock:
            if self.session is None:
                return {"ok": False, "message": "Proxy is not running"}
            try:
                self.session.stop()
            finally:
                self.session = None
        self._push_status(False)
        return {"ok": True, "message": "Proxy stopped"}

    def stop(self):
        return self.stop_proxy()

    def shutdown(self):
        """Called when the window is closing."""
        self._pump_running = False
        if self.session is not None:
            try:
                self.session.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _resolve_frontend_url() -> str:
    """Pick the HTML to load in the webview.

    Priority:
      1. $VXI11_GUI_URL (e.g. http://localhost:5173 during `pnpm dev`)
      2. view/dist/index.html (the built Vite SPA)
      3. legacy index.html in the repo root (fallback)
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))

    env_url = os.environ.get("VXI11_GUI_URL")
    if env_url:
        return env_url

    built = os.path.join(base_dir, "view", "dist", "index.html")
    if os.path.isfile(built):
        return built

    # return os.path.join(base_dir, "index.html")
    return None


def main():
    api = Api()

    html_path = "http://localhost:5173"

    window = webview.create_window(
        title="VXI-11 Proxy",
        url=html_path,
        js_api=api,
        width=900,
        height=720,
        resizable=True,
    )
    api.attach_window(window)

    def on_closing():
        api.shutdown()

    window.events.closing += on_closing
    webview.start(debug=True)


if __name__ == "__main__":
    main()