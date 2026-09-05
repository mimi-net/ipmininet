"""Scenarios building routing policy and config objects.

These tests exercise the zebra configuration domain-specific language the way
a real topology would compose it (access-lists, prefix-lists, route-maps and
their merge/update lifecycle) plus a few configuration edge cases. They never
require root privileges and never start a network.
"""

from ipaddress import ip_network
from typing import cast
from unittest.mock import Mock

import pytest

from ipmininet.router import IPNode
from ipmininet.router.config.base import NodeConfig
from ipmininet.router.config.utils import ConfigDict
from ipmininet.router.config.zebra import (
    AccessList,
    AccessListEntry,
    CommunityList,
    PrefixList,
    PrefixListEntry,
    RouteMap,
    RouteMapEntry,
    RouteMapMatchCond,
    RouteMapSetAction,
)
from ipmininet.utils import require_cmd

_V4_MAX_PREFIX = 32
_V6_MAX_PREFIX = 128
_V4_LE_BOUND = 24
_V4_GE_BOUND = 16
_TWO = 2
_THREE = 3


def _v4_acl_entry(prefix: str) -> AccessListEntry:
    return AccessListEntry(prefix, family="ipv4")


def test_access_list_entries_with_family():
    v4 = _v4_acl_entry("10.0.0.0/8")
    assert v4.prefix == ip_network("10.0.0.0/8")
    assert v4.family == "ipv4"
    assert v4.action == "permit"
    assert v4.zebra_family == "ip"

    v6 = AccessListEntry("2001:db8::/32", family="ipv6")
    assert v6.family == "ipv6"
    assert v6.zebra_family == "ipv6"

    with pytest.raises(AssertionError):
        AccessListEntry("10.0.0.0/8", family="ipv6")


def test_access_list_auto_name_and_family():
    acl = AccessList("ipv4", entries=("any",))
    assert acl.name.startswith("acl")
    assert acl.entries[0].family == "ipv4"
    assert acl.zebra_family == ""

    acl6 = AccessList("ipv6", entries=("any",))
    assert acl6.name.startswith("acl")
    assert acl6.entries[0].family == "ipv6"
    assert acl6.zebra_family == "ipv6 "


def test_prefix_list_any_entry():
    pl4 = PrefixList("ipv4", entries=("any",))
    entry4 = pl4.entries[0]
    assert entry4.prefix == ip_network("0.0.0.0/0")
    assert entry4.le == _V4_MAX_PREFIX
    assert not hasattr(entry4, "ge")

    pl6 = PrefixList("ipv6", entries=("any",))
    entry6 = pl6.entries[0]
    assert entry6.prefix == ip_network("::/0")
    assert entry6.le == _V6_MAX_PREFIX


def test_prefix_list_le_ge_bounds():
    entry = PrefixListEntry("10.0.0.0/8", le=_V4_LE_BOUND)
    assert entry.le == _V4_LE_BOUND
    assert entry.ge is None

    entry = PrefixListEntry("10.0.0.0/8", ge=_V4_GE_BOUND)
    assert entry.ge == _V4_GE_BOUND
    assert entry.le is None

    entry = PrefixListEntry("10.0.0.0/8", le=_V4_LE_BOUND, ge=_V4_GE_BOUND)
    assert entry.le == _V4_LE_BOUND
    assert entry.ge == _V4_GE_BOUND

    with pytest.raises(AssertionError):
        PrefixListEntry("10.0.0.0/8", le=_V4_GE_BOUND, ge=_V4_LE_BOUND)
    with pytest.raises(AssertionError):
        PrefixListEntry("10.0.0.0/8", le=_V4_MAX_PREFIX + 1)


def test_prefix_list_auto_name():
    pl = PrefixList("ipv4")
    assert pl.name.startswith("pfxl")


def test_prefix_list_entry_types():
    prefix_list = PrefixList(
        "ipv4",
        entries=[
            ip_network("192.168.0.0/16"),
            "172.16.0.0/12",
            PrefixListEntry("10.0.0.0/8", family="ipv4"),
        ],
    )
    assert len(prefix_list.entries) == _THREE

    with pytest.raises(ValueError):
        PrefixList("ipv4", entries=("10.0.0.0/8", 3))


