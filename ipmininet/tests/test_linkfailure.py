""" "This module test the Link Failure API"""

from ipaddress import ip_network

import pytest

from ipmininet.clean import cleanup
from ipmininet.ipnet import IPNet
from ipmininet.iptopo import IPTopo

from ..examples.link_failure import FailureTopo
from . import require_root
from .utils import assert_connectivity, assert_node_not_connected, assert_routing_table


def _wait_reconvergence(net: IPNet, timeout=180):
    """Wait for OSPF to recompute routes after link restoration.

    The connectivity probe can false-negative while the routing tables are
    still empty right after `restoreIntfs`, so wait for each router to learn
    a route to the far host (both address families) before probing.
    """
    for v6 in (False, True):
        for router, far in (("r1", net["h2"]), ("r2", net["h1"])):
            itf = far.defaultIntf()
            far_ip = itf.ip6 if v6 else itf.ip
            plen = itf.prefixLen6 if v6 else itf.prefixLen
            prefix = str(ip_network(f"{far_ip}/{plen}", strict=False))
            assert_routing_table(net[router], [prefix], present=True, timeout=timeout)


class Topo(IPTopo):
    def build(self, *args, **kwargs):
        r1 = self.addRouter("r1")
        r2 = self.addRouter("r2")
        h1 = self.addHost("h1")
        h2 = self.addHost("h2")

        self.addLinks((r1, r2), (h1, r1), (h2, r2))
        super().build(*args, **kwargs)


@require_root
def test_failure_topo():
    try:
        net = IPNet(topo=FailureTopo())
        net.start()

        # Check example connectivity
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)

        net.stop()
    finally:
        cleanup()


@require_root
@pytest.mark.parametrize(
    "plan",
    [
        [("r1", "r2")],
        [("h1", "r1")],
        [("r1", "h1"), ("r2", "r1"), ("r2", "h2")],
    ],
)
def test_failurePlan(plan):
    try:
        net = IPNet(topo=Topo())
        net.start()

        # Wait for OSPF convergence
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)

        interface_down = net.runFailurePlan(plan)

        # Check failures
        for n1, n2 in plan:
            assert_node_not_connected(src=net[n1], dst=net[n2], v6=False)
            assert_node_not_connected(src=net[n1], dst=net[n2], v6=True)

        net.restoreIntfs(interface_down)

        # Wait for OSPF reconvergence before probing connectivity
        _wait_reconvergence(net)

        # Check link restoration
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)
        net.stop()
    finally:
        cleanup()


@require_root
@pytest.mark.parametrize("downed_links", [1, 2, 3])
def test_randomFailure(downed_links):
    try:
        net = IPNet(topo=Topo())
        net.start()

        # Wait for OSPF convergence
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)

        interface_down = net.randomFailure(downed_links)

        # Check a failure between both hosts
        assert_node_not_connected(src=net["h1"], dst=net["h2"], v6=False)
        assert_node_not_connected(src=net["h1"], dst=net["h2"], v6=True)

        net.restoreIntfs(interface_down)

        # Wait for OSPF reconvergence before probing connectivity
        _wait_reconvergence(net)

        # Check link restoration
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)
        net.stop()
    finally:
        cleanup()


@require_root
def test_randomFailureOnTargetedLink():
    try:
        net = IPNet(topo=Topo())
        net.start()

        # Wait for OSPF convergence
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)

        itfs = net.randomFailure(1, weak_links=[net["r1"].intf("r1-eth0").link])

        # Check a failure between both hosts
        assert_node_not_connected(src=net["h1"], dst=net["h2"], v6=False)
        assert_node_not_connected(src=net["h1"], dst=net["h2"], v6=True)

        net.restoreIntfs(itfs)

        # Wait for OSPF reconvergence before probing connectivity
        _wait_reconvergence(net)

        # Check link restoration
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)
        net.stop()
    finally:
        cleanup()


@require_root
def test_ping_and_failure_api_edges():
    """Exercise the corner cases of the ping and failure APIs on a live net."""
    try:
        net = IPNet(topo=Topo())
        net.start()

        # Wait for OSPF convergence before touching the failure APIs
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)

        # Ping API corner cases
        assert net.ping(use_v4=False, use_v6=False) == 0
        assert net.ping(hosts=[]) == 0

        # Failure API corner cases: bogus nodes and too many downed links
        assert net.runFailurePlan([("ghost1", "ghost2")]) == []
        assert net.randomFailure(99) == []

        net.stop()
    finally:
        cleanup()
