""""This module test the Link Failure API"""
from ipmininet.clean import cleanup
from ipmininet.ipnet import IPNet
from ipmininet.overlay import NetworkCapture
from . import require_root, require_mimidump
from .utils import assert_connectivity
from ..examples.network_capture import NetworkCaptureTopo


@require_mimidump
@require_root
def test_network_capture_example():
    try:
        net = IPNet(topo=NetworkCaptureTopo())
        net.start()
        overlay = next(o for o in net.topo.overlays
                       if isinstance(o, NetworkCapture))

        # Capture readiness is asynchronous; wait for it instead of asserting
        # file existence immediately after net.start().
        assert overlay.wait_until_capturing("r2-eth0", timeout=10)
        assert overlay.wait_until_capturing("s2-eth1", timeout=10)
        assert overlay.wait_until_capturing("r1", timeout=10)
        assert overlay.wait_until_capturing("s1", timeout=10)

        # Check example connectivity
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)

        net.stop()
    finally:
        cleanup()


@require_mimidump
@require_root
def test_network_capture_wait_until_capturing():
    try:
        net = IPNet(topo=NetworkCaptureTopo())
        net.start()
        overlay = next(o for o in net.topo.overlays
                       if isinstance(o, NetworkCapture))

        # Captures on interfaces (mimidump) become live once the READY signal
        # is received
        assert overlay.wait_until_capturing("r2-eth0", timeout=10)
        assert overlay.wait_until_capturing("s2-eth1", timeout=10)

        # Captures on nodes (tcpdump) become live once their output file exists
        assert overlay.wait_until_capturing("r1", timeout=10)
        assert overlay.wait_until_capturing("s1", timeout=10)

        # Captures that were never started are not live
        assert not overlay.wait_until_capturing("does-not-exist", timeout=1)

        net.stop()
    finally:
        cleanup()
