"""Common abstractions shared by every transport implementation."""

from __future__ import annotations

import enum
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional


class Transport(str, enum.Enum):
    VXI11 = 'vxi11'
    HISLIP = 'hislip'
    SOCKET = 'socket'


@dataclass
class AddressInfo:
    """Parsed VISA resource string."""

    raw: str
    transport: Transport
    host: str
    # VXI-11 device name (``inst0``, ``gpib,5`` ...). None for non-VXI-11.
    device: Optional[str] = None
    # HiSLIP sub-address (``hislip0``). None for other transports.
    hislip_name: Optional[str] = None
    # TCP port. Defaults are filled in based on transport when not specified
    # in the resource string.
    port: int = 0
    extras: dict = field(default_factory=dict)


# ``TCPIP[board]::host[::sub]::SUFFIX``. Permissive on whitespace and case.
_TCPIP_RE = re.compile(
    r'^\s*TCPIP\d*::([A-Za-z0-9_.\-]+)(?:::([A-Za-z0-9_,\[\]:.\-]+))?::([A-Za-z]+)\s*$',
    re.IGNORECASE,
)
_HISLIP_RE = re.compile(r'^hislip(\d+)(?:,(\d+))?$', re.IGNORECASE)


VXI11_DEFAULT_PORT = 0  # discovered via portmap
HISLIP_DEFAULT_PORT = 4880
SOCKET_DEFAULT_PORT = 5025


def parse_address(addr: str) -> Optional[AddressInfo]:
    """Parse a VISA resource string. Returns None on failure.

    Recognised forms (case-insensitive):

      TCPIP[N]::host[::device]::INSTR        VXI-11
      TCPIP[N]::host::hislipN[,port]::INSTR  HiSLIP
      TCPIP[N]::host::PORT::SOCKET           Raw TCP socket
    """
    if not addr:
        return None
    m = _TCPIP_RE.match(addr)
    if not m:
        return None
    host = m.group(1)
    sub = m.group(2)
    suffix = m.group(3).upper()

    if suffix == 'SOCKET':
        if not sub or not sub.isdigit():
            return None
        return AddressInfo(
            raw=addr.strip(),
            transport=Transport.SOCKET,
            host=host,
            port=int(sub),
        )

    if suffix == 'INSTR':
        if sub:
            mh = _HISLIP_RE.match(sub)
            if mh:
                port = int(mh.group(2)) if mh.group(2) else HISLIP_DEFAULT_PORT
                return AddressInfo(
                    raw=addr.strip(),
                    transport=Transport.HISLIP,
                    host=host,
                    hislip_name=sub.lower().split(',', 1)[0],
                    port=port,
                )
        device = sub or 'inst0'
        return AddressInfo(
            raw=addr.strip(),
            transport=Transport.VXI11,
            host=host,
            device=device,
        )

    return None


LogSink = Callable[[str, str], None]


def _silent_log(_level: str, _msg: str) -> None:
    pass


def listen_host_for_source(source_host: str) -> str:
    """Return the local bind host for a source VISA address.

    The host in a VISA resource is the address clients use to reach this
    relay. For LAN/public/NAT addresses, bind all IPv4 interfaces because the
    address may not be assigned to the local machine. Keep explicit loopback
    mappings private.
    """
    host = (source_host or '').strip().lower()
    if host == 'localhost' or host.startswith('127.'):
        return '127.0.0.1'
    return ''


class RelayClient(ABC):
    """A connection to the upstream real instrument.

    Each transport provides a concrete implementation. Sources call
    :meth:`open` once per session, then a sequence of
    :meth:`write_raw` / :meth:`read_raw` pairs, and finally :meth:`close`.
    Implementations must be safe to use from a single thread; the source
    layer serialises calls.
    """

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write_raw(self, data: bytes) -> None: ...

    @abstractmethod
    def read_raw(self, max_size: int = -1) -> bytes: ...


TargetFactory = Callable[[], RelayClient]


class RelaySource(ABC):
    """Local server endpoint that exposes the relay to client tools."""

    def __init__(
        self,
        info: AddressInfo,
        target_factory: TargetFactory,
        log: Optional[LogSink] = None,
    ) -> None:
        self.info = info
        self.target_factory = target_factory
        self.log: LogSink = log or _silent_log

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
