"""This module holds the configuration generators for daemons
that can be used in a router."""

from .base import (
    BasicRouterConfig,
    BorderRouterConfig,
    NodeConfig,
    RouterConfig,
)
from .bgp import (
    AF_INET,
    AF_INET6,
    AS,
    BGP,
    CLIENT_PROVIDER,
    SHARE,
    AccessList,
    CommunityList,
    bgp_fullmesh,
    bgp_peering,
    ebgp_session,
    iBGPFullMesh,
    set_rr,
)
from .exabgp import (
    BGPAttribute,
    BGPAttributeFlags,
    BGPRoute,
    ExaBGPDaemon,
    ExaList,
    HexRepresentable,
    Representable,
)
from .iptables import (
    NOT,
    AddressClause,
    Allow,
    Chain,
    ChainRule,
    Deny,
    Filter,
    InputFilter,
    InterfaceClause,
    IP6Tables,
    IPTables,
    OutputFilter,
    PortClause,
    Rule,
    TransitFilter,
)
from .ospf import OSPF, OSPFArea
from .ospf6 import OSPF6
from .pimd import PIMD
from .radvd import RADVD, AdvConnectedPrefix, AdvPrefix, AdvRDNSS
from .ripng import RIPng
from .sshd import SSHd
from .staticd import STATIC, StaticRoute
from .zebra import Mgmtd, Zebra

__all__ = [
    "AF_INET",
    "AF_INET6",
    "AS",
    "BGP",
    "CLIENT_PROVIDER",
    "NOT",
    "OSPF",
    "OSPF6",
    "PIMD",
    "RADVD",
    "SHARE",
    "STATIC",
    "AccessList",
    "AddressClause",
    "AdvConnectedPrefix",
    "AdvPrefix",
    "AdvRDNSS",
    "Allow",
    "BGPAttribute",
    "BGPAttributeFlags",
    "BGPRoute",
    "BasicRouterConfig",
    "BorderRouterConfig",
    "Chain",
    "ChainRule",
    "CommunityList",
    "Deny",
    "ExaBGPDaemon",
    "ExaList",
    "Filter",
    "HexRepresentable",
    "IP6Tables",
    "IPTables",
    "InputFilter",
    "InterfaceClause",
    "Mgmtd",
    "NodeConfig",
    "OSPFArea",
    "OutputFilter",
    "PortClause",
    "RIPng",
    "Representable",
    "RouterConfig",
    "Rule",
    "SSHd",
    "StaticRoute",
    "TransitFilter",
    "Zebra",
    "bgp_fullmesh",
    "bgp_peering",
    "ebgp_session",
    "iBGPFullMesh",
    "set_rr",
]
