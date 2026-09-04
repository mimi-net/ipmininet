"""Router configurations that add the routing daemons themselves.

``BasicRouterConfig`` and ``BorderRouterConfig`` need the OSPF, OSPF6 and BGP
daemon configuration classes, which in turn import ``.base``. They live in
their own module so that ``.base`` does not import those daemons.
"""

from collections.abc import Iterable
from typing import TYPE_CHECKING

from .base import DaemonOption, RouterConfig
from .bgp import AF_INET, AF_INET6, BGP
from .ospf import OSPF
from .ospf6 import OSPF6

if TYPE_CHECKING:
    from ipmininet.router import Router


class BasicRouterConfig(RouterConfig):
    """A basic router that will run an OSPF daemon"""

    def __init__(
        self,
        node: "Router",
        daemons: Iterable[DaemonOption] = (),
        additional_daemons: Iterable[DaemonOption] = (),
        *args,
        **kwargs,
    ):
        """A simple router made of at least an OSPF daemon

        :param additional_daemons: Other daemons that should be used"""
        # We don't want any zebra-specific settings, so we rely on the
        # OSPF/OSPF6 DEPENDS list for that daemon to run it with default
        # settings. We also don't want specific settings beside the defaults,
        # so we don't provide an instance but the class instead
        d = list(daemons)
        if node.use_v4:
            d.append(OSPF)
        if node.use_v6:
            d.append(OSPF6)
        d.extend(additional_daemons)
        super().__init__(node, *args, daemons=d, **kwargs)


class BorderRouterConfig(BasicRouterConfig):
    """A router config that will run both OSPF and BGP, and redistribute all
    connected router into BGP."""

    def __init__(
        self,
        node: "Router",
        daemons: Iterable[DaemonOption] = (),
        additional_daemons: Iterable[DaemonOption] = (),
        *args,
        **kwargs,
    ):
        """A simple router made of at least an OSPF daemon and a BGP daemon

        :param additional_daemons: Other daemons that should be used"""
        af = []
        if node.use_v4:
            af.append(AF_INET(redistribute=("connected", "ospf")))
        if node.use_v6:
            af.append(AF_INET6(redistribute=("connected", "ospf6")))
        if af:
            d = list(daemons)
            d.append((BGP, {"address_families": af}))
        super().__init__(node, *args, daemons=d, **kwargs)
