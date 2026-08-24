"""This module defines a modular host that is able to support
   multiple daemons
"""

from .__host import CPULimitedHost, IPHost

__all__ = ["CPULimitedHost", "IPHost"]
