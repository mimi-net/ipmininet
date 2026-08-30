"""This module tests the TopologyDB class"""
import itertools
import os
import shutil
import tempfile
from typing import Type

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
from ipmininet.utils import realIntfList, otherIntf


@require_root
@pytest.mark.parametrize("topology", [
    SimpleOSPFNet, SimpleOSPFv3Net, StaticAddressNet,
    BGPDecisionProcess, SpanningTreeNet
])
def test_topologydb(topology: Type[IPTopo]):
    net = IPNet(topo=topology())
    db_dir = tempfile.mkdtemp()
    try:
        db = TopologyDB(net=net)

        db_path = os.path.join(db_dir, "topology.json")
        db.save(db_path)

        assert os.path.exists(db_path), \
            "TopologyDB did not write the JSON database"

        db = TopologyDB(db=db_path)

        for node in net.routers + net.hosts + net.switches:
            assert node.name in db._network, \
                "The node {} in the network is not in the DB file".format(node)

        for node, node_info in db._network.items():
            assert node in net, \
                "The node {} in the DB file is not in the network".format(node)

            # Check type

            assert "type" in node_info, \
                "No info on the type of node {}".format(node)
            node_type = node_info["type"]
            if node_type == "host":
                assert type(net[node]) == IPHost, "The node {} is not an " \
                                                  "host".format(node)
            elif node_type == "router":
                assert type(net[node]) == Router, "The node {} is not a " \
                                                  "router".format(node)
            elif node_type == "switch":
                assert type(net[node]) == IPSwitch, "The node {} is not a " \
                                                    "switch".format(node)
            else:
                pytest.fail("The node type {} of node {} is invalid"
                            .format(node_type, node))

            # Check interfaces

            assert "interfaces" in node_info, \
                "No information about interfaces of node {}".format(node)
            real_intfs = {itf.name for itf in realIntfList(net[node])}
            assert real_intfs == set(node_info["interfaces"]), \
                "The interface list is not the same on node {}".format(node)

            for info_key, info_value in node_info.items():
                if info_key == "type" or info_key == "interfaces":
                    continue

                try:
                    intf = net[node].intf(info_key)
                    # info_key is a interface name
                except KeyError:
                    # info_key is a node name
                    assert info_key in net, \
                        "{} is neither a node nor an interface nor a special " \
                        "key of node {}".format(info_key, node)
                    intf = net[node].intf(info_value["name"])

                    # Checks that the node is a neighbor
                    assert otherIntf(intf).node.name == info_key, \
                        "The node {} has no neighbor node {}".format(node,
                                                                     info_key)

                # Checks the IP address
                assert info_value["ip"] == '%s/%s' % (intf.ip, intf.prefixLen), \
                    "The IP address of the record {} of node {} does not " \
                    "match".format(info_key, node)

                # Checks the IP prefixes
                prefixes = {ip.with_prefixlen
                            for ip in itertools.chain(intf.ips(), intf.ip6s())}
                assert set(info_value["ips"]) == prefixes, \
                    "The IP prefixes of the record {} of node {} do not " \
                    "match".format(info_key, node)

    finally:
        net.stop()
        shutil.rmtree(db_dir, ignore_errors=True)
