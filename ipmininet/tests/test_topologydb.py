"""This module tests the TopologyDB class"""

import itertools
import os
import shutil
import tempfile
from ipaddress import ip_interface

import pytest

from ipmininet.examples.bgp_decision_process import BGPDecisionProcess
from ipmininet.examples.simple_ospf_network import SimpleOSPFNet
from ipmininet.examples.simple_ospfv3_network import SimpleOSPFv3Net
from ipmininet.examples.spanning_tree import SpanningTreeNet
from ipmininet.examples.static_address_network import StaticAddressNet
from ipmininet.host import IPHost
from ipmininet.ipnet import IPNet
from ipmininet.ipswitch import IPSwitch
from ipmininet.iptopo import IPTopo
from ipmininet.router import Router
from ipmininet.tests import require_root
from ipmininet.topologydb import (
    NoSuchLinkError,
    NoSuchNodeError,
    NotARouterError,
    TopologyDB,
)
from ipmininet.utils import otherIntf, realIntfList

_MIN_SUBNET_ADDRESSES = 2


class _MixedNetworkTopo(IPTopo):
    """A small network mixing routers, hosts and a switch"""

    def build(self, *args, **kwargs):
        r1 = self.addRouter("r1")
        r2 = self.addRouter("r2")
        h1 = self.addHost("h1")
        s1 = self.addSwitch("s1")
        h2 = self.addHost("h2")
        h3 = self.addHost("h3")
        self.addLink(r1, r2)
        self.addLink(h1, r1)
        self.addLink(r1, s1)
        self.addLink(s1, h2)
        self.addLink(s1, h3)
        super().build(*args, **kwargs)


@require_root
@pytest.mark.parametrize(
    "topology",
    [
        SimpleOSPFNet,
        SimpleOSPFv3Net,
        StaticAddressNet,
        BGPDecisionProcess,
        SpanningTreeNet,
    ],
)
def test_topologydb(topology: type[IPTopo]):
    net = IPNet(topo=topology())
    db_dir = tempfile.mkdtemp()
    try:
        db = TopologyDB(net=net)

        db_path = os.path.join(db_dir, "topology.json")
        db.save(db_path)

        assert os.path.exists(db_path), "TopologyDB did not write the JSON database"

        db = TopologyDB(db=db_path)

        for node in net.routers + net.hosts + net.switches:
            assert node.name in db._network, (
                f"The node {node} in the network is not in the DB file"
            )

        for node, node_info in db._network.items():
            assert node in net, f"The node {node} in the DB file is not in the network"

            # Check type

            assert "type" in node_info, f"No info on the type of node {node}"
            node_type = node_info["type"]
            if node_type == "host":
                assert isinstance(net[node], IPHost), f"The node {node} is not an host"
            elif node_type == "router":
                assert isinstance(net[node], Router), f"The node {node} is not a router"
            elif node_type == "switch":
                assert isinstance(net[node], IPSwitch), (
                    f"The node {node} is not a switch"
                )
            else:
                pytest.fail(f"The node type {node_type} of node {node} is invalid")

            # Check interfaces

            assert "interfaces" in node_info, (
                f"No information about interfaces of node {node}"
            )
            real_intfs = {itf.name for itf in realIntfList(net[node])}
            assert real_intfs == set(node_info["interfaces"]), (
                f"The interface list is not the same on node {node}"
            )

            for info_key, info_value in node_info.items():
                if info_key == "type" or info_key == "interfaces":
                    continue

                try:
                    intf = net[node].intf(info_key)
                    # info_key is a interface name
                except KeyError:
                    # info_key is a node name
                    assert info_key in net, (
                        f"{info_key} is neither a node nor an interface nor a special "
                        f"key of node {node}"
                    )
                    intf = net[node].intf(info_value["name"])

                    # Checks that the node is a neighbor
                    assert otherIntf(intf).node.name == info_key, (
                        f"The node {node} has no neighbor node {info_key}"
                    )

                # Checks the IP address
                assert info_value["ip"] == f"{intf.ip}/{intf.prefixLen}", (
                    f"The IP address of the record {info_key} of node {node} "
                    "does not match"
                )

                # Checks the IP prefixes
                prefixes = {
                    ip.with_prefixlen for ip in itertools.chain(intf.ips(), intf.ip6s())
                }
                assert set(info_value["ips"]) == prefixes, (
                    f"The IP prefixes of the record {info_key} of node {node} "
                    "do not match"
                )

    finally:
        net.stop()
        shutil.rmtree(db_dir, ignore_errors=True)


@require_root
def test_topologydb_lookups_and_errors():
    net = IPNet(topo=_MixedNetworkTopo())
    try:
        db = TopologyDB(net=net)

        assert db["r1"]["type"] == "router"
        assert db.node("h1")["type"] == "host"

        itf_names = db.interfaces("h1")
        assert itf_names
        itf = net["h1"].intf(itf_names[0])
        assert otherIntf(itf) is not None and otherIntf(itf).node.name == "r1"
        assert db.interface("h1", "r1") == ip_interface(db["h1"]["r1"]["ip"])
        assert db.subnet("h1", "r1").num_addresses >= _MIN_SUBNET_ADDRESSES

        assert db.interface_bandwidth("h1", "r1") in (None, -1)

        interfaces = {itf.name for itf in realIntfList(net["r1"])}
        assert set(db.interfaces("r1")) == interfaces

        with pytest.raises(NoSuchNodeError):
            db["ghost"]
        with pytest.raises(NoSuchNodeError):
            db.interface("ghost", "r1")
        with pytest.raises(NoSuchLinkError):
            db.interface("h1", "ghost")
        with pytest.raises(NoSuchLinkError):
            db.interface_bandwidth("h1", "ghost")
        with pytest.raises(NotARouterError):
            db.routerid("h1")
    finally:
        net.stop()


def test_topologydb_without_data():
    db = TopologyDB()
    assert db._network == {}
