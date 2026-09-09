"""Rootless unit tests for the BGPConfig route-map builder.

These drive BGPConfig on an in-memory stand-in for the topology object, so
they exercise the route-map data model without starting a network.
"""

from ipmininet.router.config import AccessList
from ipmininet.router.config.bgp import BGPConfig

# Number of set actions merged into a single route-map entry when the match
# conditions are identical.
_MERGED_ACTION_COUNT = 2
# Explicit route-map order used to place a community set action.
_CUSTOM_ORDER = 15


class _NodeInfoTopo:
    """In-memory stand-in for IPTopo node attribute storage."""

    def __init__(self):
        self._attrs = {}

    def getNodeInfo(self, node, attr, default=None):
        key = (node, attr)
        if key not in self._attrs:
            self._attrs[key] = default() if callable(default) else default
        return self._attrs[key]


def _new_cfg():
    topo = _NodeInfoTopo()
    return BGPConfig(topo, "r1"), topo


def _acl(name):
    return AccessList("ipv4", name=name, entries=("any",))


def _ipv4_route_map(topo):
    route_maps = topo.getNodeInfo("r1", "bgp_route_maps", list)
    return next(rm for rm in route_maps if rm.family == "ipv4")


def test_set_action_distinct_match_conditions_do_not_crash():
    cfg, topo = _new_cfg()
    cfg.set_local_pref(150, from_peer="r2", matching=(_acl("a"),))
    cfg.set_local_pref(450, from_peer="r2", matching=(_acl("b"),))
    entries = _ipv4_route_map(topo).entries
    assert sorted(entries) == [10, 20]


def test_set_action_same_match_conditions_merge():
    cfg, topo = _new_cfg()
    acl = _acl("a")
    cfg.set_local_pref(150, from_peer="r2", matching=(acl,))
    cfg.set_local_pref(450, from_peer="r2", matching=(acl,))
    entries = _ipv4_route_map(topo).entries
    assert sorted(entries) == [10]
    assert len(next(iter(entries.values())).set_actions) == _MERGED_ACTION_COUNT


def test_set_action_explicit_orders():
    cfg, topo = _new_cfg()
    cfg.set_local_pref(150, from_peer="r2", matching=(_acl("a"),), order=20)
    cfg.set_local_pref(450, from_peer="r2", matching=(_acl("b"),), order=10)
    entries = _ipv4_route_map(topo).entries
    assert sorted(entries) == [10, 20]
    assert all(len(entry.set_actions) == 1 for entry in entries.values())


def test_set_community_forwards_order():
    cfg, topo = _new_cfg()
    cfg.set_community(3, from_peer="r2", order=_CUSTOM_ORDER)
    assert _CUSTOM_ORDER in _ipv4_route_map(topo).entries
