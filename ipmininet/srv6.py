"""This modules defines classes to create IPv6 Segment Routing (SRv6) Routes
For more information about SRv6, see https://segment-routing.org"""

import abc
import contextlib
import shlex
import subprocess
from collections.abc import Iterable
from ipaddress import (
    AddressValueError,
    IPv4Address,
    IPv6Address,
    IPv6Network,
    NetmaskValueError,
)

from mininet.log import lg as log

from .ipnet import IPNet
from .link import IPIntf
from .router import IPNode
from .utils import address_pair, realIntfList

# Lowest reserved Linux routing table number (253, 254 and 255 are the
# default, main and local tables), hence the highest usable value is 252.
MIN_RESERVED_TABLE = 253


def enable_srv6(node: IPNode):
    """
    Enable IPv6 Segment Routing parsing on all interfaces of the node
    """
    node.nconfig.sysctl = "net.ipv6.conf.all.seg6_enabled=1"
    node.nconfig.sysctl = "net.ipv6.conf.default.seg6_enabled=1"
    for intf in realIntfList(node):
        node.nconfig.sysctl = f"net.ipv6.conf.{intf.name}.seg6_enabled=1"


def check_srv6_compatibility() -> bool:
    """
    :return: True if the distribution supports SRv6
    """
    try:
        subprocess.check_output(shlex.split("sysctl net.ipv6.conf.all.seg6_enabled"))
    except subprocess.CalledProcessError:
        return False
    else:
        return True


def srv6_segment_space(
    node: str | IPNode | None = None, intf: str | IPIntf = "lo"
) -> list[IPv6Network]:
    """
    :param node: The IPNode object representing the node
    :param intf: Either the interface name (in which case the node parameter has
                 to be filled) or the IPIntf object representing the interface
    :return: The segment space of the interface of the node
    """
    if isinstance(intf, str):
        if not isinstance(node, IPNode):
            raise TypeError(
                "Cannot retrieve an IPIntf from name without "
                "passing its node as parameter"
            )
        intf = node.intf(intf)

    return [ip.network for ip in intf.ip6s(exclude_lls=True, exclude_lbs=True)]


class LocalSIDTable:
    """A class representing a LocalSID routing table"""

    def __init__(
        self,
        node: IPNode,
        matching: Iterable[str | IPv6Network | IPNode | IPIntf] = ("::/0",),
    ):
        """
        :param node: The node on which the table is added
        :param matching: The list of destinations
                         whose processing is delegated to the table;
                         destinations can be raw prefixes, interfaces
                         (implying all networks on the interface) or nodes
                         (implying all networks on its loopback interface)
        """
        self.node = node
        self.prefixes = []
        for destination in matching:
            if isinstance(destination, str):
                self.prefixes.append(IPv6Network(destination))
            elif isinstance(destination, IPv6Network):
                self.prefixes.append(destination)
            elif isinstance(destination, IPNode):
                self.prefixes.extend(srv6_segment_space(node=destination))
            elif isinstance(destination, IPIntf):
                self.prefixes.extend(srv6_segment_space(intf=destination))
            else:
                raise TypeError(
                    "The LocalSIDTable cannot be created because "
                    f"the destination {destination} cannot be matched"
                )

        # Find Free table number
        tables = []
        # -color=never: mininet runs commands on a pty, and iproute2 (>= 6.19)
        # colorizes `ip rule list` there, which would corrupt the lookup parse.
        out = self.node.cmd("ip -color=never rule list")
        lines = out.split("\n")
        for line in lines:
            if "lookup " in line:
                with contextlib.suppress(ValueError):
                    tables.append(int(line.split("lookup ")[-1]))
        self.num = 1
        while self.num in tables:
            self.num += 1
        if self.num >= MIN_RESERVED_TABLE:
            raise RuntimeError("Cannot find a free table number on the host")

        # Create the table
        self.create()

    def create(self):
        self.clean()
        for prefix in self.prefixes:
            cmd = f"ip -6 rule add to {prefix} table {self.num}"
            out, err, exitcode = self.node.pexec(shlex.split(cmd))
            if exitcode != 0:
                log.error(
                    "Cannot install rule for new LocalSIDTable:\n"
                    f"{cmd}\nstdout:{out}\nstderr:{err}\n"
                )
        cmd = f"ip -6 route add blackhole default table {self.num}"
        out, err, exitcode = self.node.pexec(cmd)
        if exitcode != 0:
            log.error(
                "Cannot install blackhole rule for new LocalSIDTable:\n"
                f"{cmd}\nstdout:{out}\nstderr:{err}\n"
            )

    def clean(self):
        self.node.cmd(f"ip -6 route flush table {self.num}")
        for prefix in self.prefixes:
            self.node.cmd(shlex.split(f"ip rule del to {prefix} table {self.num}"))


