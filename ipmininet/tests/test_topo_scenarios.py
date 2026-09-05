"""Scenarios exercising the IPTopo DSL, the Subnet overlay and NetworkCapture.

These tests build real IPTopo descriptions the way a scenario would, without
starting any network or requiring root privileges. The Subnet and NetworkCapture
overlays are applied through ``topo.build()`` just like in a real experiment.
"""

from unittest.mock import Mock

import pytest

from ipmininet.iptopo import IPTopo, UnknownTopologyAttributeError
from ipmininet.node_description import (
    LinkDescription,
    LinkIndexError,
    NodeDescription,
    NodeNotOnLinkError,
)
from ipmininet.overlay import (
    NetworkCapture,
    NoCaptureAnchorError,
    Subnet,
    _capture_header_size,
)

_COST = 5
_PCAP_MAGIC_LE = b"\xd4\xc3\xb2\xa1"
_PCAP_MAGIC_BE = b"\xa1\xb2\xc3\xd4"
_PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"
_PCAP_GLOBAL_HEADER_SIZE = 24
_PCAPNG_SECTION_HEADER_SIZE = 28


def _ips_per_node(topo: IPTopo) -> dict[str, list[str]]:
    """Return the addresses assigned to each node's LAN interfaces."""
    ips: dict[str, list[str]] = {}
    for src, dst, _key, attrs in topo.iterLinks(withInfo=True, withKeys=True):
        for node, params in ((src, "params1"), (dst, "params2")):
            ips.setdefault(node, []).extend(attrs.get(params, {}).get("ip", ()))
    return ips


def _build_lan(prefix="s") -> IPTopo:
    topo = IPTopo()
    topo.addHost("h1")
    topo.addSwitch(prefix)
    topo.addHost("h2")
    topo.addLink("h1", prefix)
    topo.addLink(prefix, "h2")
    return topo


def test_topo_node_type_helpers():
    topo = IPTopo()
    topo.addRouter("r1")
    topo.addHost("h1")
    topo.addHub("hub1")
    topo.addLink("r1", "hub1")
    topo.addLink("hub1", "h1")
    topo.build()

    assert topo.isRouter("r1")
    assert not topo.isRouter("h1")
    assert topo.isHub("hub1")
    assert not topo.isHub("h1")
    assert not topo.isRouter("ghost")
    assert [str(r) for r in topo.routers()] == ["r1"]
    assert topo.hubs() == ["hub1"]
    assert [str(h) for h in topo.hosts()] == ["h1"]


def test_topo_overlay_dispatch():
    topo = IPTopo()
    topo.addHost("h1")
    topo.addSwitch("s1")
    topo.addLink("h1", "s1")
    assert topo.overlays == []

    topo.addSubnet(nodes=["h1"], subnets=["10.0.0.0/24"])
    topo.addNetworkCapture()
    assert [type(o).__name__ for o in topo.overlays] == ["Subnet", "NetworkCapture"]
    assert isinstance(topo.overlays[0], Subnet)
    assert isinstance(topo.overlays[1], NetworkCapture)


def test_topo_unknown_attribute_raises():
    topo = IPTopo()
    with pytest.raises(UnknownTopologyAttributeError):
        topo.addNoSuchOverlay()
    with pytest.raises(UnknownTopologyAttributeError):
        _ = topo.no_such_attribute


def test_subnet_assigns_addresses_in_order():
    topo = _build_lan()
    topo.addSubnet(nodes=["h1", "h2"], subnets=["10.0.0.0/24"])
    topo.build()

    assert topo.overlays[0].consistent
    ips = _ips_per_node(topo)
    assert ips["h1"] == ["10.0.0.1/24"]
    assert ips["h2"] == ["10.0.0.2/24"]


def test_subnet_multiple_subnets_same_interface():
    topo = _build_lan()
    topo.addSubnet(nodes=["h1", "h2"], subnets=["10.0.0.0/24", "192.168.0.0/30"])
    topo.build()

    ips = _ips_per_node(topo)
    assert ips["h1"] == ["10.0.0.1/24", "192.168.0.1/30"]
    assert ips["h2"] == ["10.0.0.2/24", "192.168.0.2/30"]


