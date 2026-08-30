"""This module tests GRE tunnels"""
from ipmininet.clean import cleanup
from ipmininet.examples.gre import GRETopo
from ipmininet.ipnet import IPNet
from . import require_root
from .utils import wait_until


@require_root
def test_gre_example():
    try:
        net = IPNet(topo=GRETopo(), use_v6=False)
        net.start()

        cmd = "ping -W 1 -c 1 -I 10.0.1.1 10.0.1.2".split(" ")
        last_out = ""
        last_err = ""

        def _gre_ping_ok():
            nonlocal last_out, last_err
            p = net["h1"].popen(cmd)
            code = p.wait()
            last_out, last_err = p.communicate()
            return code == 0

        wait_until(
            _gre_ping_ok, timeout=60, interval=0.5,
            description=lambda: "the GRE tunnel from %s to 10.0.1.2 to be "
                                "usable\n[stdout]\n%s\n[stderr]\n%s"
                                % (net["h1"], last_out, last_err))

        net.stop()
    finally:
        cleanup()