class SRv6Route(metaclass=abc.ABCMeta):
    """The SRv6Route abstract class, which enables to create an SRv6 route"""

    def __init__(
        self,
        net: IPNet,
        node: IPNode | str,
        to: str | IPv6Network | IPNode | IPIntf = "::/0",
        cost=1,
        table: LocalSIDTable | None = None,
    ):
        """
        :param net: The IPNet instance
        :param node: The IPNode object on which the route has to be installed
                     or the name of this node
        :param to: Either directly the prefix, an IPNode, a name of an IPNode
                   or an IPIntf object so that it matches all its addresses.
        :param cost: The cost of using the route: routes with lower cost is
                     preferred if the destination prefix is the same.
        :param table: Install the route into the specified table instead of
                      the main one.
        """
        self.net = net
        self.table = table
        self.destination = to
        self.cost = cost
        self.source = node if not isinstance(node, str) else net[node]
        itfs = realIntfList(self.source)
        if len(itfs) == 0:
            raise ValueError(
                f"Cannot install SRv6Route {self} without"
                f" a real interface on node {self.source.name}\n"
            )
        self.dev = itfs[0].name

        # Check SRv6 capability
        if not self.is_available():
            raise ValueError(
                f"Cannot create {self} because the distribution does not support it"
            )

        # Activate SRv6 on all routers and hosts
        for n in net.routers + net.hosts:
            enable_srv6(n)

        # Add routes
        self.cmds = self.build_commands()
        self.install()

    def is_available(self) -> bool:
        """Check the compatibility with this encapsulation method"""
        return check_srv6_compatibility()

    def dest_prefixes(self) -> list[str]:
        prefixes = []
        try:
            IPv6Network(str(self.destination))
            # This is an IPv6 address
            prefixes.append(str(self.destination))
        except (AddressValueError, NetmaskValueError):
            if isinstance(self.destination, str):
                with contextlib.suppress(KeyError):
                    self.destination = self.net[self.destination]

            if isinstance(self.destination, IPNode):
                prefixes.extend(
                    ip6.network.with_prefixlen
                    for itf in self.destination.intfList()
                    for ip6 in itf.ip6s(exclude_lls=True, exclude_lbs=True)
                )
            elif isinstance(self.destination, IPIntf):
                prefixes.extend(
                    ip6.network.with_prefixlen
                    for ip6 in self.destination.ip6s(exclude_lls=True, exclude_lbs=True)
                )

            if len(prefixes) == 0:
                log.error(
                    "Cannot install SRv6Route",
                    self,
                    "because the destination",
                    self.destination,
                    "does not have a global IPv6 address\n",
                )
        return prefixes

    def nexthops_to_ips(
        self, nexthops: list[str | IPNode | IPIntf | IPv6Address | IPv4Address], v6=True
    ) -> list[str]:
        """
        :param nexthops: Each element of the list can either be an IP or IPv6
                         address, an IPIntf, an IPNode or the name of an IPNode.
                         In the last 3 cases, the default IPv6 address is
                         selected.
        :param v6: Whether we return IPv6 or IPv4 addresses
        :return: a list of addresses
        """
        s = []
        for nh in nexthops:
            try:
                IPv6Address(str(nh)) if v6 else IPv4Address(str(nh))
                # This is an IPv6 or IPv4 address
                s.append(str(nh))
            except (AddressValueError, NetmaskValueError):
                h = nh
                if isinstance(h, str):
                    with contextlib.suppress(KeyError):
                        h = self.net[h]
                ip = None
                if isinstance(h, IPNode):
                    ip = address_pair(h, use_v4=not v6)[1 if v6 else 0]
                elif isinstance(h, IPIntf):
                    ip = h.ip6 if v6 else h.ip
                if ip is None:
                    raise ValueError(
                        f"Cannot find for the nexthop {nh}"
                        f" a global IPv{6 if v6 else 4} address\n"
                    ) from None
                s.append(ip)
        return s

    @abc.abstractmethod
    def build_commands(self) -> list[str]:
        return []

    def install(self):
        self._run_cmds()

    def cleanup(self):
        self._run_cmds(prefix="ip -6 route add ")

    def _run_cmds(self, prefix: str = "ip -6 route add ") -> int:
        for c in self.cmds:
            cmd = prefix + c
            if self.table is not None:
                cmd = cmd + f" table {self.table.num}"
            out, err, code = self.source.pexec(shlex.split(cmd))
            log.debug(f"Installing route on router {self.source.name}: '{cmd}'\n")
            if code:
                log.error(
                    "Cannot install SRv6Route",
                    self,
                    "[rcode:",
                    str(code),
                    "]:\n",
                    cmd,
                    "\nstdout:",
                    str(out),
                    "\nstderr:",
                    str(err),
                )
                return code
        return -1

    def __str__(self):
        return (
            f"SRv6Route<on={self.source.name}, to={self.destination}, cost={self.cost}>"
        )


