"""This modules show how to add GRE tunnels on top of an existing network.
It introduces a stretched IP network that spans across the two hosts, with no
cooperation from the routers."""
from ipmininet.iptopo import IPTopo
from ipmininet.link import GRETunnel


class GRETopo(IPTopo):
    """
    h1 -- r1 -- r2 -- r3 -- r4 -- h2
     |                            |
     +---- GRE (10.0.1.0/24) -----+"""
    def build(self, *args, **kw):
        r1, r2, r3, r4 = map(self.addRouter, ("r1", "r2", "r3", "r4"))
        self.h1, self.h2 = map(self.addHost, ("h1", "h2"))
        for s, d in ((r1, r2), (r1, self.h1), (r2, r3), (r3, r4),
                     (r4, self.h2)):
            self.addLink(s, d)
        super().build(*args, **kw)

    def post_build(self, net):
        GRETunnel(net[self.h1].defaultIntf(), net[self.h2].defaultIntf(),
                  "10.0.1.1/24", "10.0.1.2/24")
        super().post_build(net)
