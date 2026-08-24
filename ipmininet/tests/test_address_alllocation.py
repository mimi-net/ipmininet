import pytest

from ipmininet.clean import cleanup
from ipmininet.examples.simple_bgp_network import SimpleBGPTopo
from ipmininet.examples.simple_ospf_network import SimpleOSPFNet
from ipmininet.examples.simple_ospfv3_network import SimpleOSPFv3Net
from ipmininet.ipnet import IPNet
from ipmininet.tests import require_root


@require_root
@pytest.mark.parametrize("topo,use_v4,use_v6", [
    (SimpleBGPTopo, True, True),
    (SimpleBGPTopo, True, False),
    (SimpleBGPTopo, False, True),
    (SimpleOSPFNet, True, True),  # Routers with use_v6=False
    (SimpleOSPFv3Net, True, True),  # Routers with use_v4=False
])
def test_v4_and_v6_only_network(topo, use_v4, use_v6):
    try:
        net = IPNet(topo=topo(), use_v4=use_v4, use_v6=use_v6)
        net.start()

        for n in net.routers + net.hosts:
            for itf in n.intfList():
                if itf.node.use_v4 and net.use_v4:
                    assert len(list(itf.ips())) == itf.interface_width[0], \
                        "Did not allocate enough IPv4 addresses on interface " \
                        f"{itf}"
                else:
                    assert len(list(itf.ips())) == 0,\
                        "Should not allocate IPv4 addresses on interface " \
                        f"{itf}"
                if itf.node.use_v6 and net.use_v6:
                    assert len(list(itf.ip6s(exclude_lls=True))) == \
                           itf.interface_width[1], \
                        "Did not allocate enough IPv6 addresses on interface " \
                        f"{itf}"
                else:
                    assert len(list(itf.ip6s(exclude_lls=True))) == 0, \
                        "Should not allocate IPv6 addresses on interface " \
                        f"{itf}"
        net.stop()
    finally:
        cleanup()
