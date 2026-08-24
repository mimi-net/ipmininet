"""Base classes to configure a BGP daemon"""
import heapq
import itertools
from abc import ABC
from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import TYPE_CHECKING, Optional

from ipmininet.overlay import Overlay
from ipmininet.utils import realIntfList

from .base import RouterDaemon
from .zebra import (
    DENY,
    PERMIT,
    AccessList,
    CommunityList,
    PrefixList,
    PrefixListEntry,
    QuaggaDaemon,
    RouteMap,
    RouteMapEntry,
    RouteMapMatchCond,
    RouteMapSetAction,
    Zebra,
)

if TYPE_CHECKING:
    from ipmininet.iptopo import IPTopo
    from ipmininet.node_description import RouterDescription
    from ipmininet.router import Router

BGP_DEFAULT_PORT = 179
SHARE = "Share"
CLIENT_PROVIDER = "Client-Provider"


class AS(Overlay):
    """An overlay class that groups routers by AS number"""

    def __init__(self, asn: int, routers=(), **props):
        """:param asn: The number for this AS
        :param routers: an initial set of routers to add to this AS
        :param props: key-values to set on all routers of this AS"""
        super().__init__(nodes=routers, nprops=props)
        self.asn = asn

    @property
    def asn(self) -> int:
        return self.nodes_properties["asn"]

    @asn.setter
    def asn(self, x: int):
        x = int(x)
        self.nodes_properties["asn"] = x

    def __str__(self):
        return f"<AS {self.asn}>"


class iBGPFullMesh(AS):
    """An overlay class to establish iBGP sessions in full mesh between BGP
    routers."""

    def apply(self, topo):
        # Quagga auto-detect whether to use iBGP or eBGP depending on ASN
        # So we simply make a full mesh with everyone
        bgp_fullmesh(topo, self.nodes)
        super().apply(topo)

    def __str__(self):
        return f"<iBGPMesh {self.asn}>"


def bgp_fullmesh(topo, routers: Sequence[str]):
    """Establish a full-mesh set of BGP peerings between routers

    :param topo: The current topology
    :param routers: The set of routers peering within each other"""

    def _set_peering(x):
        bgp_peering(topo, x[0], x[1])

    for peering in itertools.combinations(routers, 2):
        _set_peering(peering)


def bgp_peering(topo: "IPTopo", a: "RouterDescription", b: "RouterDescription"):
    """Register a BGP peering between two nodes"""
    topo.getNodeInfo(a, "bgp_peers", list).append(b)
    topo.getNodeInfo(b, "bgp_peers", list).append(a)

    # recent versions of BGP must define import/export filters for eBGP sessions (RFC 8212).
    # This function allows all the routes to be accepted. As depicted, the user can still
    # change the behavior of importation and exportation filters by matching prefixes
    # in the smaller orders of the RM
    filter_allows_all_routes(a, b)


def filter_allows_all_routes(a: "RouterDescription", b: "RouterDescription"):
    ip4_pfxl = PrefixList(name="hello-world-v4", family="ipv4", entries=(PrefixListEntry("0.0.0.0/0", le=32),))
    ip6_pfxl = PrefixList(name="hello-world-v6", family="ipv6", entries=(PrefixListEntry("::/0", le=128),))

    # since only one route-map can be used for importation/exportation filter,
    # this RM allows any routes as ultimate resort. The user needs to
    # explicitly deny in the smaller orders
    a.get_config(BGP) \
        .filter(policy=PERMIT, from_peer=b, matching=(ip4_pfxl, ip6_pfxl), order=RouteMap.DEFAULT_POLICY) \
        .filter(policy=PERMIT, to_peer=b, matching=(ip4_pfxl, ip6_pfxl), order=RouteMap.DEFAULT_POLICY)
    b.get_config(BGP) \
        .filter(policy=PERMIT, from_peer=a, matching=(ip4_pfxl, ip6_pfxl), order=RouteMap.DEFAULT_POLICY) \
        .filter(policy=PERMIT, to_peer=a, matching=(ip4_pfxl, ip6_pfxl), order=RouteMap.DEFAULT_POLICY)


