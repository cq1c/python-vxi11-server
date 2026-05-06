"""VISA device protocol mapping tool.

Frontend (Element Plus) is loaded into a pywebview window. The Python side
exposes a JsApi class via pywebview's `js_api`, while log messages are
pushed to the page through `window.evaluate_js`.
"""

import json
import logging
import os
import re
import sys
import threading
import time

import webview

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vxi11_server as Vxi11
from vxi11_server import rpc as vxi11_rpc
from vxi11_server import vxi11 as vxi11_proto
from vxi11_server.portmap_server import PortMapServer


def _local_host(host: str) -> str:
    """Return a host string that's actually connectable via TCP.

    InstrumentServer binds to `''` which becomes `('0.0.0.0', port)` after
    bind. Connecting to `0.0.0.0` works on Linux but raises WinError 10049
    on Windows. Always rewrite to loopback for our embedded portmap calls.
    """
    if not host or host in ('0.0.0.0', '::'):
        return '127.0.0.1'
    return host


# Patch the upstream rpc.TCPServer so register_pmap/unregister talk to a
# loopback portmapper instead of '' / '0.0.0.0'. This keeps the existing
# InstrumentServer.listen() / .close() flow working unmodified on Windows.

def _patched_register_pmap(self):
    host, _port = self.server_address
    p = vxi11_rpc.TCPPortMapperClient(_local_host(host))
    if not p.set(self.mapping):
        raise vxi11_rpc.RPCError('register failed')
    self.registered = True


def _patched_unregister(self):
    host, _port = self.server_address
    p = vxi11_rpc.TCPPortMapperClient(_local_host(host))
    if not p.unset(self.mapping):
        raise vxi11_rpc.RPCError('unregister failed')
    self.registered = False


vxi11_rpc.TCPServer.register_pmap = _patched_register_pmap
vxi11_rpc.TCPServer.unregister = _patched_unregister


# TCPIP[board]::host[::device]::INSTR  (case-insensitive, ignore surrounding whitespace)
VISA_RE = re.compile(
    r'^TCPIP\d*::([A-Za-z0-9_.\-]+)(?:::([A-Za-z0-9_]+))?::INSTR$',
    re.IGNORECASE,
)


def parse_visa(addr: str):
    m = VISA_RE.match(addr.strip())
    if not m:
        return None
    return {'host': m.group(1), 'device': m.group(2) or 'inst0'}


