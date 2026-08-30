"""This network emulates delay and bandwidth constraints on the links.

This network avoids pitfalls when mixing bandwidth and delay emulation on
the same interface by creating additional switches on the links. For more
details, you can refer to the IPMininet documentation.
"""

from ipmininet.iptopo import IPTopo


class TCAdvancedNet(IPTopo):
    def __init__(self, *args, **kwargs):
        self.switch_count = 0
        super().__init__(*args, **kwargs)

    def build(self, *args, **kwargs):
        h1 = self.addHost("h1")
        r1, r2 = self.addRouters("r1", "r2")
        h2 = self.addHost("h2")

        self.addLink(h1, r1, bw=100, delay="15ms")
        self.addLink(r1, r2, bw=10, delay="5ms")
        self.addLink(r2, h2, bw=1000, params1={"delay": "7ms"})

        super().build(*args, **kwargs)

    # We need at least 2ms of delay for accurate emulation
    def addLink(self, node1, node2, delay="2ms", bw=None, max_queue_size=None, **opts):
        src_delay = None
        dst_delay = None
        opts1 = dict(opts)
        if "params2" in opts1:
            opts1.pop("params2")
        try:
            src_delay = opts.get("params1", {}).pop("delay")
        except KeyError:
            pass
        opts2 = dict(opts)
        if "params1" in opts2:
            opts2.pop("params1")
        try:
            dst_delay = opts.get("params2", {}).pop("delay")
        except KeyError:
            pass

        src_delay = src_delay or delay
        dst_delay = dst_delay or delay

        # node1 -> switch
        default_params1 = {"bw": bw}
        default_params1.update(opts.get("params1", {}))
        opts1["params1"] = default_params1

        # node2 -> switch
        default_params2 = {"bw": bw}
        default_params2.update(opts.get("params2", {}))
        opts2["params2"] = default_params2

        # switch -> node1
        opts1["params2"] = {"delay": dst_delay, "max_queue_size": max_queue_size}
        # switch -> node2
        opts2["params1"] = {"delay": src_delay, "max_queue_size": max_queue_size}

        # Netem queues will mess with shaping
        # Therefore, we put them on an intermediary switch
        self.switch_count += 1
        s = "s%d" % self.switch_count
        self.addSwitch(s)
        return super().addLink(node1, s, **opts1), super().addLink(s, node2, **opts2)