def test_subnet_nodes_on_distinct_lans_are_inconsistent():
    topo = IPTopo()
    topo.addHost("h1")
    topo.addHost("h2")
    topo.addSwitch("s1")
    topo.addSwitch("s2")
    topo.addLink("h1", "s1")
    topo.addLink("h2", "s2")
    topo.addSubnet(nodes=["h1", "h2"], subnets=["10.0.0.0/24"])
    topo.build()

    assert not topo.overlays[0].consistent


def test_subnet_too_small_is_inconsistent():
    topo = IPTopo()
    for host in ("h1", "h2", "h3", "h4"):
        topo.addHost(host)
    topo.addSwitch("s1")
    for host in ("h1", "h2", "h3", "h4"):
        topo.addLink(host, "s1")
    topo.addSubnet(nodes=["h1", "h2", "h3", "h4"], subnets=["10.0.0.0/30"])
    topo.build()

    assert not topo.overlays[0].consistent


def test_subnet_invalid_network_is_inconsistent():
    topo = _build_lan()
    topo.addSubnet(nodes=["h1", "h2"], subnets=["banana"])
    topo.build()

    assert not topo.overlays[0].consistent


def test_subnet_without_nodes_is_consistent():
    topo = _build_lan()
    topo.addSubnet(nodes=[], subnets=["10.0.0.0/24"])
    topo.build()

    assert topo.overlays[0].consistent
    assert not any(_ips_per_node(topo).values())


def test_overlay_element_properties():
    subnet = Subnet(nodes=["h1"], subnets=["10.0.0.0/24"])
    subnet.add_node("h2")
    subnet.set_node_property("h1", "some_key", True)
    subnet.set_link_property("h1-h2", "cost", _COST)

    assert subnet.nodes == ["h1", "h2"]
    assert subnet.node_property("h1")["some_key"]
    assert not subnet.node_property("h2").get("some_key")
    assert subnet.link_property("h1-h2")["cost"] == _COST


def test_network_capture_requires_anchor():
    capture = NetworkCapture()
    assert not capture.check_consistency(IPTopo())
    with pytest.raises(NoCaptureAnchorError):
        capture.start()


def test_link_description_indexing():
    topo = IPTopo()
    topo.addHost("h1")
    topo.addHost("h2")
    link = topo.addLink("h1", "h2")

    assert link[0].node == "h1"
    assert link[1].node == "h2"
    assert link[LinkDescription.KEY_INDEX] == link.key
    with pytest.raises(LinkIndexError):
        _ = link[2]


def test_link_description_node_lookup_errors():
    topo = IPTopo()
    topo.addHost("h1")
    topo.addHost("h2")
    link = topo.addLink("h1", "h2")

    assert link["h1"].node == "h1"
    assert link["h2"].node == "h2"
    with pytest.raises(NodeNotOnLinkError, match="is not on this link"):
        _ = link["ghost"]


def test_link_description_ordering_by_key():
    topo = IPTopo()
    topo.addHost("h1")
    topo.addHost("h2")
    first = topo.addLink("h1", "h2", key=1)
    second = topo.addLink("h1", "h2", key=2)

    assert first < second.key
    assert hash(first) == hash(1)
    assert first == 1


def test_node_description_without_topo_is_inert():
    node = NodeDescription("h1")

    node.addDaemon(Mock())
    assert node.get_config(Mock()) is None


def test_capture_header_size_reads_magic(tmp_path):
    for magic, expected in (
        (_PCAP_MAGIC_LE, _PCAP_GLOBAL_HEADER_SIZE),
        (_PCAP_MAGIC_BE, _PCAP_GLOBAL_HEADER_SIZE),
        (_PCAPNG_MAGIC, _PCAPNG_SECTION_HEADER_SIZE),
    ):
        capture = tmp_path / "capture.pcap"
        capture.write_bytes(magic + b"\x00" * 40)
        assert _capture_header_size(str(capture)) == expected


def test_capture_header_size_defaults(tmp_path):
    capture = tmp_path / "capture.unknown"
    capture.write_bytes(b"\xde\xad\xbe\xef" + b"\x00" * 40)
    assert _capture_header_size(str(capture)) == _PCAP_GLOBAL_HEADER_SIZE

    assert _capture_header_size(str(tmp_path / "missing.pcap")) == (
        _PCAP_GLOBAL_HEADER_SIZE
    )


def test_capture_header_size_ignores_empty_output(tmp_path):
    capture = tmp_path / "empty.pcap"
    capture.write_bytes(b"")
    assert _capture_header_size(str(capture)) == _PCAP_GLOBAL_HEADER_SIZE
