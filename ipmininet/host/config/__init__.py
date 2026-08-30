"""This module holds the configuration generators for daemons
that can be used in a host."""

from .base import HostConfig, HostDaemon
from .named import AAAARecord, ARecord, DNSZone, Named, NSRecord, PTRRecord, SOARecord

__all__ = [
    "AAAARecord",
    "ARecord",
    "DNSZone",
    "HostConfig",
    "HostDaemon",
    "NSRecord",
    "Named",
    "PTRRecord",
    "SOARecord",
]
