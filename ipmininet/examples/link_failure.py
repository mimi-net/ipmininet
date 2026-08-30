from ipmininet.iptopo import IPTopo
from ipmininet.utils import realIntfList


class FailureTopo(IPTopo):
    """

    +-----+                 +------+
    |  r1 +-----------------+  r2  |
    +---+-+                 +---+--+
        |        +-----+        |
        +--------| r3  |--------+
                 +--+--+
                    |
                 +--+--+
                 | r4  |
                 +-----+
    """

    def build(self, *args, **kwargs):
        r1 = self.addRouter("r1")
        r2 = self.addRouter("r2")
        r3 = self.addRouter("r3")
        r4 = self.addRouter("r4")
        self.addLinks((r1, r2), (r2, r3), (r3, r1), (r3, r4))
        super().build(*args, **kwargs)

    def post_build(self, net):
        # Run the failure plan and then, restore the links
        failure_plan = [("r1", "r2"), ("r3", "r4")]
        interfaces_down = net.runFailurePlan(failure_plan)
        net.restoreIntfs(interfaces_down)

        # Run a random failure with 2 link to be downed and then, restore them
        interfaces_down = net.randomFailure(2)
        net.restoreIntfs(interfaces_down)

        # Run a 1 link Failure Random based on a given list of link
        # and then, restore the link
        links = [x.link for x in realIntfList(net["r1"])]
        interfaces_down = net.randomFailure(1, weak_links=links)
        net.restoreIntfs(interfaces_down)
        super().post_build(net)