class SRv6Encap(SRv6Route):
    """The SRv6Encap class, which enables to create an IPv6
    Segment Routing encapsulation in a router.

    The instantiation of these tunnels should happen
    *after* the network has been built and its addresses has been allocated.
    You can leverage the IPTopo.post_build method to do it."""

    ENCAP = "encap"
    INLINE = "inline"

    def __init__(
        self,
        net: IPNet,
        node: IPNode | str,
        to: str | IPv6Network | IPNode | IPIntf = "::/0",
        through: list[str | IPv6Address | IPNode | IPIntf] = (),
        mode=ENCAP,
        cost=1,
    ):
        """
        :param net: The IPNet instance
        :param node: The IPNode object on which the route has to be installed
                     or the name of this node
        :param to: Either directly the prefix, an IPNode, a name of an IPNode
                   or an IPIntf object so that it matches all its addresses.
        :param through: A list of nexthops to set in the IPv6 Segment Routing
                        Header. Each element of the list can either be an
                        IPv6 address, an IPIntf or an IPNode. In both later
                        cases, the default IPv6 address is selected.
        :param mode: Either SRv6Encap.ENCAP or SRv6Encap.INLINE whether
                     the route should encapsulate packets in an outer IPv6
                     packet with the SRH or insert the SRH directly inside
                     the packet.
        :param cost: The cost of using the route: routes with lower cost is
                     preferred if the destination prefix is the same.
        """
        if len(through) == 0:
            raise ValueError(
                "It does not make sense to use Segment Routing without any redirection."
            )
        self.nexthops = list(through)
        self.mode = mode
        super().__init__(net, node, to=to, cost=cost)

    def is_available(self) -> bool:
        """Check the compatibility with this encapsulation method"""
        return (
            super().is_available()
            and subprocess.check_call(shlex.split("ip sr tunsrc set ::")) == 0
        )

    def build_commands(self) -> list[str]:
        cmds = []  # type: List[str]

        # Get destination addresses
        prefixes = self.dest_prefixes()
        if len(prefixes) == 0:
            return cmds

        # Get segments
        nexthops = self.nexthops_to_ips(self.nexthops)
        if len(nexthops) == 0:
            return cmds

        # Build iproute2 commands
        cmds.extend(
            "{} encap seg6 mode {} segs {} metric {} dev {}".format(
                prefix, self.mode, ",".join(nexthops), self.cost, self.dev
            )
            for prefix in prefixes
        )
        return cmds

    def __str__(self):
        return (
            f"SRv6Encap<on={self.source.name}, to={self.destination}, "
            f"through={self.nexthops}, mode={self.mode}, cost={self.cost}>"
        )


class SRv6EndFunction(SRv6Route):
    """This class represents an SRv6 End function"""

    ACTION = "End"

    @property
    def params(self) -> str:
        return ""

    def is_available(self) -> bool:
        """Check the compatibility with this advanced SRv6 routes"""
        cmd = "{seg} encap seg6local action End dev {dev}".format(
            seg="::2/128", dev=self.dev
        )
        src = self.source
        return (
            super().is_available()
            and src.pexec(shlex.split("ip -6 route add " + cmd))[2] == 0
            and src.pexec(shlex.split("ip -6 route del " + cmd))[2] == 0
        )

    def build_commands(self) -> list[str]:
        cmds = []  # type: List[str]

        # Get destination addresses
        prefixes = self.dest_prefixes()
        if len(prefixes) == 0:
            return cmds

        # Build iproute2 commands
        cmds.extend(
            f"{prefix} encap seg6local action {self.ACTION} {self.params}"
            f" metric {self.cost} dev {self.dev}"
            for prefix in prefixes
        )
        return cmds

    def __str__(self):
        return (
            f"SRv6Function<action={self.ACTION}, on={self.source.name}, "
            f"to={self.destination}, cost={self.cost}, params={self.params}>"
        )


class SRv6EndXFunction(SRv6EndFunction):
    """This class represents an SRv6 End.X function"""

    ACTION = "End.X"

    def __init__(self, nexthop: str | IPv6Address | IPIntf | IPNode, *args, **kwargs):
        """
        :param net: The IPNet instance
        :param node: The IPNode object on which the route has to be installed
        :param to: Either directly the prefix, an IPNode or an IPIntf object
                   so that it matches all its addresses.
        :param cost: The cost of using the route: routes with lower cost is
                     preferred if the destination prefix is the same.
        :param table: Install the route into the specified table instead of
                      the main one.
        :param nexthop: The nexthop to consider when forwarding the packet.
                        It can be an IPv6 address, an IPIntf or an IPNode.
                        In both later cases, the default IPv6 address is
                        selected.
        """
        self.nexthop = self.nexthops_to_ips([nexthop])[0]
        super().__init__(*args, **kwargs)

    @property
    def params(self) -> str:
        return "nh6 " + self.nexthop


