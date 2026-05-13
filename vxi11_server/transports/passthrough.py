"""Same-protocol TCP passthrough sources.

When the source and target speak the same protocol, the relay does not need
to decode anything: each accepted client connection is paired one-to-one
with a TCP connection to the upstream target, and two pump threads shuttle
bytes both ways until either end closes.

This avoids the SCPI-only ``b'?' in message`` heuristic in the protocol-level
relay, preserves vendor-extension bytes verbatim, and lowers latency.

For HiSLIP and SOCKET the target port is known up front. For VXI-11 the
target's per-program ports live in the remote portmap; :class:`Vxi11PassthroughSource`
queries it on every new connection and registers its own listener ports
with the local :class:`PortMapServer` so client GETPORT calls resolve here.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from typing import Callable, Optional

from .. import rpc as vxi11_rpc
from .. import vxi11
from ..portmap_server import PortMapServer
from .base import (
    AddressInfo,
    HISLIP_DEFAULT_PORT,
    LogSink,
    Transport,
    _silent_log,
    listen_host_for_source,
)


PUMP_BUF = 65536
CONNECT_TIMEOUT = 10.0


def _shutdown_quiet(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            chunk = src.recv(PUMP_BUF)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass


def _bridge(client_sock: socket.socket, target_sock: socket.socket) -> None:
    up = threading.Thread(target=_pump, args=(client_sock, target_sock), daemon=True)
    down = threading.Thread(target=_pump, args=(target_sock, client_sock), daemon=True)
    up.start()
    down.start()
    up.join()
    down.join()
    _shutdown_quiet(client_sock)
    _shutdown_quiet(target_sock)


class _TcpPassthrough:
    """One listening socket → per-connection TCP pump to a resolved target port."""

    def __init__(
        self,
        label: str,
        listen_host: str,
        listen_port: int,
        target_host: str,
        target_port_provider: Callable[[], int],
        log: LogSink,
    ) -> None:
        self.label = label
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._target_host = target_host
        self._target_port_provider = target_port_provider
        self._log = log
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._bound_port: Optional[int] = None

    @property
    def bound_port(self) -> int:
        if self._bound_port is None:
            raise RuntimeError(f'{self.label} passthrough not started')
        return self._bound_port

    def start(self) -> None:
        if self._server is not None:
            return

        outer = self

        class _Handler(socketserver.BaseRequestHandler):
            def handle(self):  # noqa: D401 — framework hook
                try:
                    target_port = outer._target_port_provider()
                except Exception as exc:
                    outer._log('ERROR', f'{outer.label} 直转: 目标端口解析失败: {exc}')
                    return
                try:
                    target_sock = socket.create_connection(
                        (outer._target_host, target_port),
                        timeout=CONNECT_TIMEOUT,
                    )
                    target_sock.settimeout(None)
                except OSError as exc:
                    outer._log(
                        'ERROR',
                        f'{outer.label} 直转: 目标 '
                        f'{outer._target_host}:{target_port} 连接失败: {exc}',
                    )
                    return

                self.request.settimeout(None)
                outer._log(
                    'INFO',
                    f'{outer.label} 直转: {self.client_address} ⇄ '
                    f'{outer._target_host}:{target_port}',
                )
                try:
                    _bridge(self.request, target_sock)
                finally:
                    outer._log('INFO', f'{outer.label} 直转: 会话结束 {self.client_address}')

        class _Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = _Server((self._listen_host, self._listen_port), _Handler)
        self._bound_port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f'passthrough-{self.label}-{self._bound_port}',
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        srv = self._server
        self._server = None
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass
            try:
                srv.server_close()
            except Exception:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2)


class SocketPassthroughSource:
    """Raw TCP SOCKET passthrough — listen on src.port → pump to target.port."""

    def __init__(
        self,
        info: AddressInfo,
        target_host: str,
        target_port: int,
        log: Optional[LogSink] = None,
    ) -> None:
        self._info = info
        self._target_host = target_host
        self._target_port = target_port
        self._log = log or _silent_log
        self._bridge = _TcpPassthrough(
            label='SOCKET',
            listen_host=listen_host_for_source(info.host),
            listen_port=info.port,
            target_host=target_host,
            target_port_provider=lambda: target_port,
            log=self._log,
        )

    def start(self) -> None:
        self._bridge.start()
        self._log(
            'INFO',
            f'SOCKET 直转监听 {self._info.host}:{self._info.port} → '
            f'{self._target_host}:{self._target_port}',
        )

    def stop(self) -> None:
        self._bridge.stop()


class HislipPassthroughSource:
    """HiSLIP passthrough — listen on src.port (default 4880) → pump to target."""

    def __init__(
        self,
        info: AddressInfo,
        target_host: str,
        target_port: int,
        log: Optional[LogSink] = None,
    ) -> None:
        self._info = info
        self._target_host = target_host
        self._target_port = target_port or HISLIP_DEFAULT_PORT
        self._log = log or _silent_log
        self._bridge = _TcpPassthrough(
            label='HiSLIP',
            listen_host=listen_host_for_source(info.host),
            listen_port=info.port or HISLIP_DEFAULT_PORT,
            target_host=target_host,
            target_port_provider=lambda: self._target_port,
            log=self._log,
        )

    def start(self) -> None:
        self._bridge.start()
        self._log(
            'INFO',
            f'HiSLIP 直转监听 {self._info.host}:'
            f'{self._info.port or HISLIP_DEFAULT_PORT} → '
            f'{self._target_host}:{self._target_port}',
        )

    def stop(self) -> None:
        self._bridge.stop()


class Vxi11PassthroughSource:
    """VXI-11 passthrough: proxy portmap + pump core/async TCP channels.

    On each new client connection we re-query the remote host's portmap so
    target server restarts (which reshuffle port numbers) recover without
    needing a relay restart.
    """

    _VXI11_PROGRAMS = (
        ('core', vxi11.DEVICE_CORE_PROG, vxi11.DEVICE_CORE_VERS),
        ('async', vxi11.DEVICE_ASYNC_PROG, vxi11.DEVICE_ASYNC_VERS),
    )

    def __init__(
        self,
        info: AddressInfo,
        target_host: str,
        log: Optional[LogSink] = None,
    ) -> None:
        self._info = info
        self._target_host = target_host
        self._log = log or _silent_log
        self._listen_host = listen_host_for_source(info.host)
        self._portmap: Optional[PortMapServer] = None
        self._channels: dict[str, _TcpPassthrough] = {}
        self._own_portmap = False

    def _resolve_remote_port(self, prog: int, vers: int) -> int:
        pmap = vxi11_rpc.TCPPortMapperClient(self._target_host)
        port = pmap.get_port((prog, vers, vxi11_rpc.IPPROTO_TCP, 0))
        if not port:
            raise IOError(
                f'远端 portmap 未注册 VXI-11 程序 {prog:#x} v{vers}'
            )
        return port

    def start(self) -> None:
        portmap_host = self._listen_host or '127.0.0.1'
        self._portmap = PortMapServer(host=portmap_host)
        try:
            self._portmap.start()
            self._own_portmap = True
            display_host = self._listen_host or '0.0.0.0'
            self._log('INFO', f'portmap listening on {display_host}:{self._portmap.port}')
        except (OSError, RuntimeError) as exc:
            self._portmap = None
            self._own_portmap = False
            self._log('WARN', f'本地 portmap 端口被占用 (已使用系统已有的): {exc}')

        for label, prog, vers in self._VXI11_PROGRAMS:
            channel = _TcpPassthrough(
                label=f'VXI-11 {label}',
                listen_host=self._listen_host,
                listen_port=0,
                target_host=self._target_host,
                target_port_provider=lambda p=prog, v=vers: self._resolve_remote_port(p, v),
                log=self._log,
            )
            channel.start()
            self._channels[label] = channel
            self._register(prog, vers, channel.bound_port, portmap_host)

        core_port = self._channels['core'].bound_port
        async_port = self._channels['async'].bound_port
        self._log(
            'INFO',
            f'VXI-11 直转: core :{core_port} / async :{async_port} → {self._target_host} (远端 portmap 自动查找)',
        )

    def _register(self, prog: int, vers: int, port: int, portmap_host: str) -> None:
        mapping = (prog, vers, vxi11_rpc.IPPROTO_TCP, port)
        if self._own_portmap and self._portmap is not None:
            # Talk straight to our own PortMapServer's dict — no need for the
            # round-trip through TCP.
            self._portmap.mappings[(prog, vers, vxi11_rpc.IPPROTO_TCP)] = port
            return
        try:
            pmap = vxi11_rpc.TCPPortMapperClient(portmap_host)
            try:
                pmap.unset(mapping)
            except Exception:
                pass
            if not pmap.set(mapping):
                raise RuntimeError('register failed')
        except Exception as exc:
            self._log(
                'ERROR',
                f'向 portmap 注册 {prog:#x} v{vers} 失败: {exc}',
            )
            raise

    def _unregister(self, prog: int, vers: int, port: int, portmap_host: str) -> None:
        mapping = (prog, vers, vxi11_rpc.IPPROTO_TCP, port)
        if self._own_portmap and self._portmap is not None:
            self._portmap.mappings.pop((prog, vers, vxi11_rpc.IPPROTO_TCP), None)
            return
        try:
            pmap = vxi11_rpc.TCPPortMapperClient(portmap_host)
            pmap.unset(mapping)
        except Exception as exc:
            self._log(
                'WARN',
                f'portmap unset {prog:#x} 异常 (已忽略): {exc}',
            )

    def stop(self) -> None:
        portmap_host = self._listen_host or '127.0.0.1'
        for label, prog, vers in self._VXI11_PROGRAMS:
            channel = self._channels.pop(label, None)
            if channel is None:
                continue
            try:
                self._unregister(prog, vers, channel.bound_port, portmap_host)
            except Exception:
                pass
            try:
                channel.stop()
            except Exception:
                pass
        if self._portmap is not None:
            try:
                self._portmap.stop()
            except Exception as exc:
                self._log('WARN', f'portmap stop 异常 (已忽略): {exc}')
            self._portmap = None


def make_passthrough_source(
    src_addr: AddressInfo,
    target_addr: AddressInfo,
    log: Optional[LogSink] = None,
):
    """Build a same-protocol passthrough source for ``src_addr``.

    The caller is responsible for verifying that ``src_addr.transport ==
    target_addr.transport`` before invoking this.
    """
    if src_addr.transport is Transport.SOCKET:
        return SocketPassthroughSource(src_addr, target_addr.host, target_addr.port, log)
    if src_addr.transport is Transport.HISLIP:
        return HislipPassthroughSource(src_addr, target_addr.host, target_addr.port, log)
    if src_addr.transport is Transport.VXI11:
        return Vxi11PassthroughSource(src_addr, target_addr.host, log)
    raise ValueError(f'unsupported passthrough transport: {src_addr.transport}')
