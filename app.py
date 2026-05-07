"""VISA device protocol mapping tool.

Frontend (Element Plus) is loaded into a pywebview window. The Python side
exposes a JsApi class via pywebview's `js_api`, while log messages are
pushed to the page through `window.evaluate_js`.

The UI takes a host IP per side plus a set of protocol checkboxes
(VXI-11 / HiSLIP / SOCKET). Each enabled source protocol gets its own
RelaySource; incoming connections are forwarded to the same protocol on
the target if available, otherwise we fall back to the most feature-rich
enabled one (HiSLIP > VXI-11 > SOCKET) so a client that probes via
VXI-11/SOCKET and upgrades to HiSLIP keeps working.
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
)
from vxi11_server.transports.base import HISLIP_DEFAULT_PORT, SOCKET_DEFAULT_PORT


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


def default_endpoint_config(host: str | None = None) -> dict:
    """Default endpoint config: all three protocols enabled, standard ports."""
    return {
        'host': host or (get_local_ipv4() or '0.0.0.0'),
        'vxi11': True,
        'hislip': {'enabled': True, 'port': HISLIP_DEFAULT_PORT},
        'socket': {'enabled': True, 'port': SOCKET_DEFAULT_PORT},
    }


def format_exception(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__


_TRANSPORT_LABELS = {
    Transport.VXI11: 'VXI-11',
    Transport.HISLIP: 'HiSLIP',
    Transport.SOCKET: 'SOCKET',
}

# When the source-side incoming protocol isn't enabled on the target, prefer
# HiSLIP (most feature-rich) > VXI-11 > SOCKET.
_TARGET_FALLBACK_ORDER = (Transport.HISLIP, Transport.VXI11, Transport.SOCKET)


def _validate_port(label: str, value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} 端口需为整数')
    if not 1 <= port <= 65535:
        raise ValueError(f'{label} 端口需在 1–65535 之间')
    return port


def _build_endpoint_addresses(label: str, cfg: dict) -> list[AddressInfo]:
    """Turn an endpoint config from the UI into one AddressInfo per protocol."""
    if not isinstance(cfg, dict):
        raise ValueError(f'{label} 配置无效')
    host = (cfg.get('host') or '').strip()
    if not host:
        raise ValueError(f'{label}: 主机 IP 不能为空')

    addrs: list[AddressInfo] = []
    if cfg.get('vxi11'):
        addrs.append(AddressInfo(
            raw=f'TCPIP::{host}::inst0::INSTR',
            transport=Transport.VXI11,
            host=host,
            device='inst0',
        ))
    hislip = cfg.get('hislip') or {}
    if hislip.get('enabled'):
        port = _validate_port(f'{label} HiSLIP', hislip.get('port', HISLIP_DEFAULT_PORT))
        suffix = 'hislip0' if port == HISLIP_DEFAULT_PORT else f'hislip0,{port}'
        addrs.append(AddressInfo(
            raw=f'TCPIP::{host}::{suffix}::INSTR',
            transport=Transport.HISLIP,
            host=host,
            hislip_name='hislip0',
            port=port,
        ))
    sock = cfg.get('socket') or {}
    if sock.get('enabled'):
        port = _validate_port(f'{label} SOCKET', sock.get('port', SOCKET_DEFAULT_PORT))
        addrs.append(AddressInfo(
            raw=f'TCPIP::{host}::{port}::SOCKET',
            transport=Transport.SOCKET,
            host=host,
            port=port,
        ))
    if not addrs:
        raise ValueError(f'{label}: 至少需要启用一个协议')
    return addrs


def _pick_target_address(
    target_by_proto: dict,
    src_proto: Transport,
) -> AddressInfo:
    """Pick a target AddressInfo for an incoming source protocol.

    Same-protocol passthrough wins; otherwise fall back HiSLIP > VXI-11 >
    SOCKET. The caller must pass a non-empty ``target_by_proto``.
    """
    if src_proto in target_by_proto:
        return target_by_proto[src_proto]
    for proto in _TARGET_FALLBACK_ORDER:
        if proto in target_by_proto:
            return target_by_proto[proto]
    raise ValueError('目标未启用任何协议')


class JsApi:
    """Methods exposed to the webview as ``window.pywebview.api.*``."""

    def __init__(self):
        self._window = None
        self._sources: list = []
        self._running = False
        self._source_config: dict | None = None
        self._target_config: dict | None = None
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

    def get_status(self):
        return {
            'running': self._running,
            'source': self._source_config,
            'target': self._target_config,
        }

    def get_default_endpoints(self):
        local = get_local_ipv4() or '0.0.0.0'
        return {
            'source': default_endpoint_config(local),
            'target': default_endpoint_config('192.168.1.10'),
        }

    def start_mapping(self, source: dict, target: dict):
        with self._lock:
            if self._running:
                return {'ok': False, 'message': '映射已在运行'}

            try:
                source_addrs = _build_endpoint_addresses('映射设备', source)
                target_addrs = _build_endpoint_addresses('目标设备', target)
            except ValueError as exc:
                return {'ok': False, 'message': str(exc)}

            target_by_proto = {a.transport: a for a in target_addrs}

            started: list = []
            try:
                for src_addr in source_addrs:
                    tgt_addr = _pick_target_address(target_by_proto, src_addr.transport)
                    target_factory = (lambda info: lambda: make_target(info))(tgt_addr)
                    src = make_source(src_addr, target_factory, self.push_log)
                    src.start()
                    started.append((src_addr, tgt_addr, src))
                    self.push_log(
                        'INFO',
                        f'  · {_TRANSPORT_LABELS[src_addr.transport]} '
                        f'{src_addr.raw} → '
                        f'{_TRANSPORT_LABELS[tgt_addr.transport]} {tgt_addr.raw}',
                    )

                self._sources = [s for _, _, s in started]
                self._running = True
                self._source_config = source
                self._target_config = target
                self.push_log(
                    'SUCCESS',
                    f'映射已启动: 源 {len(source_addrs)} 个协议 → 目标 {len(target_addrs)} 个协议',
                )
                return {'ok': True}
            except Exception as exc:
                message = format_exception(exc)
                self.push_log('ERROR', f'启动失败: {message}')
                for _, _, src in started:
                    try:
                        src.stop()
                    except Exception:
                        pass
                self._sources = []
                self._running = False
                self._source_config = None
                self._target_config = None
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
        for src in self._sources:
            try:
                src.stop()
            except Exception as exc:
                self.push_log(
                    'WARN',
                    f'source 收尾异常 (已忽略): {format_exception(exc)}',
                )
        self._sources = []
        self._running = False
        self._source_config = None
        self._target_config = None


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