def format_exception(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__


class MappingDevice(Vxi11.InstrumentDevice):
    """Proxies VXI-11 RPCs from a local link to a real upstream instrument.

    Configuration is set on the class before the server is started, because
    the framework instantiates one device per client link via a no-arg-style
    factory (``device_class(name, lock)``).
    """

    target_address = None
    log_sink = None

    def device_init(self):
        self._client = None
        try:
            self._client = vxi11_proto.Instrument(self.target_address)
            self._client.open()
            self._log('INFO', f'链接已建立 -> {self.target_address}')
        except Exception as exc:
            self._log('ERROR', f'连接目标设备失败: {exc}')
            self._client = None

    def _log(self, level, msg):
        sink = MappingDevice.log_sink
        if sink:
            sink(level, msg)

    def device_write(self, opaque_data, flags, io_timeout):
        if self._client is None:
            return Vxi11.Error.IO_ERROR
        try:
            self._client.write_raw(opaque_data)
            preview = opaque_data.decode('ascii', errors='replace').strip()
            self._log('INFO', f'>>> {preview}')
            return Vxi11.Error.NO_ERROR
        except Exception as exc:
            self._log('ERROR', f'write 失败: {exc}')
            return Vxi11.Error.IO_ERROR

    def device_read(self, request_size, term_char, flags, io_timeout):
        if self._client is None:
            return Vxi11.Error.IO_ERROR, Vxi11.ReadRespReason.END, b''
        try:
            data = self._client.read_raw(request_size)
            preview = data.decode('ascii', errors='replace').strip()
            self._log('INFO', f'<<< {preview}')
            return Vxi11.Error.NO_ERROR, Vxi11.ReadRespReason.END, data
        except Exception as exc:
            self._log('ERROR', f'read 失败: {exc}')
            return Vxi11.Error.IO_ERROR, Vxi11.ReadRespReason.END, b''


class JsApi:
    """Methods exposed to the webview as ``window.pywebview.api.*``."""

    def __init__(self):
        self._window = None
        self._server = None
        self._portmap = None
        self._running = False
        self._source = None
        self._target = None
        self._lock = threading.Lock()

    def attach_window(self, window: 'webview.Window') -> None:
        self._window = window

    # ---- log push -----------------------------------------------------

    def push_log(self, level: str, msg: str) -> None:
        if not self._window:
            return
        payload = json.dumps({
            'level': level,
            'time': time.strftime('%H:%M:%S'),
            'msg': msg,
        })
        try:
            self._window.evaluate_js(f'window.__pushLog && window.__pushLog({payload})')
        except Exception:
            pass

    # ---- public js api ------------------------------------------------

    def validate_address(self, addr: str):
        if not addr or not addr.strip():
            return {'ok': False, 'message': '地址不能为空'}
        if parse_visa(addr) is None:
            return {
                'ok': False,
                'message': '格式应为 TCPIP[board]::host[::device]::INSTR',
            }
        return {'ok': True}

    def get_status(self):
        return {
            'running': self._running,
            'source': self._source,
            'target': self._target,
        }

    def start_mapping(self, source_addr: str, target_addr: str):
        with self._lock:
            if self._running:
                return {'ok': False, 'message': '映射已在运行'}

            for label, addr in (('源地址', source_addr), ('目标地址', target_addr)):
                v = self.validate_address(addr)
                if not v['ok']:
                    return {'ok': False, 'message': f'{label}: {v["message"]}'}

            src = parse_visa(source_addr)
            try:
                MappingDevice.target_address = target_addr.strip()
                MappingDevice.log_sink = self.push_log

                self._portmap = PortMapServer()
                try:
                    self._portmap.start()
                except OSError as exc:
                    self._portmap = None
                    self.push_log(
                        'WARN',
                        f'本地 portmap 端口被占用 (已使用系统已有的): {exc}',
                    )

                # InstrumentServer always registers a default 'inst0'. If the
                # user's source device is 'inst0', override that default;
                # otherwise add the mapping device as an extra handler.
                if src['device'].lower() == 'inst0':
                    self._server = Vxi11.InstrumentServer(default_device_handler=MappingDevice)
                else:
                    self._server = Vxi11.InstrumentServer()
                    self._server.add_device_handler(MappingDevice, src['device'])
                self._server.listen()

                self._running = True
                self._source = source_addr.strip()
                self._target = target_addr.strip()
                self.push_log('SUCCESS', f'映射已启动: {self._source} -> {self._target}')
                return {'ok': True}
            except Exception as exc:
                message = format_exception(exc)
                self.push_log('ERROR', f'启动失败: {message}')
                self._cleanup()
                return {'ok': False, 'message': f'启动失败: {message}'}

    def stop_mapping(self):
        with self._lock:
            if not self._running:
                return {'ok': True}
            try:
                self._cleanup()
                self.push_log('INFO', '映射已停止')
                return {'ok': True}
            except Exception as exc:
                message = format_exception(exc)
                self.push_log('ERROR', f'停止失败: {message}')
                return {'ok': False, 'message': f'停止失败: {message}'}

    def _cleanup(self):
        if self._server is not None:
            try:
                self._server.close()
            except Exception as exc:
                # listen() can fail partway (abort thread started, core not),
                # in which case socketserver.shutdown() on the un-served core
                # server would deadlock waiting on its __is_shut_down event.
                # Tear servers down with a bounded join.
                self.push_log(
                    'WARN',
                    f'instrument server 收尾异常 (已忽略): {format_exception(exc)}',
                )
                for srv_attr in ('coreServer', 'abortServer'):
                    srv = getattr(self._server, srv_attr, None)
                    if srv is None:
                        continue
                    t = threading.Thread(target=srv.shutdown, daemon=True)
                    t.start()
                    t.join(timeout=1.5)
                    try:
                        srv.server_close()
                    except Exception:
                        pass
            finally:
                self._server = None
        if self._portmap is not None:
            try:
                self._portmap.stop()
            except Exception as exc:
                self.push_log(
                    'WARN',
                    f'portmap stop 异常 (已忽略): {format_exception(exc)}',
                )
            self._portmap = None
        self._running = False
        self._source = None
        self._target = None
        MappingDevice.target_address = None
        MappingDevice.log_sink = None


api = JsApi()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    # Default: connect to the Vite dev server. Override with VIEW_URL=
    # file:///path/to/dist/index.html for a built bundle.
    url = os.environ.get('VIEW_URL', 'http://localhost:5173')

    window = webview.create_window(
        title='VISA 设备映射工具',
        url=url,
        js_api=api,
        width=960,
        height=720,
        confirm_close=True,
    )
    api.attach_window(window)

    debug = os.environ.get('VIEW_DEBUG', '1') != '0'
    webview.start(debug=debug)


if __name__ == '__main__':
    main()
