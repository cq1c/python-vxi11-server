"""Build relay endpoints from a parsed VISA address."""

from __future__ import annotations

from typing import Optional

from .base import (
    AddressInfo,
    LogSink,
    RelayClient,
    RelaySource,
    TargetFactory,
    Transport,
)
from .hislip import HislipSourceServer, HislipTargetClient
from .socket_relay import SocketSourceServer, SocketTargetClient
from .vxi11_relay import Vxi11SourceServer, Vxi11TargetClient


def make_target(info: AddressInfo) -> RelayClient:
    if info.transport is Transport.VXI11:
        return Vxi11TargetClient(info)
    if info.transport is Transport.HISLIP:
        return HislipTargetClient(info)
    if info.transport is Transport.SOCKET:
        return SocketTargetClient(info)
    raise ValueError(f'unsupported transport: {info.transport}')


def make_source(
    info: AddressInfo,
    target_factory: TargetFactory,
    log: Optional[LogSink] = None,
) -> RelaySource:
    if info.transport is Transport.VXI11:
        return Vxi11SourceServer(info, target_factory, log)
    if info.transport is Transport.HISLIP:
        return HislipSourceServer(info, target_factory, log)
    if info.transport is Transport.SOCKET:
        return SocketSourceServer(info, target_factory, log)
    raise ValueError(f'unsupported transport: {info.transport}')