def ebgp_session(topo: "IPTopo", a: "RouterDescription", b: "RouterDescription",
                 link_type: str | None = None):
    """Register an eBGP peering between two nodes, and disable IGP adjacencies
    between them.

    :param topo: The current topology
    :param a: Local router
    :param b: Peer router
    :param link_type: Can be set to SHARE or CLIENT_PROVIDER. In this case
                      ebgp_session will create import and export
                      filter and set local pref based on the link type
    """
    if link_type:
        all_al_v4 = AccessList("ipv4", name="Allv4", entries=("any",))
        all_al_v6 = AccessList("ipv6", name="Allv6", entries=("any",))
        # Create the community filter for the export policy
        peers_link = CommunityList(name="from-peers", community=1,
                                   action=PERMIT)
        up_link = CommunityList(name="from-up", community=3, action=PERMIT)

        if link_type == SHARE:
            # Set the community and local pref for the import policy
            a.get_config(BGP) \
                .set_community(1, from_peer=b, matching=(all_al_v4, all_al_v6)) \
                .set_local_pref(150, from_peer=b, matching=(all_al_v4, all_al_v6))
            b.get_config(BGP) \
                .set_community(1, from_peer=a, matching=(all_al_v4, all_al_v6)) \
                .set_local_pref(150, from_peer=a, matching=(all_al_v4, all_al_v6))

            # Create route maps to filter exported route
            a.get_config(BGP) \
                .deny(to_peer=b, matching=(up_link,),
                      order=10) \
                .deny(to_peer=b, matching=(peers_link,),
                      order=15) \
                .permit(to_peer=b, order=20)

            b.get_config(BGP) \
                .deny(to_peer=a, matching=(up_link,),
                      order=10) \
                .deny(to_peer=a, matching=(peers_link,),
                      order=15) \
                .permit(to_peer=a, order=20)

        elif link_type == CLIENT_PROVIDER:
            # Set the community and local pref for the import policy
            a.get_config(BGP) \
                .set_community(3, from_peer=b, matching=(all_al_v4, all_al_v6)) \
                .set_local_pref(100, from_peer=b, matching=(all_al_v4, all_al_v6))
            b.get_config(BGP) \
                .set_community(2, from_peer=a, matching=(all_al_v4, all_al_v6)) \
                .set_local_pref(200, from_peer=a, matching=(all_al_v4, all_al_v6))

            # Create route maps to filter exported route
            a.get_config(BGP) \
                .deny(to_peer=b, matching=(up_link,),
                      order=10) \
                .deny(to_peer=b, matching=(peers_link,),
                      order=15) \
                .permit(to_peer=b, order=20)

    bgp_peering(topo, a, b)
    topo.linkInfo(a, b)["igp_passive"] = True


