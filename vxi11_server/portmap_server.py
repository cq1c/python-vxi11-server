"""Embedded RPC Portmapper (program 100000, version 2).

A minimal asyncio implementation of the Sun RPC portmapper, listening on
TCP and UDP port 111. It exists so that ``InstrumentServer`` can register
itself and remote VXI-11 clients can look it up without the host OS having
to provide ``rpcbind`` / ``portmap`` — particularly useful on Windows.

Only the procedures required by VXI-11 traffic are implemented:
NULL, SET, UNSET, GETPORT, DUMP.
"""

import asyncio
import logging
import socket
import struct
import threading
from typing import Dict, Tuple

from . import rpc

logger = logging.getLogger(__name__)


class PortMapServer:
    def __init__(self, host: str = '127.0.0.1', port: int = rpc.PMAP_PORT):
        self.host = host
        self.port = port
        self.mappings: Dict[Tuple[int, int, int], int] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tcp_server: asyncio.base_events.Server | None = None
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        # Track live TCP writers so shutdown can abort lingering connections
        # instead of hanging on wait_closed().
        self._writers: set[asyncio.StreamWriter] = set()

    # ---- lifecycle ----------------------------------------------------

    def start(self, timeout: float = 3.0) -> None:
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run, name='portmap-asyncio', daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError('portmap failed to start within timeout')
        if self._error is not None:
            err = self._error
            self._error = None
            raise err

    def stop(self, timeout: float = 2.0) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            fut.result(timeout)
        except Exception as exc:
            logger.warning('portmap shutdown error (ignored): %s', exc)
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout)
        self._loop = None
        self._thread = None

    def _run(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._setup())
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass

    async def _setup(self) -> None:
        self._tcp_server = await asyncio.start_server(
            self._handle_tcp, host=self.host, port=self.port,
            family=socket.AF_INET,
        )
        self._udp_transport, _ = await self._loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self),
            local_addr=(self.host, self.port),
            family=socket.AF_INET,
        )
        logger.info('portmap listening on %s:%d', self.host, self.port)

    async def _shutdown(self) -> None:
        if self._tcp_server is not None:
            self._tcp_server.close()
            self._tcp_server = None
        # Force-close active connections; wait_closed() would otherwise hang
        # until every client peer closes its socket.
        for w in list(self._writers):
            try:
                w.transport.abort()
            except Exception:
                pass
        self._writers.clear()
        if self._udp_transport is not None:
            self._udp_transport.close()
            self._udp_transport = None

    # ---- transport handlers ------------------------------------------

    async def _handle_tcp(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        try:
            while True:
                record = await self._recv_record(reader)
                reply = self._handle_call(record)
                if reply is not None:
                    await self._send_record(writer, reply)
        except (asyncio.IncompleteReadError, ConnectionError, EOFError):
            pass
        finally:
            self._writers.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _recv_record(reader: asyncio.StreamReader) -> bytes:
        buf = bytearray()
        while True:
            header = await reader.readexactly(4)
            x = struct.unpack('>I', header)[0]
            last = (x & 0x80000000) != 0
            n = x & 0x7fffffff
            if n:
                buf.extend(await reader.readexactly(n))
            if last:
                return bytes(buf)

    @staticmethod
    async def _send_record(writer: asyncio.StreamWriter, record: bytes) -> None:
        writer.write(struct.pack('>I', len(record) | 0x80000000) + record)
        await writer.drain()

    # ---- RPC protocol ------------------------------------------------

    def _handle_call(self, data: bytes):
        unpacker = rpc.PortMapperUnpacker(data)
        packer = rpc.PortMapperPacker()
        try:
            xid = unpacker.unpack_uint()
            mtype = unpacker.unpack_enum()
            if mtype != rpc.CALL:
                return None

            packer.pack_uint(xid)
            packer.pack_uint(rpc.REPLY)

            rpcvers = unpacker.unpack_uint()
            if rpcvers != rpc.RPCVERSION:
                packer.pack_uint(rpc.MSG_DENIED)
                packer.pack_uint(rpc.RPC_MISMATCH)
                packer.pack_uint(rpc.RPCVERSION)
                packer.pack_uint(rpc.RPCVERSION)
                return packer.get_buf()

            packer.pack_uint(rpc.MSG_ACCEPTED)
            packer.pack_auth((rpc.AUTH_NULL, rpc.make_auth_null()))

            prog = unpacker.unpack_uint()
            if prog != rpc.PMAP_PROG:
                packer.pack_uint(rpc.PROG_UNAVAIL)
                return packer.get_buf()

            vers = unpacker.unpack_uint()
            if vers != rpc.PMAP_VERS:
                packer.pack_uint(rpc.PROG_MISMATCH)
                packer.pack_uint(rpc.PMAP_VERS)
                packer.pack_uint(rpc.PMAP_VERS)
                return packer.get_buf()

            proc = unpacker.unpack_uint()
            unpacker.unpack_auth()  # cred
            unpacker.unpack_auth()  # verf

            if proc == rpc.PMAPPROC_NULL:
                packer.pack_uint(rpc.SUCCESS)
            elif proc == rpc.PMAPPROC_SET:
                mapping = unpacker.unpack_mapping()
                p, v, prot, port = mapping
                self.mappings[(p, v, prot)] = port
                logger.info('PMAP SET %s', mapping)
                packer.pack_uint(rpc.SUCCESS)
                packer.pack_uint(1)
            elif proc == rpc.PMAPPROC_UNSET:
                mapping = unpacker.unpack_mapping()
                p, v, prot, _port = mapping
                existed = self.mappings.pop((p, v, prot), None) is not None
                # rpcbind in practice returns true for any well-formed UNSET
                # call (the entry is now absent — that is the success). The
                # upstream client raises if we return 0, which would break
                # register()'s pre-clean step on a fresh start.
                logger.info(
                    'PMAP UNSET %s (existed=%s)', mapping, existed
                )
                packer.pack_uint(rpc.SUCCESS)
                packer.pack_uint(1)
            elif proc == rpc.PMAPPROC_GETPORT:
                mapping = unpacker.unpack_mapping()
                p, v, prot, _port = mapping
                port = self.mappings.get((p, v, prot), 0)
                logger.info('PMAP GETPORT %s -> %d', mapping, port)
                packer.pack_uint(rpc.SUCCESS)
                packer.pack_uint(port)
            elif proc == rpc.PMAPPROC_DUMP:
                packer.pack_uint(rpc.SUCCESS)
                items = [
                    (p, v, prot, port)
                    for (p, v, prot), port in self.mappings.items()
                ]
                packer.pack_pmaplist(items)
            else:
                packer.pack_uint(rpc.PROC_UNAVAIL)

            return packer.get_buf()
        except Exception as exc:
            logger.exception('portmap call error: %s', exc)
            return None


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: PortMapServer):
        self.server = server
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        reply = self.server._handle_call(data)
        if reply is not None and self.transport is not None:
            self.transport.sendto(reply, addr)
