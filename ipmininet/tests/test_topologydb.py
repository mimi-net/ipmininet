"""This module tests the TopologyDB class"""

import itertools
import os
import shutil
import tempfile

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
from ipmininet.topologydb import TopologyDB
from ipmininet.utils import otherIntf, realIntfList


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
                assert type(net[node]) == IPHost, f"The node {node} is not an host"
            elif node_type == "router":
                assert type(net[node]) == Router, f"The node {node} is not a router"
            elif node_type == "switch":
                assert type(net[node]) == IPSwitch, f"The node {node} is not a switch"
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
                assert info_value["ip"] == "%s/%s" % (intf.ip, intf.prefixLen), (
                    f"The IP address of the record {info_key} of node {node} does not "
                    "match"
                )

                # Checks the IP prefixes
                prefixes = {
                    ip.with_prefixlen for ip in itertools.chain(intf.ips(), intf.ip6s())
                }
                assert set(info_value["ips"]) == prefixes, (
                    f"The IP prefixes of the record {info_key} of node {node} do not "
                    "match"
                )

    finally:
        net.stop()
        shutil.rmtree(db_dir, ignore_errors=True)
