"""VXI-11 transport: target client + source server.

Target side reuses :class:`vxi11.Instrument`. Source side wraps the
existing :class:`InstrumentServer` machinery so a custom target factory
can be plugged in via a per-instance :class:`RelayDevice` subclass.
"""

from __future__ import annotations

import threading
from typing import Optional

from .. import vxi11 as _vxi11
from ..instrument_device import InstrumentDevice, ReadRespReason
from ..instrument_server import Error, InstrumentServer
from ..portmap_server import PortMapServer
from .base import (
    AddressInfo,
    LogSink,
    RelayClient,
    RelaySource,
    TargetFactory,
    listen_host_for_source,
)


class Vxi11TargetClient(RelayClient):
    """Forwards writes/reads to an upstream VXI-11 instrument."""

    def __init__(self, info: AddressInfo) -> None:
        self.info = info
        self._instr: Optional[_vxi11.Instrument] = None

    def open(self) -> None:
        if self._instr is not None:
            return
        self._instr = _vxi11.Instrument(self.info.raw)
        self._instr.open()

    def close(self) -> None:
        if self._instr is None:
            return
        try:
            self._instr.close()
        finally:
            self._instr = None

    def write_raw(self, data: bytes) -> None:
        if self._instr is None:
            self.open()
        assert self._instr is not None
        self._instr.write_raw(data)

    def read_raw(self, max_size: int = -1) -> bytes:
        if self._instr is None:
            self.open()
        assert self._instr is not None
        return self._instr.read_raw(max_size)


class Vxi11SourceServer(RelaySource):
    """Hosts a VXI-11 service that proxies RPCs to a target client.

    A new :class:`Vxi11TargetClient` is created per VXI-11 link, mirroring
    real instruments: each client gets its own session.
    """

    def __init__(
        self,
        info: AddressInfo,
        target_factory: TargetFactory,
        log: Optional[LogSink] = None,
    ) -> None:
        super().__init__(info, target_factory, log)
        self._server: Optional[InstrumentServer] = None
        self._portmap: Optional[PortMapServer] = None

    def start(self) -> None:
        if self._server is not None:
            return

        device_name = (self.info.device or 'inst0')
        device_cls = _build_relay_device(self.target_factory, self.log)

        portmap_host = listen_host_for_source(self.info.host)
        self._portmap = PortMapServer(host=portmap_host)
        try:
            self._portmap.start()
        except OSError as exc:
            self._portmap = None
            self.log('WARN', f'本地 portmap 端口被占用 (已使用系统已有的): {exc}')
        else:
            display_host = portmap_host or '0.0.0.0'
            self.log('INFO', f'portmap listening on {display_host}:111')

        if device_name.lower() == 'inst0':
            self._server = InstrumentServer(default_device_handler=device_cls)
        else:
            self._server = InstrumentServer()
            self._server.add_device_handler(device_cls, device_name)
        self._server.listen()

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.close()
            except Exception as exc:
                self.log('WARN', f'instrument server 收尾异常 (已忽略): {exc}')
                # Bound the join: a half-initialised server can deadlock on
                # shutdown() if its serve_forever loop never started.
                for srv_attr in ('coreServer', 'abortServer'):
                    srv = getattr(server, srv_attr, None)
                    if srv is None:
                        continue
                    t = threading.Thread(target=srv.shutdown, daemon=True)
                    t.start()
                    t.join(timeout=1.5)
                    try:
                        srv.server_close()
                    except Exception:
                        pass

        if self._portmap is not None:
            try:
                self._portmap.stop()
            except Exception as exc:
                self.log('WARN', f'portmap stop 异常 (已忽略): {exc}')
            self._portmap = None


def _build_relay_device(target_factory: TargetFactory, log: LogSink):
    """Return a fresh InstrumentDevice subclass bound to this session.

    InstrumentServer instantiates the handler ``device_class(name, lock)``
    once per VXI-11 link, so we plumb the target factory + log sink in at
    class scope rather than as instance ctor args.
    """

    class _RelayDevice(InstrumentDevice):
        _factory = staticmethod(target_factory)
        _log = staticmethod(log)

        def device_init(self):  # noqa: D401 — framework hook
            self._client: Optional[RelayClient] = None
            try:
                self._client = self._factory()
                self._client.open()
                self._log('INFO', '链接已建立 (VXI-11 source)')
            except Exception as exc:
                self._log('ERROR', f'连接目标设备失败: {exc}')
                self._client = None

        def device_write(self, opaque_data, flags, io_timeout):
            if self._client is None:
                return Error.IO_ERROR
            try:
                self._client.write_raw(opaque_data)
                preview = opaque_data.decode('ascii', errors='replace').strip()
                self._log('INFO', f'>>> {preview}')
                return Error.NO_ERROR
            except Exception as exc:
                self._log('ERROR', f'write 失败: {exc}')
                return Error.IO_ERROR

        def device_read(self, request_size, term_char, flags, io_timeout):
            if self._client is None:
                return Error.IO_ERROR, ReadRespReason.END, b''
            try:
                data = self._client.read_raw(request_size)
                preview = data.decode('ascii', errors='replace').strip()
                self._log('INFO', f'<<< {preview}')
                return Error.NO_ERROR, ReadRespReason.END, data
            except Exception as exc:
                self._log('ERROR', f'read 失败: {exc}')
                return Error.IO_ERROR, ReadRespReason.END, b''

        def __del__(self):
            client = getattr(self, '_client', None)
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    return _RelayDevice
