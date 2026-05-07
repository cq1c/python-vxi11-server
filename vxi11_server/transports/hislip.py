"""HiSLIP (IVI-6.1) transport: minimal client + server.

HiSLIP is an instrument protocol over TCP, normally on port 4880. Each
session uses two TCP connections (synchronous + asynchronous channel)
that the client opens in sequence; both channels speak a common 16-byte
framing header.

This implementation covers the common-case write/read message flow used
for SCPI relay:

* Initialize / InitializeResponse handshake
* AsyncInitialize / AsyncInitializeResponse
* AsyncMaximumMessageSize / AsyncMaximumMessageSizeResponse
* Data / DataEnd (with rolling MessageID)
* FatalError / Error pass-through

Locking, async device clear, service requests, trigger, TLS/credentials
and remote/local are NOT implemented. They send a polite ``Error`` reply
or are ignored.
"""

from __future__ import annotations

import socket
import socketserver
import struct
import threading
import time
from typing import Dict, Optional, Tuple

from .base import (
    AddressInfo,
    HISLIP_DEFAULT_PORT,
    LogSink,
    RelayClient,
    RelaySource,
    TargetFactory,
)


# ---- Protocol constants ---------------------------------------------------

PROLOGUE = b'HS'
HEADER_FMT = '>2sBBIQ'
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 16

# Message types we handle.
MSG_INITIALIZE = 0
MSG_INITIALIZE_RESPONSE = 1
MSG_FATAL_ERROR = 2
MSG_ERROR = 3
MSG_ASYNC_LOCK = 4
MSG_ASYNC_LOCK_RESPONSE = 5
MSG_DATA = 6
MSG_DATA_END = 7
MSG_DEVICE_CLEAR_COMPLETE = 8
MSG_DEVICE_CLEAR_ACKNOWLEDGE = 9
MSG_ASYNC_REMOTE_LOCAL_CONTROL = 10
MSG_ASYNC_REMOTE_LOCAL_RESPONSE = 11
MSG_TRIGGER = 12
MSG_INTERRUPTED = 13
MSG_ASYNC_INTERRUPTED = 14
MSG_ASYNC_MAXIMUM_MESSAGE_SIZE = 15
MSG_ASYNC_MAXIMUM_MESSAGE_SIZE_RESPONSE = 16
MSG_ASYNC_INITIALIZE = 17
MSG_ASYNC_INITIALIZE_RESPONSE = 18
MSG_ASYNC_DEVICE_CLEAR = 19
MSG_ASYNC_SERVICE_REQUEST = 20
MSG_ASYNC_STATUS_QUERY = 21
MSG_ASYNC_STATUS_RESPONSE = 22
MSG_ASYNC_DEVICE_CLEAR_ACKNOWLEDGE = 23
MSG_ASYNC_LOCK_INFO = 24
MSG_ASYNC_LOCK_INFO_RESPONSE = 25

# Default protocol version: 1.0 (0x0100). We do not implement the v2
# additions (TLS, credentials, GET_DESCRIPTORS).
DEFAULT_PROTOCOL_VERSION = 0x0100
DEFAULT_VENDOR_ID = b'XX'
DEFAULT_MAX_MESSAGE_SIZE = 1 << 20  # 1 MiB


def pack_header(
    msg_type: int,
    control_code: int = 0,
    message_parameter: int = 0,
    payload: bytes = b'',
) -> bytes:
    return struct.pack(
        HEADER_FMT,
        PROLOGUE,
        msg_type,
        control_code,
        message_parameter,
        len(payload),
    ) + payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('hislip peer closed during recv')
        buf.extend(chunk)
    return bytes(buf)


