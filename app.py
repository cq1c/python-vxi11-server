"""VISA device protocol mapping tool.

Frontend (Element Plus) is loaded into a pywebview window. The Python side
exposes a JsApi class via pywebview's `js_api`, while log messages are
pushed to the page through `window.evaluate_js`.

The UI takes a host IP per side plus a set of protocol checkboxes
(VXI-11 / HiSLIP / SOCKET). Each enabled source protocol gets its own
RelaySource; incoming connections are forwarded to the same protocol on
the target if available, with per-session fallback to the most feature-rich
enabled one (HiSLIP > VXI-11 > SOCKET) when that endpoint is unavailable.
"""

import json
import logging
import os
import pickle
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import webview

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vxi11_server import rpc as vxi11_rpc
from vxi11_server.transports import (
    AddressInfo,
    RelayClient,
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


_LOG_PRIORITY = {
    'DEBUG': 10,
    'INFO': 20,
    'SUCCESS': 20,
    'WARN': 30,
    'WARNING': 30,
    'ERROR': 40,
}
_DEFAULT_LOG_LEVEL = 'INFO'

# A fixed subdir under the OS temp dir. tempfile.gettempdir() returns a
# stable location across launches (/tmp on Linux, %TEMP% on Windows), so
# data saved here survives restarts. Intentionally NOT sys._MEIPASS,
# which is a fresh per-launch pyinstaller scratch dir.
_STATE_DIR_NAME = 'visa-mapping-tool'
_STATE_FILE_NAME = 'last_inputs.pkl'


def _state_file_path() -> Path:
    base = Path(tempfile.gettempdir()) / _STATE_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base / _STATE_FILE_NAME


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


def _target_route(
    target_by_proto: dict,
    src_proto: Transport,
) -> list[AddressInfo]:
    """Build target attempts for an incoming source protocol.

    Same-protocol passthrough wins. If that endpoint cannot be used for a
    session, the routed client falls back HiSLIP > VXI-11 > SOCKET.
    """
    route: list[AddressInfo] = []
    seen: set[Transport] = set()

    def add(proto: Transport) -> None:
        if proto in seen:
            return
        addr = target_by_proto.get(proto)
        if addr is None:
            return
        route.append(addr)
        seen.add(proto)

    add(src_proto)
    for proto in _TARGET_FALLBACK_ORDER:
        add(proto)

    if not route:
        raise ValueError('目标未启用任何协议')
    return route


def _format_target_route(route: list[AddressInfo]) -> str:
    return ' / '.join(
        f'{_TRANSPORT_LABELS[addr.transport]} {addr.raw}' for addr in route
    )


class _RoutedTargetClient(RelayClient):
    """Session-local target client with same-protocol preference + fallback."""

    def __init__(self, route: list[AddressInfo], log) -> None:
        self._route = tuple(route)
        self._log = log
        self._client: RelayClient | None = None
        self._active: AddressInfo | None = None

    def open(self) -> None:
        if self._client is not None:
            return

        errors: list[str] = []
        for index, addr in enumerate(self._route):
            client = make_target(addr)
            try:
                client.open()
            except Exception as exc:
                try:
                    client.close()
                except Exception:
                    pass
                message = format_exception(exc)
                errors.append(f'{_TRANSPORT_LABELS[addr.transport]} {addr.raw}: {message}')
                if index + 1 < len(self._route):
                    self._log(
                        'WARN',
                        f'目标 {_TRANSPORT_LABELS[addr.transport]} 连接失败，尝试下一个协议: {message}',
                    )
                continue

            self._client = client
            self._active = addr
            if index > 0:
                self._log(
                    'INFO',
                    f'目标协议已切换为 {_TRANSPORT_LABELS[addr.transport]} {addr.raw}',
                )
            return

        detail = '; '.join(errors) if errors else '未配置目标协议'
        raise ConnectionError(f'目标协议均连接失败: {detail}')

    def close(self) -> None:
        client = self._client
        self._client = None
        self._active = None
        if client is not None:
            client.close()

    def _require_client(self) -> RelayClient:
        if self._client is None:
            self.open()
        assert self._client is not None
        return self._client

    def write_raw(self, data: bytes) -> None:
        self._require_client().write_raw(data)

    def read_raw(self, max_size: int = -1) -> bytes:
        return self._require_client().read_raw(max_size)

    def has_pending_read_data(self) -> bool:
        pending = getattr(self._require_client(), 'has_pending_read_data', None)
        return bool(callable(pending) and pending())

    def device_clear(self) -> None:
        self._require_client().device_clear()


def _make_target_factory(route: list[AddressInfo], log):
    return lambda: _RoutedTargetClient(route, log)


def _pick_target_address(
    target_by_proto: dict,
    src_proto: Transport,
) -> AddressInfo:
    """Return the first target address for compatibility with old callers."""
    return _target_route(target_by_proto, src_proto)[0]


class JsApi:
    """Methods exposed to the webview as ``window.pywebview.api.*``."""

    def __init__(self):
        self._window = None
        self._sources: list = []
        self._running = False
        self._source_config: dict | None = None
        self._target_config: dict | None = None
        self._lock = threading.Lock()
        self._log_level = _DEFAULT_LOG_LEVEL
        self._persisted: dict = self._load_persisted()

    def attach_window(self, window: 'webview.Window') -> None:
        self._window = window

    # ---- pickle persistence ------------------------------------------

    def _load_persisted(self) -> dict:
        try:
            with _state_file_path().open('rb') as f:
                data = pickle.load(f)
        except (FileNotFoundError, EOFError, pickle.UnpicklingError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        level = data.get('log_level')
        if isinstance(level, str) and level.upper() in _LOG_PRIORITY:
            self._log_level = level.upper()
        return data

    def _save_persisted(self) -> None:
        data = {
            'source': self._persisted.get('source'),
            'target': self._persisted.get('target'),
            'log_level': self._log_level,
        }
        try:
            with _state_file_path().open('wb') as f:
                pickle.dump(data, f)
        except OSError:
            pass

    # ---- log push -----------------------------------------------------

    def push_log(self, level: str, msg: str) -> None:
        if not self._window:
            return
        if _LOG_PRIORITY.get(level.upper(), 0) < _LOG_PRIORITY.get(self._log_level, 0):
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

    def set_log_level(self, level: str):
        level_up = level.upper() if isinstance(level, str) else ''
        if level_up not in _LOG_PRIORITY:
            return {'ok': False, 'message': f'未知日志等级: {level}'}
        self._log_level = level_up
        self._save_persisted()
        return {'ok': True, 'level': level_up}

    # ---- public js api ------------------------------------------------

    def get_status(self):
        return {
            'running': self._running,
            'source': self._source_config,
            'target': self._target_config,
            'log_level': self._log_level,
        }

    def get_persisted_state(self):
        return {
            'source': self._persisted.get('source'),
            'target': self._persisted.get('target'),
            'log_level': self._log_level,
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

            self._persisted['source'] = source
            self._persisted['target'] = target
            self._save_persisted()

            target_by_proto = {a.transport: a for a in target_addrs}

            started: list = []
            try:
                for src_addr in source_addrs:
                    target_route = _target_route(target_by_proto, src_addr.transport)
                    target_factory = _make_target_factory(target_route, self.push_log)
                    src = make_source(src_addr, target_factory, self.push_log)
                    src.start()
                    started.append((src_addr, target_route, src))
                    self.push_log(
                        'INFO',
                        f'  · {_TRANSPORT_LABELS[src_addr.transport]} '
                        f'{src_addr.raw} → '
                        f'{_format_target_route(target_route)}',
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
        text_select=True,
    )
    api.attach_window(window)

    debug = os.environ.get('VIEW_DEBUG', '1') != '0'
    webview.start(debug=debug)


if __name__ == '__main__':
    main()