class BGPConfig:

    def __init__(self, topo: "IPTopo", router: "RouterDescription"):
        self.topo = topo
        self.router = router

    @staticmethod
    def rm_name(peer: str, family: str, direction: str):
        return f"{peer}-{family}-{direction}".format(peer=peer, family=family, direction=direction)

    def set_local_pref(self, local_pref: int, from_peer: str,
                       matching: Sequence[AccessList | CommunityList] =
                       (), name: str | None = None) -> "BGPConfig":
        """Set local pref on a peering with 'from_peer' on routes
         matching all of the access and community lists in 'matching'

        :param name:
        :param local_pref: The local pref value to set
        :param from_peer: The peer on which the local pref is applied
        :param matching: A list of AccessList and/or CommunityList
        :return: self
        """
        self.add_set_action(peer=from_peer,
                            set_action=RouteMapSetAction("local-preference",
                                                         local_pref),
                            matching=matching, direction="in", name=name)
        return self

    def set_med(self, med: int, to_peer: str,
                matching: Sequence[AccessList | CommunityList] = (),
                name: str | None = None) \
            -> "BGPConfig":
        """Set MED on a peering with 'to_peer' on routes
         matching all of the access and community lists in 'matching'

        :param name:
        :param med: The local pref value to set
        :param to_peer: The peer to which the med is applied
        :param matching: A list of AccessList and/or CommunityList
        :return: self
        """
        self.add_set_action(peer=to_peer,
                            set_action=RouteMapSetAction("metric", med),
                            matching=matching, direction="out", name=name)
        return self

    def set_community(self, community: str | int,
                      from_peer: str | None = None,
                      to_peer: str | None = None,
                      matching: Sequence[AccessList | CommunityList] =
                      (), name: str | None = None) -> "BGPConfig":
        """Set community on a routes received from 'from_peer'
         and routes sent to 'to_peer' on routes matching
         all of the access and community lists in 'matching'

        :param name:
        :param community: The community value to set
        :param from_peer: The peer on which received routes have to have
                          the community
        :param to_peer: The peer on which sent routes have to have the community
        :param matching: A list of AccessList and/or CommunityList
        :return: self
        """
        if to_peer is not None:
            self.add_set_action(peer=to_peer,
                                set_action=RouteMapSetAction("community",
                                                             community),
                                matching=matching, direction="out", name=name)
        if from_peer is not None:
            self.add_set_action(peer=from_peer,
                                set_action=RouteMapSetAction("community",
                                                             community),
                                matching=matching, direction="in", name=name)
        return self

    def filter(self, name: str | None = None, policy=DENY,
               from_peer: str | None = None, to_peer: str | None = None,
               matching: Sequence[AccessList | CommunityList | PrefixList] = (),
               order=10) -> "BGPConfig":
        """Either accept or deny all routes received from 'from_peer'
         and routes sent to 'to_peer' matching
         any access/prefix lists or community lists in 'matching'

        :param name: The name of the route-map. If no name is given, the
                     filter will be appended to the main route map responsible
                     for the importation (resp. exportation) of routes received
                     (resp. sent) from "from_peer" (resp. "to_peer"). If the name
                     is set, the freshly created route-map will be created but not
                     used unless explicitly called with the route-map "call"
                     command from the main importation/exportation RM.
        :param policy: Either 'deny' or 'permit'
        :param from_peer: Is set, the filter will be applied on the routes received
                          from "from_peer".
        :param to_peer: Is set, the filter will be applied on the routes sent
                        to "to_peer".
        :param matching: A list of AccessList and/or CommunityList and/or PrefixList
        :param order: The order in which route-maps are applied,
         i.e., lower order means applied before
        :return: self
        """
        route_maps = self.topo.getNodeInfo(self.router, "bgp_route_maps", list)
        for peer, direction in ((from_peer, "in"), (to_peer, "out")):
            if peer is None:
                continue
            for family in ["ipv4", "ipv6"]:
                match_cond = self.filters_to_match_cond(matching, family)

                rm = RouteMap(family=family,
                              name=name if name is not None
                                        else self.rm_name(peer, family, direction),
                              proto={"bgp"},
                              neighbor=peer,
                              direction=direction)

                rm.entry(RouteMapEntry(family=family,
                                       match_policy=policy,
                                       match_cond=match_cond if match_cond and len(match_cond) > 0 else ()),
                         order)

                try:
                    idx = route_maps.index(rm)
                    existing_rm = route_maps.pop(idx)
                    rm.update(existing_rm)
                except ValueError:
                    pass

                route_maps.append(rm)

        return self

    def deny(self, name: str | None = None, from_peer: str | None = None,
             to_peer: str | None = None,
             matching: Sequence[AccessList | CommunityList] = (),
             order=10) -> "BGPConfig":
        """Deny all routes received from 'from_peer'
         and routes sent to 'to_peer' matching
         all of the access and community lists in 'matching'

        :param name: The name of the route-map
        :param from_peer: The peer on which received routes have to have
                          the community
        :param to_peer: The peer on which sent routes have to have the community
        :param matching: A list of AccessList and/or CommunityList
        :param order: The order in which route-maps are applied,
         i.e., lower order means applied before
        :return: self
        """
        return self.filter(name, policy=DENY, from_peer=from_peer,
                           to_peer=to_peer, matching=matching, order=order)

    def permit(self, name: str | None = None,
               from_peer: str | None = None, to_peer: str | None = None,
               matching: Sequence[AccessList | CommunityList] = (),
               order=10) -> "BGPConfig":
        """Accept all routes received from 'from_peer'
         and routes sent to 'to_peer' matching
         all of the access and community lists in 'matching'

        :param name: The name of the route-map
        :param from_peer: The peer on which received routes have to have
                          the community
        :param to_peer: The peer on which sent routes have to have the community
        :param matching: A list of AccessList and/or CommunityList
        :param order: The order in which route-maps are applied,
         i.e., lower order means applied before
        :return: self
        """
        return self.filter(name, policy=PERMIT, from_peer=from_peer,
                           to_peer=to_peer, matching=matching, order=order)

    def filters_to_match_cond(self,
                              filter_list: Sequence[AccessList | CommunityList | PrefixList],
                              family: str):
        match_cond = []
        assert family in {"ipv4", "ipv6"}, f"Bad family {family}"
        access_lists = self.topo.getNodeInfo(self.router, "bgp_access_lists",
                                             list)
        community_list = self.topo.getNodeInfo(self.router,
                                               "bgp_community_lists", list)

        prefix_list = self.topo.getNodeInfo(self.router, "bgp_prefix_lists", list)

        # Create match_conditions based on the provided filters
        for f in filter_list:
            if isinstance(f, CommunityList):
                match_cond.append(RouteMapMatchCond("community", f.name, f.family))
                if f not in community_list:
                    community_list.append(f)
            elif isinstance(f, AccessList):
                if f.family == family:
                    match_cond.append(RouteMapMatchCond("access-list", f.name, f.family))
                    if f not in access_lists:
                        access_lists.append(f)
            elif isinstance(f, PrefixList):
                if f.family == family:
                    match_cond.append(RouteMapMatchCond("prefix-list", f.name, f.family))
                    if f not in prefix_list:
                        prefix_list.append(f)
            else:
                msg = "Filter not yet implemented"
                raise Exception(msg)
        return match_cond

    def add_set_action(self, peer: str, set_action: RouteMapSetAction, name: str | None,
                       matching: Sequence[AccessList | CommunityList],
                       direction: str) -> "BGPConfig":
        """Add a 'RouteMapSetAction' to a BGP peering between two nodes

        :param name: if set, define the name of the route map, the action
        :param peer: The peer to which the route map is applied
        :param set_action: The RouteMapSetAction to set
        :param matching: A list of filter, can be empty
        :param direction: direction of the route map: 'in', 'out' or 'both'
        :return: self
        """
        route_maps = self.topo.getNodeInfo(self.router, "bgp_route_maps", list)

        for family in ("ipv4", "ipv6"):
            match_cond = self.filters_to_match_cond(matching, family)

            rm = RouteMap(family=family, name=name if name is not None else self.rm_name(peer, family, direction),
                          proto={"bgp"}, neighbor=peer, direction=direction)

            rm_entry = RouteMapEntry(family=family, match_cond=match_cond,
                                     set_actions=[set_action])

            try:
                idx = route_maps.index(rm)
                entry = route_maps[idx].find_entry_by_match_condition(match_cond)
                if entry:
                    entry.append_set_action([set_action])
                else:
                    entry.entry(rm_entry)

            except ValueError:
                rm.entry(rm_entry)
                route_maps.append(rm)
        return self