def test_route_map_entry_from_tuples():
    entry = RouteMapEntry(
        "ipv4",
        match_cond=[
            ("acl", "my_acl"),
            RouteMapMatchCond(cond_type="prefix-list", condition="pfx"),
        ],
        set_actions=[
            ("localpref", 120),
            RouteMapSetAction(action_type="community", value="65000:1"),
        ],
    )
    assert len(entry.match_cond) == _TWO
    assert all(isinstance(c, RouteMapMatchCond) for c in entry.match_cond)
    assert len(entry.set_actions) == _TWO
    assert all(isinstance(a, RouteMapSetAction) for a in entry.set_actions)

    entry.append_match_cond([RouteMapMatchCond("acl", "extra")])
    assert len(entry.match_cond) == _THREE
    entry.append_match_cond([RouteMapMatchCond("acl", "extra")])
    assert len(entry.match_cond) == _THREE

    entry.append_set_action([RouteMapSetAction("community", "65000:2")])
    assert len(entry.set_actions) == _THREE
    entry.append_set_action([RouteMapSetAction("community", "65000:2")])
    assert len(entry.set_actions) == _THREE


def test_route_map_entry_merge():
    base = RouteMapEntry("ipv4")
    base.append_set_action([RouteMapSetAction("localpref", 200)])
    other = RouteMapEntry("ipv4")
    other.append_match_cond([RouteMapMatchCond("acl", "extra")])
    base.update(other)
    assert len(base.match_cond) == 1
    assert len(base.set_actions) == 1

    incompatible = RouteMapEntry("ipv6")
    with pytest.raises(ValueError):
        base.update(incompatible)


def test_route_map_management():
    route_map = RouteMap("ipv4")
    assert route_map.name.startswith("rm")
    assert route_map.describe == "route-map"

    first = RouteMapEntry("ipv4")
    denied = RouteMapEntry("ipv4", match_policy="deny")
    route_map.entry(first)
    route_map.entry(denied, order=5)
    assert len(route_map) == _TWO

    route_map.remove_entry(5)
    assert len(route_map) == 1
    route_map.remove_entry(5)
    assert len(route_map) == 1

    route_map.remove_default_policy()

    with pytest.raises(ValueError):
        route_map.update(RouteMap("ipv4"))


def test_route_map_default_policy():
    route_map = RouteMap("ipv6")
    assert route_map.default_policy_set() is False
    route_map.entry(RouteMapEntry("ipv6"), order=RouteMap.DEFAULT_POLICY)
    assert route_map.default_policy_set() is True
    route_map.remove_default_policy()
    assert route_map.default_policy_set() is True
    assert RouteMap.DEFAULT_POLICY not in route_map.entries


def test_route_map_find_entry():
    condition = RouteMapMatchCond("acl", "found")
    matching = RouteMapEntry("ipv4", match_cond=[condition])
    route_map = RouteMap("ipv4")
    route_map.entry(matching)
    route_map.entry(RouteMapEntry("ipv4"))

    assert route_map.find_entry_by_match_condition([condition]) is matching
    assert (
        route_map.find_entry_by_match_condition([RouteMapMatchCond("acl", "missing")])
        is None
    )


def test_route_map_match_condition_families():
    community = RouteMapMatchCond("community", "65000:1", family="community")
    assert community.zebra_family == "community"

    v6 = RouteMapMatchCond("prefix-list", "pfx", family="ipv6")
    assert v6.zebra_family == "ipv6"
    assert v6 == RouteMapMatchCond("prefix-list", "pfx", family="ipv6")

    unfamilied = RouteMapMatchCond("acl", "some-acl")
    with pytest.raises(ValueError):
        _ = unfamilied.zebra_family


def test_community_list_auto_name():
    community = CommunityList(community=1)
    assert community.name.startswith("cml")
    assert community.family == "community"
    assert community.action == "permit"


def test_config_dict_usage():
    cfg = ConfigDict()
    cfg.name = "router"
    cfg["zebra"] = {"static_routes": []}
    assert cfg.name == "router"
    assert cfg["zebra"]["static_routes"] == []
    assert cfg.missing_attr is None


def test_node_config_sysctl_format():
    cfg = NodeConfig(node=cast(IPNode, Mock(name="node")))
    cfg.sysctl = "net.ipv4.ip_forward=1"
    assert ("net.ipv4.ip_forward", "1") in list(cfg.sysctl)

    with pytest.raises(ValueError):
        cfg.sysctl = "net.ipv4.ip_forward"


def test_require_cmd_reports_help():
    with pytest.raises(RuntimeError):
        require_cmd(
            "definitely-missing-ipmininet-test-command",
            help_str="missing command",
        )