def read_message(sock: socket.socket) -> Tuple[int, int, int, bytes]:
    """Block until a full HiSLIP message has been read.

    Returns (msg_type, control_code, message_parameter, payload).
    """
    header = _recv_exact(sock, HEADER_SIZE)
    prologue, msg_type, control_code, message_parameter, payload_len = struct.unpack(
        HEADER_FMT, header
    )
    if prologue != PROLOGUE:
        raise IOError(f'hislip bad prologue: {prologue!r}')
    payload = _recv_exact(sock, payload_len) if payload_len else b''
    return msg_type, control_code, message_parameter, payload


# ---- Target client --------------------------------------------------------


class HislipTargetClient(RelayClient):
    """HiSLIP client used by the relay target side."""

    def __init__(
        self,
        info: AddressInfo,
        timeout: float = 10.0,
        max_message_size: int = DEFAULT_MAX_MESSAGE_SIZE,
    ) -> None:
        self.info = info
        self.timeout = timeout
        self.max_message_size = max_message_size
        self._sync: Optional[socket.socket] = None
        self._async: Optional[socket.socket] = None
        self._async_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._message_id: int = 0xFFFF_FF00

    # -- session lifecycle --

    def open(self) -> None:
        if self._sync is not None:
            return
        host = self.info.host
        port = self.info.port or HISLIP_DEFAULT_PORT
        sub = self.info.hislip_name or 'hislip0'

        sync_sock = socket.create_connection((host, port), timeout=self.timeout)
        sync_sock.settimeout(self.timeout)
        message_parameter = (DEFAULT_PROTOCOL_VERSION << 16) | int.from_bytes(
            DEFAULT_VENDOR_ID, 'big'
        )
        sync_sock.sendall(
            pack_header(
                MSG_INITIALIZE,
                control_code=0,
                message_parameter=message_parameter,
                payload=sub.encode('ascii'),
            )
        )
        msg_type, _ctrl, mparam, _payload = read_message(sync_sock)
        if msg_type != MSG_INITIALIZE_RESPONSE:
            sync_sock.close()
            raise IOError(f'hislip: unexpected reply {msg_type}')
        # Upper 16 bits = ServerProtocolVersion, lower 16 bits = SessionID.
        session_id = mparam & 0xFFFF

        async_sock = socket.create_connection((host, port), timeout=self.timeout)
        async_sock.settimeout(self.timeout)
        async_sock.sendall(
            pack_header(MSG_ASYNC_INITIALIZE, message_parameter=session_id)
        )
        msg_type, _ctrl, _mparam, _payload = read_message(async_sock)
        if msg_type != MSG_ASYNC_INITIALIZE_RESPONSE:
            sync_sock.close()
            async_sock.close()
            raise IOError(f'hislip: unexpected async reply {msg_type}')

        # Negotiate max message size on async channel.
        async_sock.sendall(
            pack_header(
                MSG_ASYNC_MAXIMUM_MESSAGE_SIZE,
                payload=struct.pack('>Q', self.max_message_size),
            )
        )
        msg_type, _ctrl, _mparam, payload = read_message(async_sock)
        if msg_type == MSG_ASYNC_MAXIMUM_MESSAGE_SIZE_RESPONSE and len(payload) >= 8:
            (server_max,) = struct.unpack('>Q', payload[:8])
            self.max_message_size = min(self.max_message_size, server_max or self.max_message_size)

        self._sync = sync_sock
        self._async = async_sock

    def close(self) -> None:
        for attr in ('_sync', '_async'):
            sock = getattr(self, attr)
            setattr(self, attr, None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

    # -- I/O --

    def _next_message_id(self) -> int:
        # MessageIDs increment by 2 per spec; the server echoes them back.
        self._message_id = (self._message_id + 2) & 0xFFFFFFFF
        return self._message_id

    def write_raw(self, data: bytes) -> None:
        if self._sync is None:
            self.open()
        assert self._sync is not None
        chunk_size = max(self.max_message_size - HEADER_SIZE, 1024)
        with self._sync_lock:
            offset = 0
            total = len(data)
            while offset < total:
                end = min(offset + chunk_size, total)
                last = end >= total
                msg_type = MSG_DATA_END if last else MSG_DATA
                self._sync.sendall(
                    pack_header(
                        msg_type,
                        message_parameter=self._next_message_id(),
                        payload=data[offset:end],
                    )
                )
                offset = end
            if total == 0:
                # Spec requires at least one DataEnd to mark message boundary.
                self._sync.sendall(
                    pack_header(MSG_DATA_END, message_parameter=self._next_message_id())
                )

    def read_raw(self, max_size: int = -1) -> bytes:
        if self._sync is None:
            self.open()
        assert self._sync is not None
        limit = max_size if max_size and max_size > 0 else 1 << 30
        buf = bytearray()
        with self._sync_lock:
            while True:
                msg_type, _ctrl, _mparam, payload = read_message(self._sync)
                if msg_type in (MSG_DATA, MSG_DATA_END):
                    buf.extend(payload)
                    if len(buf) > limit:
                        del buf[limit:]
                    if msg_type == MSG_DATA_END:
                        break
                elif msg_type in (MSG_FATAL_ERROR, MSG_ERROR):
                    raise IOError(
                        f'hislip remote error type={msg_type} '
                        f'msg={payload.decode("ascii", errors="replace")!r}'
                    )
                elif msg_type == MSG_INTERRUPTED:
                    # Clear any partial data and continue waiting.
                    buf.clear()
                else:
                    # Unhandled informational message — keep going.
                    continue
        return bytes(buf)


# ---- Source server --------------------------------------------------------


class _SessionRegistry:
    """Pairs sync + async sockets that share a session ID."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._next_id = 1
        self._pending_sync: Dict[int, threading.Event] = {}
        self._sessions: Dict[int, '_HislipSession'] = {}

    def allocate(self, session: '_HislipSession') -> int:
        with self._cond:
            sid = self._next_id
            self._next_id = (self._next_id + 1) & 0xFFFF
            if self._next_id == 0:
                self._next_id = 1
            self._sessions[sid] = session
            self._cond.notify_all()
            return sid

    def attach_async(self, session_id: int, sock: socket.socket, timeout: float = 5.0) -> Optional['_HislipSession']:
        deadline = time.monotonic() + timeout
        with self._cond:
            while session_id not in self._sessions:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            return self._sessions[session_id]

    def remove(self, session_id: int) -> None:
        with self._cond:
            self._sessions.pop(session_id, None)


class _HislipSession:
    """Active HiSLIP session: a sync socket + async socket + target client.

    Owns the threads that pump messages on each socket. The synchronous
    side feeds writes/reads through the upstream relay client.
    """

    def __init__(
        self,
        registry: _SessionRegistry,
        target_factory: TargetFactory,
        log: LogSink,
        sync_sock: socket.socket,
    ) -> None:
        self.registry = registry
        self.target_factory = target_factory
        self.log = log
        self.sync_sock = sync_sock
        self.async_sock: Optional[socket.socket] = None
        self.session_id = registry.allocate(self)
        self.async_ready = threading.Event()
        self.client: Optional[RelayClient] = None
        self.max_message_size = DEFAULT_MAX_MESSAGE_SIZE
        self._closed = False
        self._lock = threading.Lock()

    # -- handshake helpers --

    def send_initialize_response(self, server_version: int) -> None:
        message_parameter = (server_version << 16) | (self.session_id & 0xFFFF)
        self.sync_sock.sendall(
            pack_header(
                MSG_INITIALIZE_RESPONSE,
                control_code=0,  # synchronous (non-overlap) mode
                message_parameter=message_parameter,
            )
        )

    def attach_async(self, sock: socket.socket) -> None:
        self.async_sock = sock
        self.async_ready.set()

    # -- main loops --

    def run_sync(self) -> None:
        """Drive the sync channel: collect Data*+DataEnd into messages."""
        if not self.async_ready.wait(timeout=10):
            self.log('ERROR', 'HiSLIP: 异步通道未在限定时间内连入')
            self.close()
            return

        try:
            self.client = self.target_factory()
            self.client.open()
        except Exception as exc:
            self.log('ERROR', f'HiSLIP 目标连接失败: {exc}')
            self.close()
            return

        self.log('INFO', f'HiSLIP 会话 {self.session_id} 已建立')
        self.sync_sock.settimeout(None)

        buf = bytearray()
        try:
            while not self._closed:
                msg_type, _ctrl, _mparam, payload = read_message(self.sync_sock)
                if msg_type == MSG_DATA:
                    buf.extend(payload)
                elif msg_type == MSG_DATA_END:
                    buf.extend(payload)
                    self._handle_request(bytes(buf))
                    buf.clear()
                elif msg_type == MSG_TRIGGER:
                    self.log('INFO', 'HiSLIP: TRIGGER 已忽略')
                elif msg_type in (MSG_FATAL_ERROR, MSG_ERROR):
                    self.log('WARN', f'HiSLIP 客户端报告错误: {payload!r}')
                    if msg_type == MSG_FATAL_ERROR:
                        break
                else:
                    # Reply with a non-fatal Error for unsupported types.
                    self._send_error(reason=1, text=f'unsupported message {msg_type}')
        except (ConnectionError, OSError) as exc:
            self.log('INFO', f'HiSLIP 同步通道关闭: {exc}')
        except Exception as exc:
            self.log('ERROR', f'HiSLIP 同步通道异常: {exc}')
        finally:
            self.close()

    def run_async(self) -> None:
        """Drive the async channel: respond to lock/maxsize/etc requests."""
        try:
            assert self.async_sock is not None
            self.async_sock.settimeout(None)
            while not self._closed:
                msg_type, ctrl, mparam, payload = read_message(self.async_sock)
                if msg_type == MSG_ASYNC_MAXIMUM_MESSAGE_SIZE:
                    if len(payload) >= 8:
                        (requested,) = struct.unpack('>Q', payload[:8])
                        self.max_message_size = max(1024, requested)
                    self.async_sock.sendall(
                        pack_header(
                            MSG_ASYNC_MAXIMUM_MESSAGE_SIZE_RESPONSE,
                            payload=struct.pack('>Q', self.max_message_size),
                        )
                    )
                elif msg_type == MSG_ASYNC_LOCK:
                    # control_code: 0=release, 1=request. Reply success either way.
                    self.async_sock.sendall(
                        pack_header(
                            MSG_ASYNC_LOCK_RESPONSE,
                            control_code=1 if ctrl else 1,
                        )
                    )
                elif msg_type == MSG_ASYNC_LOCK_INFO:
                    self.async_sock.sendall(
                        pack_header(MSG_ASYNC_LOCK_INFO_RESPONSE, message_parameter=0)
                    )
                elif msg_type == MSG_ASYNC_DEVICE_CLEAR:
                    self.async_sock.sendall(
                        pack_header(
                            MSG_ASYNC_DEVICE_CLEAR_ACKNOWLEDGE,
                            control_code=0,
                            message_parameter=0,
                        )
                    )
                elif msg_type == MSG_ASYNC_STATUS_QUERY:
                    self.async_sock.sendall(
                        pack_header(MSG_ASYNC_STATUS_RESPONSE, message_parameter=0)
                    )
                elif msg_type == MSG_ASYNC_REMOTE_LOCAL_CONTROL:
                    self.async_sock.sendall(
                        pack_header(MSG_ASYNC_REMOTE_LOCAL_RESPONSE)
                    )
                else:
                    # ignore other async messages
                    continue
        except (ConnectionError, OSError):
            pass
        except Exception as exc:
            self.log('ERROR', f'HiSLIP 异步通道异常: {exc}')
        finally:
            self.close()

    # -- relay helpers --

    def _handle_request(self, message: bytes) -> None:
        if self.client is None:
            return
        preview = message.decode('ascii', errors='replace').strip()
        try:
            self.client.write_raw(message)
            self.log('INFO', f'>>> {preview}')
        except Exception as exc:
            self.log('ERROR', f'write 失败: {exc}')
            self._send_error(reason=2, text=str(exc))
            return

        if b'?' not in message:
            return

        try:
            response = self.client.read_raw()
        except Exception as exc:
            self.log('ERROR', f'read 失败: {exc}')
            self._send_error(reason=3, text=str(exc))
            return
        self._send_data(response)

    def _send_data(self, response: bytes) -> None:
        chunk_size = max(self.max_message_size - HEADER_SIZE, 1024)
        with self._lock:
            offset = 0
            total = len(response)
            while offset < total:
                end = min(offset + chunk_size, total)
                last = end >= total
                msg_type = MSG_DATA_END if last else MSG_DATA
                self.sync_sock.sendall(
                    pack_header(msg_type, message_parameter=0, payload=response[offset:end])
                )
                offset = end
            if total == 0:
                self.sync_sock.sendall(pack_header(MSG_DATA_END))
        preview = response.decode('ascii', errors='replace').strip()
        self.log('INFO', f'<<< {preview}')

    def _send_error(self, reason: int, text: str) -> None:
        try:
            self.sync_sock.sendall(
                pack_header(
                    MSG_ERROR,
                    control_code=reason,
                    payload=text.encode('ascii', errors='replace')[:200],
                )
            )
        except OSError:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.registry.remove(self.session_id)
        for sock in (self.sync_sock, self.async_sock):
            if sock is None:
                continue
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None


class HislipSourceServer(RelaySource):
    """Listens on a single TCP port for HiSLIP sync + async connections."""

    def __init__(
        self,
        info: AddressInfo,
        target_factory: TargetFactory,
        log: Optional[LogSink] = None,
    ) -> None:
        super().__init__(info, target_factory, log)
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._registry = _SessionRegistry()

    def start(self) -> None:
        if self._server is not None:
            return
        host = self.info.host if self.info.host not in ('0.0.0.0', '*') else ''
        port = self.info.port or HISLIP_DEFAULT_PORT

        relay = self

        class _Handler(socketserver.BaseRequestHandler):
            def handle(self):  # noqa: D401 — framework hook
                sock = self.request
                sock.settimeout(10)
                try:
                    msg_type, _ctrl, mparam, payload = read_message(sock)
                except Exception as exc:
                    relay.log('WARN', f'HiSLIP: 初始消息读取失败: {exc}')
                    return

                if msg_type == MSG_INITIALIZE:
                    sub = payload.decode('ascii', errors='replace')
                    relay.log('INFO', f'HiSLIP Initialize sub-address={sub!r}')
                    server_version = min(
                        DEFAULT_PROTOCOL_VERSION,
                        (mparam >> 16) & 0xFFFF,
                    )
                    session = _HislipSession(
                        relay._registry, relay.target_factory, relay.log, sock
                    )
                    session.send_initialize_response(server_version)
                    session.run_sync()
                elif msg_type == MSG_ASYNC_INITIALIZE:
                    session_id = mparam & 0xFFFF
                    session = relay._registry.attach_async(session_id, sock)
                    if session is None:
                        relay.log('WARN', f'HiSLIP: 未匹配的会话 {session_id}')
                        try:
                            sock.sendall(
                                pack_header(MSG_FATAL_ERROR, control_code=1, payload=b'unknown session')
                            )
                        except OSError:
                            pass
                        return
                    session.attach_async(sock)
                    sock.sendall(
                        pack_header(
                            MSG_ASYNC_INITIALIZE_RESPONSE,
                            message_parameter=int.from_bytes(DEFAULT_VENDOR_ID, 'big') << 16,
                        )
                    )
                    session.run_async()
                else:
                    relay.log('WARN', f'HiSLIP: 非预期初始消息 {msg_type}')

        class _Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = _Server((host, port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f'hislip-relay-{port}',
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