def set_rr(topo: "IPTopo", rr: str, peers: Sequence[str] = ()):
    """
    Set rr as route reflector for all router r

    :param topo: The current topology
    :param rr: The route reflector
    :param peers: Clients of the route reflector
    """
    for r in peers:
        bgp_peering(topo, rr, r)
    router_is_rr = topo.getNodeInfo(rr, "bgp_rr_info", list)
    router_is_rr.append(True)


class AbstractBGP(ABC, RouterDaemon):

    @property
    def afi(self):
        return [AF_INET(), AF_INET6()]

    def _build_afi(self, af: list["AddressFamily"] | None):
        afis = self.afi
        if af:
            for address_family in af:
                for default_afi in afis:
                    if address_family.family == default_afi.family:
                        default_afi.extend(address_family)

        return afis

    @staticmethod
    def _address_families(af: list["AddressFamily"], nei: list["Peer"]) \
            -> list["AddressFamily"]:
        """Complete the address families: add extra networks, or activate
        neighbors. The default is to activate all given neighbors"""
        for a in af:
            a.neighbors.extend(nei)
        return af

    def _build_neighbors(self) -> list["Peer"]:
        """Compute the set of BGP peers for this BGP router
        :return: set of neighbors"""
        neighbors = []
        for x in self._node.get("bgp_peers", []):
            for v6 in [True, False]:
                peer = Peer(self._node, x, v6=v6)
                if peer.peer:
                    neighbors.append(peer)
        return neighbors


