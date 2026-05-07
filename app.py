"""VISA device protocol mapping tool.

Frontend (Element Plus) is loaded into a pywebview window. The Python side
exposes a JsApi class via pywebview's `js_api`, while log messages are
pushed to the page through `window.evaluate_js`.

Supports three VISA transports for both source and target:

* VXI-11   ``TCPIP[N]::host[::deviceName]::INSTR``
* HiSLIP   ``TCPIP[N]::host::hislipN[,port]::INSTR``
* SOCKET   ``TCPIP[N]::host::PORT::SOCKET``
"""

import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

import webview

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vxi11_server import rpc as vxi11_rpc
from vxi11_server.transports import (
    AddressInfo,
    Transport,
    make_source,
    make_target,
    parse_address,
)


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


def default_view_url() -> str:
    if 'VIEW_URL' in os.environ:
        return os.environ['VIEW_URL']

    base_dir = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    bundled_index = base_dir / 'view' / 'dist' / 'index.html'
    if bundled_index.exists():
        return bundled_index.resolve().as_uri()

    local_index = Path(__file__).resolve().parent / 'view' / 'dist' / 'index.html'
    if local_index.exists():
        return local_index.resolve().as_uri()

    return 'http://localhost:5173'


def get_local_ipv4() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            host = sock.getsockname()[0]
            if host and not host.startswith('127.'):
                return host
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            host = info[4][0]
            if host and not host.startswith('127.'):
                return host
    except OSError:
        pass

    return None


def default_source_address() -> str:
    host = get_local_ipv4() or '0.0.0.0'
    return f'TCPIP::{host}::inst0::INSTR'


def format_exception(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__


def _transport_label(t: Transport) -> str:
    return {Transport.VXI11: 'VXI-11', Transport.HISLIP: 'HiSLIP', Transport.SOCKET: 'SOCKET'}[t]


class JsApi:
    """Methods exposed to the webview as ``window.pywebview.api.*``."""

    def __init__(self):
        self._window = None
        self._source = None  # RelaySource
        self._running = False
        self._source_addr = None
        self._target_addr = None
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
        if parse_address(addr) is None:
            return {
                'ok': False,
                'message': '格式应为 TCPIP::host::inst0::INSTR / hislip0::INSTR / PORT::SOCKET',
            }
        return {'ok': True}

    def get_status(self):
        return {
            'running': self._running,
            'source': self._source_addr,
            'target': self._target_addr,
        }

    def get_default_source_address(self):
        return {
            'address': default_source_address(),
            'host': get_local_ipv4() or '0.0.0.0',
        }

    def start_mapping(self, source_addr: str, target_addr: str):
        with self._lock:
            if self._running:
                return {'ok': False, 'message': '映射已在运行'}

            for label, addr in (('源地址', source_addr), ('目标地址', target_addr)):
                v = self.validate_address(addr)
                if not v['ok']:
                    return {'ok': False, 'message': f'{label}: {v["message"]}'}

            source_info = parse_address(source_addr)
            target_info = parse_address(target_addr)
            assert source_info is not None and target_info is not None

            try:
                target_factory = lambda info=target_info: make_target(info)
                self._source = make_source(source_info, target_factory, self.push_log)
                self._source.start()

                self._running = True
                self._source_addr = source_info.raw
                self._target_addr = target_info.raw
                self.push_log(
                    'SUCCESS',
                    f'映射已启动 [{_transport_label(source_info.transport)} → '
                    f'{_transport_label(target_info.transport)}]: '
                    f'{self._source_addr} -> {self._target_addr}',
                )
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
        if self._source is not None:
            try:
                self._source.stop()
            except Exception as exc:
                self.push_log(
                    'WARN',
                    f'source 收尾异常 (已忽略): {format_exception(exc)}',
                )
            self._source = None
        self._running = False
        self._source_addr = None
        self._target_addr = None


api = JsApi()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    url = default_view_url()

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