class SRv6EndTFunction(SRv6EndFunction):
    """This class represents an SRv6 End.T function"""

    ACTION = "End.T"

    def __init__(self, lookup_table: str, *args, **kwargs):
        """
        :param net: The IPNet instance
        :param node: The IPNode object on which the route has to be installed
        :param to: Either directly the prefix, an IPNode or an IPIntf object
                   so that it matches all its addresses.
        :param cost: The cost of using the route: routes with lower cost is
                     preferred if the destination prefix is the same.
        :param table: Install the route into the specified table instead of
                      the main one.
        :param lookup_table: The packet is forwarded to the nexthop looked up
                             in this specified routing table
        """
        self.lookup_table = lookup_table
        super().__init__(*args, **kwargs)

    @property
    def params(self) -> str:
        return f"table {self.lookup_table}"


class SRv6EndDX2Function(SRv6EndFunction):
    """This class represents an SRv6 End.DX2 function"""

    ACTION = "End.DX2"

    def __init__(self, interface: str | IPIntf, *args, **kwargs):
        """
        :param net: The IPNet instance
        :param node: The IPNode object on which the route has to be installed
        :param to: Either directly the prefix, an IPNode or an IPIntf object
                   so that it matches all its addresses.
        :param cost: The cost of using the route: routes with lower cost is
                     preferred if the destination prefix is the same.
        :param table: Install the route into the specified table instead of
                      the main one.
        :param interface: The packet is forwarded to this specific interface
        """
        self.interface = (
            interface.name if isinstance(interface, IPIntf) else str(interface)
        )
        super().__init__(*args, **kwargs)

    @property
    def params(self) -> str:
        return "oif " + self.interface


class SRv6EndDX6Function(SRv6EndXFunction):
    """This class represents an SRv6 End.DX6 function"""

    ACTION = "End.DX6"


class SRv6EndDX4Function(SRv6EndFunction):
    """This class represents an SRv6 End.DX4 function"""

    ACTION = "End.DX4"

    def __init__(self, nexthop: str | IPv4Address | IPIntf | IPNode, *args, **kwargs):
        """
        :param net: The IPNet instance
        :param node: The IPNode object on which the route has to be installed
        :param to: Either directly the prefix, an IPNode or an IPIntf object
                   so that it matches all its addresses.
        :param cost: The cost of using the route: routes with lower cost is
                     preferred if the destination prefix is the same.
        :param table: Install the route into the specified table instead of
                      the main one.
        :param nexthop: The nexthop to consider when forwarding the packet.
                        It can be an IPv4 address, an IPIntf or an IPNode.
                        In both later cases, the default IPv4 address is
                        selected.
        """
        self.nexthop = self.nexthops_to_ips([nexthop], v6=False)[0]
        super().__init__(*args, **kwargs)

    @property
    def params(self) -> str:
        return "nh4 " + self.nexthop


class SRv6EndDT6Function(SRv6EndTFunction):
    """This class represents an SRv6 End.DT6 function"""

    ACTION = "End.DT6"


class SRv6EndB6Function(SRv6EndFunction):
    """This class represents an SRv6 End.B6 function"""

    ACTION = "End.B6"

    def __init__(
        self, segments: list[str | IPv6Address | IPIntf | IPNode], *args, **kwargs
    ):
        """
        :param net: The IPNet instance
        :param node: The IPNode object on which the route has to be installed
        :param to: Either directly the prefix, an IPNode or an IPIntf object
                   so that it matches all its addresses.
        :param cost: The cost of using the route: routes with lower cost is
                     preferred if the destination prefix is the same.
        :param table: Install the route into the specified table instead of
                      the main one.
        :param segments: A list of segments to set in the IPv6 Segment Routing
                         Header. Each element of the list can either be an
                         IPv6 address, an IPIntf or an IPNode. In both later
                         cases, the default IPv6 address is selected.
        """
        if len(segments) == 0:
            raise ValueError(
                "It does not make sense to use Segment Routing without any segment."
            )
        self.segments = self.nexthops_to_ips(segments)
        super().__init__(*args, **kwargs)

    @property
    def params(self) -> str:
        return "srh segs " + ",".join(self.segments)


class SRv6EndB6EncapsFunction(SRv6EndB6Function):
    """This class represents an SRv6 End.B6.Encaps function"""

    ACTION = "End.B6.Encaps"
