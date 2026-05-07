"""Raw TCP socket VISA transport (``...::PORT::SOCKET``).

The SOCKET transport has no protocol envelope — it is the byte stream as
received over TCP. We use the SCPI convention that messages end with a
linefeed, and that any message containing ``?`` expects a response.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from typing import Optional

from .base import (
    AddressInfo,
    LogSink,
    RelayClient,
    RelaySource,
    TargetFactory,
    listen_host_for_source,
)

LINE_TERMINATOR = b'\n'
DEFAULT_READ_BUF = 4096
DEFAULT_TIMEOUT = 10.0
TRAILING_TERMINATOR_TIMEOUT = 0.05


def _looks_like_query(data: bytes) -> bool:
    return b'?' in data


class SocketTargetClient(RelayClient):
    """Connects to a raw-TCP instrument (``TCPIP::host::PORT::SOCKET``)."""

    def __init__(self, info: AddressInfo, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.info = info
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._rx_buffer = bytearray()
        self._pending_response = bytearray()

    def open(self) -> None:
        if self._sock is not None:
            return
        s = socket.create_connection((self.info.host, self.info.port), timeout=self.timeout)
        # Use blocking sockets with a timeout — read_raw needs to bound.
        s.settimeout(self.timeout)
        self._sock = s

    def close(self) -> None:
        s = self._sock
        self._sock = None
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    def write_raw(self, data: bytes) -> None:
        if self._sock is None:
            self.open()
        assert self._sock is not None
        # Make sure each write ends with a newline so the instrument sees
        # a complete SCPI message; clients on top of pyvisa already do
        # this, but VXI-11 source clients won't.
        if not data.endswith(LINE_TERMINATOR):
            data = data + LINE_TERMINATOR
        self._sock.sendall(data)

    def read_raw(self, max_size: int = -1) -> bytes:
        if self._sock is None:
            self.open()
        assert self._sock is not None
        limit = max_size if max_size and max_size > 0 else None
        if not self._pending_response:
            self._pending_response.extend(self._read_complete_response())
        if limit is None or len(self._pending_response) <= limit:
            data = bytes(self._pending_response)
            self._pending_response.clear()
            return data
        data = bytes(self._pending_response[:limit])
        del self._pending_response[:limit]
        return data

    def has_pending_read_data(self) -> bool:
        return bool(self._pending_response)

    def _recv_into_buffer(self) -> None:
        assert self._sock is not None
        chunk = self._sock.recv(DEFAULT_READ_BUF)
        if not chunk:
            raise ConnectionError('socket peer closed during recv')
        self._rx_buffer.extend(chunk)

    def _fill_until(self, size: int) -> None:
        while len(self._rx_buffer) < size:
            self._recv_into_buffer()

    def _read_until_terminator(self) -> bytes:
        while LINE_TERMINATOR not in self._rx_buffer:
            self._recv_into_buffer()
        end = self._rx_buffer.index(LINE_TERMINATOR) + 1
        data = bytes(self._rx_buffer[:end])
        del self._rx_buffer[:end]
        return data

    def _read_complete_response(self) -> bytes:
        self._fill_until(1)
        if self._rx_buffer[:1] != b'#':
            return self._read_until_terminator()

        self._fill_until(2)
        digits_byte = self._rx_buffer[1]
        if digits_byte < ord('0') or digits_byte > ord('9'):
            return self._read_until_terminator()

        digits = digits_byte - ord('0')
        if digits == 0:
            return self._read_until_terminator()

        header_size = 2 + digits
        self._fill_until(header_size)
        payload_len_bytes = bytes(self._rx_buffer[2:header_size])
        if not payload_len_bytes.isdigit():
            return self._read_until_terminator()
        payload_len = int(payload_len_bytes.decode('ascii'))
        total = header_size + payload_len
        self._fill_until(total)
        total = self._include_buffered_terminator(total)
        data = bytes(self._rx_buffer[:total])
        del self._rx_buffer[:total]
        return data

    def _include_buffered_terminator(self, total: int) -> int:
        if len(self._rx_buffer) > total:
            return self._extend_past_terminator(total, allow_wait_for_lf=True)

        assert self._sock is not None
        previous_timeout = self._sock.gettimeout()
        try:
            self._sock.settimeout(TRAILING_TERMINATOR_TIMEOUT)
            try:
                chunk = self._sock.recv(2)
            except socket.timeout:
                return total
            if chunk:
                self._rx_buffer.extend(chunk)
                return self._extend_past_terminator(total, allow_wait_for_lf=True)
            return total
        finally:
            self._sock.settimeout(previous_timeout)

    def _extend_past_terminator(self, total: int, allow_wait_for_lf: bool) -> int:
        if self._rx_buffer[total:total + 2] == b'\r\n':
            return total + 2
        if self._rx_buffer[total:total + 1] == b'\n':
            return total + 1
        if self._rx_buffer[total:total + 1] == b'\r':
            if allow_wait_for_lf and len(self._rx_buffer) == total + 1:
                self._try_buffer_optional_lf()
                if self._rx_buffer[total:total + 2] == b'\r\n':
                    return total + 2
            return total + 1
        return total

    def _try_buffer_optional_lf(self) -> None:
        assert self._sock is not None
        previous_timeout = self._sock.gettimeout()
        try:
            self._sock.settimeout(TRAILING_TERMINATOR_TIMEOUT)
            try:
                chunk = self._sock.recv(1)
            except socket.timeout:
                return
            self._rx_buffer.extend(chunk)
        finally:
            self._sock.settimeout(previous_timeout)


class SocketSourceServer(RelaySource):
    """A TCP server that accepts SCPI clients and forwards traffic.

    Each client connection gets its own target session: the relay opens
    a fresh ``RelayClient`` on connect and closes it on disconnect. The
    handler operates in a synchronous ``write → optional read`` loop —
    it forwards every received line to the target, and if the line is a
    query (contains ``?``) it reads the target response and writes it
    back to the client.
    """

    def __init__(
        self,
        info: AddressInfo,
        target_factory: TargetFactory,
        log: Optional[LogSink] = None,
    ) -> None:
        super().__init__(info, target_factory, log)
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._server is not None:
            return

        host = listen_host_for_source(self.info.host)
        port = self.info.port

        relay = self  # captured by handler

        class _Handler(socketserver.BaseRequestHandler):
            def handle(self):  # noqa: D401 — framework hook
                client = None
                try:
                    client = relay.target_factory()
                    client.open()
                except Exception as exc:
                    relay.log('ERROR', f'目标连接失败: {exc}')
                    return
                relay.log('INFO', f'SOCKET 客户端已连接 {self.client_address}')

                self.request.settimeout(None)
                pending = bytearray()
                try:
                    while True:
                        chunk = self.request.recv(DEFAULT_READ_BUF)
                        if not chunk:
                            break
                        pending.extend(chunk)
                        # Drain whole lines.
                        while True:
                            nl = pending.find(LINE_TERMINATOR)
                            if nl < 0:
                                break
                            line = bytes(pending[: nl + 1])
                            del pending[: nl + 1]
                            relay._handle_message(client, line, self.request)
                finally:
                    relay.log('INFO', f'SOCKET 客户端已断开 {self.client_address}')
                    try:
                        client.close()
                    except Exception:
                        pass

        class _Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = _Server((host, port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f'socket-relay-{port}',
            daemon=True,
        )
        self._thread.start()

    def _handle_message(self, client: RelayClient, line: bytes, sock) -> None:
        text = line.rstrip(b'\r\n').decode('ascii', errors='replace')
        try:
            client.write_raw(line)
            self.log('INFO', f'>>> {text}')
        except Exception as exc:
            self.log('ERROR', f'write 失败: {exc}')
            return
        if not _looks_like_query(line):
            return
        try:
            response = client.read_raw()
        except Exception as exc:
            self.log('ERROR', f'read 失败: {exc}')
            return
        if not response:
            return
        if not response.endswith(LINE_TERMINATOR):
            response = response + LINE_TERMINATOR
        try:
            sock.sendall(response)
            preview = response.rstrip(b'\r\n').decode('ascii', errors='replace')
            self.log('INFO', f'<<< {preview}')
        except OSError as exc:
            self.log('ERROR', f'回写客户端失败: {exc}')

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
