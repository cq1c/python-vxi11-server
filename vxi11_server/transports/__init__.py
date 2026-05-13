"""Pluggable VISA transport layer for the relay tool.

Public surface:

* :func:`parse_address` — turn a VISA resource string into an
  :class:`AddressInfo` describing transport kind + endpoint params.
* :func:`make_target` — build a :class:`RelayClient` for a target address.
* :func:`make_source` — build a :class:`RelaySource` for a source address.

Three transports are supported: VXI-11 (``...::INSTR`` with named device),
HiSLIP (``...::hislipN::INSTR``) and raw TCP socket
(``...::PORT::SOCKET``).
"""

from .base import (
    AddressInfo,
    RelayClient,
    RelaySource,
    Transport,
    parse_address,
)
from .factory import make_source, make_target
from .passthrough import make_passthrough_source

__all__ = [
    'AddressInfo',
    'RelayClient',
    'RelaySource',
    'Transport',
    'parse_address',
    'make_source',
    'make_target',
    'make_passthrough_source',
]
