""""This module test the Link Failure API"""

import pytest

from ipmininet.clean import cleanup
from ipmininet.ipnet import IPNet
from ipmininet.iptopo import IPTopo

from ..examples.link_failure import FailureTopo
from . import require_root
from .utils import assert_connectivity, assert_node_not_connected


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
@pytest.mark.parametrize("plan", [
    [("r1", "r2")],
    [("h1", "r1")],
    [("r1", "h1"), ("r2", "r1"), ("r2", "h2")],
])
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

        itfs = net.randomFailure(1,
                                 weak_links=[net["r1"].intf("r1-eth0").link])

        # Check a failure between both hosts
        assert_node_not_connected(src=net["h1"], dst=net["h2"], v6=False)
        assert_node_not_connected(src=net["h1"], dst=net["h2"], v6=True)

        net.restoreIntfs(itfs)

        # Check link restoration
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)
        net.stop()
    finally:
        cleanup()