class BGP(QuaggaDaemon, AbstractBGP):
    """This class provides the configuration skeletons for BGP routers."""
    NAME = "bgpd"
    DEPENDS = (Zebra,)
    KILL_PATTERNS = (NAME,)

    @property
    def STARTUP_LINE_EXTRA(self):
        """We add the port to the standard startup line"""
        return f"-p {self.port}"

    def __init__(self, node, port=BGP_DEFAULT_PORT,
                 *args, **kwargs):
        super().__init__(node=node, *args, **kwargs)
        self.port = port

    def build(self):
        cfg = super().build()
        cfg.asn = self._node.asn
        cfg.neighbors = self._build_neighbors()
        cfg.address_families = self._address_families(
            self._build_afi(self.options.address_families), cfg.neighbors)

        cfg.access_lists = self.build_access_list()
        cfg.community_lists = self.build_community_list()
        cfg.prefix_lists = self.build_prefix_list()
        cfg.route_maps = self.build_route_map(cfg.neighbors)
        cfg.rr = self._node.get("bgp_rr_info")

        return cfg

    def build_community_list(self) -> list[CommunityList]:
        """
        Build and return a list of community_filter
        """
        node_community_lists = self._node.get("bgp_community_lists")
        community_lists = []
        if node_community_lists:
            for node_cl in node_community_lists:
                # If community is an int change it to the right format
                # asn:community by adding node asn
                cl = CommunityList(name=node_cl.name,
                                   community=node_cl.community,
                                   action=node_cl.action)
                community_lists.append(cl)
                if isinstance(node_cl.community, int):
                    cl.community = "%s:%d" % (self._node.asn, node_cl.community)
        return community_lists

    def build_access_list(self) -> list[AccessList]:
        """
        Build and return a list of access_filter
        :return:
        """
        return self._node.get("bgp_access_lists", val=[])

    def build_prefix_list(self):
        return self._node.get("bgp_prefix_lists", val=[])

    def build_route_map(self, neighbors: Sequence["Peer"]) -> list[RouteMap]:
        """
        Build and return a list of route map for the current node
        """
        def find_neighbor(route_map: "RouteMap"):
            """
            Find the Peer object associated to the neighbor on which
            the route map will be applied
            """
            assert route_map.neighbor is not None, "BGP Neighbor route maps must have one neighbor!"

            for n in neighbors:
                if n.node == route_map.neighbor and n.family == route_map.family:
                    return n
            return None

        final_rms = []

        rms = self._node.get("bgp_route_maps", val=[])  # type: List['RouteMap']

        for rm in rms:
            neigh = find_neighbor(rm)
            rm.neighbor = neigh

            if len(rm) > 1 and rm.default_policy_set():
                rm.remove_default_policy()

            if neigh is not None:
                final_rms.append(rm)

        return final_rms

    def set_defaults(self, defaults):
        """:param debug: the set of debug events that should be logged
        :param address_families: The set of AddressFamily to use"""
        super().set_defaults(defaults)

    @classmethod
    def get_config(cls, topo: "IPTopo", node: "RouterDescription", **kwargs):
        return BGPConfig(topo=topo, router=node)


class AddressFamily:
    """An address family that is exchanged through BGP"""

    def __init__(self, af_name: str, redistribute: Sequence[str] = (),
                 networks: Sequence[str | IPv4Network | IPv6Network] = (),
                 routes=()):
        self.name = af_name
        self.networks = [ip_network(str(n)) for n in networks]
        self.redistribute = set(redistribute)  # type: Set[str]
        self.neighbors = []  # type: List[Peer]
        self.routes = routes

    def __str__(self):
        return repr(self)

    def __repr__(self) -> str:
        return f"AddressFamily({self.name}, networks: {self.networks}, redistribute: {self.redistribute}, {self.neighbors}, routes: {self.routes})"

    def extend(self, af: "AddressFamily"):
        self.name = af.name
        self.redistribute.update(af.redistribute)
        self.neighbors.extend(af.neighbors)
        self.networks.extend(af.networks)
        self.routes += af.routes

    @property
    def family(self):
        """
        :return: the AddressFamily to be used in FRRouting configuration
        """
        if self.name == "ipv4":
            return "ip"
        if self.name == "ipv6":
            return "ip6"
        msg = f"Unsupported AddressFamily {self.name}"
        raise ValueError(msg)


def AF_INET(*args, **kwargs):
    """The ipv4 (unicast) address family"""
    return AddressFamily("ipv4", *args, **kwargs)


def AF_INET6(*args, **kwargs):
    """The ipv6 (unicast) address family"""
    return AddressFamily("ipv6", *args, **kwargs)


class Peer:
    """A BGP peer"""

    class PQNode:
        """Class representing an element of the priority queue used in _find_peer_address"""

        def __init__(self, key, extra_val):
            self.key = key
            self.value = extra_val

        def __lt__(self, other):
            return self.key < other.key

        def __str__(self):
            return str(f"{self.key} : {self.value}")

        def __repr__(self):
            return str(self)

    def __init__(self, base: "Router", node: str, v6=False):
        """:param base: The base router that has this peer
        :param node: The actual peer"""
        _peer, other, _local_addr = self._find_peer_address(base, node, v6=v6)
        self.peer = _peer
        self.local_addr = _local_addr
        if not _peer or not other:
            return
        self.node = node
        self.asn = other.asn
        self.family = "ipv4" if not v6 else "ipv6"
        try:
            self.port = other.nconfig.daemon(BGP).port
        except KeyError:  # No configured daemon - yet - use default
            self.port = BGP_DEFAULT_PORT
        # We default to nexthop self for eBGP routes only
        self.nh_self = "next-hop-self"
        # We enable eBGP multihop if eBGP is in use
        ebgp = self.asn != base.asn
        self.ebgp_multihop = ebgp
        self.description = "{} ({}BGP)".format(node, "e" if ebgp else "i")

    @staticmethod
    def _find_peer_address(base: "Router", peer: str, v6=False) \
            -> tuple[str | None, Optional["Router"], str | None]:
        """
        Finds the IP address of the peer from the base router to
        typically configure the BGP session between the two routers.

        :param base: The router from which the peer's address must be found
        :param peer: the name of the node for which we are looking for the IP address
        :param v6: if set to True, the function seeks the IPv6 address.
                   Otherwise, if set to False, it looks for the IPv4 address
        :return: a 3-Tuple <peer IP, peer Router object, local base IP>
                 peer IP: the IP address set on the peer interface
                 peer Router object: the node object related to the peer
                 local base IP: the local IP address used on base router
                                to establish the connection with the peer
        """
        visited = set()  # type: Set[str]
        to_visit = {i.name: i for i in realIntfList(base)}
        prio_queue: list[Peer.PQNode] = [Peer.PQNode((0, i), to_visit[i]) for i in to_visit]
        heapq.heapify(prio_queue)
        # Explore all interfaces in base ASN recursively, until we find one
        # connected to the peer
        while to_visit:
            node = heapq.heappop(prio_queue)
            path_cost = node.key[0]
            i = node.key[1]
            my_interface = node.value
            if i in visited:
                continue
            visited.add(i)  # putting the string representation of the interface
            i = to_visit.pop(i)
            for n in i.broadcast_domain.routers:
                if n.node.name == peer:
                    if not v6:
                        return n.ip, n.node, my_interface.ip
                    if n.ip6 and not ip_address(n.ip6).is_link_local:
                        return n.ip6, n.node, my_interface.ip6
                    return None, None, None
                if n.node.asn == base.asn or not n.node.asn:
                    for i in realIntfList(n.node):
                        to_visit[i.name] = i
                        heapq.heappush(prio_queue, Peer.PQNode((path_cost + i.igp_metric, i.name), my_interface))
        return None, None, None
