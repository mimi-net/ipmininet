"""This modules defines the IPSwitch class allowing to better support STP
and to create hubs"""

from mininet.nodelib import LinuxBridge

from ipmininet.utils import require_cmd


class IPSwitch(LinuxBridge):
    """Linux Bridge (with optional spanning tree) extended to include
    the hubs"""

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        name: str,
        stp=True,
        hub=False,
        prio: int | None = None,
        cwd="/tmp",
        stp_forward_delay: int | None = None,
        stp_hello_time: int | None = None,
        **kwargs,
    ):
        """:param name: the name of the node
        :param stp: whether to use spanning tree protocol
        :param hub: whether this switch behaves as a hub (this disable stp)
        :param prio: optional explicit bridge priority for STP
        :param cwd: The base directory for temporary files such as configs
        :param stp_forward_delay: optional STP forward delay in seconds
                                  (kernel default is 15)
        :param stp_hello_time: optional STP hello time in seconds
                               (kernel default is 2)"""
        self.hub = hub
        self.cwd = cwd
        self.stp_forward_delay = stp_forward_delay
        self.stp_hello_time = stp_hello_time
        stp = stp and not hub
        LinuxBridge.__init__(self, name, stp=stp, prio=prio, **kwargs)

    def start(self, _controllers):
        """Start Linux bridge"""
        require_cmd("brctl", help_str=f"You need brctl to use {self.__class__} objects")

        self.cmd("ifconfig", self, "down")
        self.cmd("brctl delbr", self)
        self.cmd("brctl addbr", self)
        if self.hub:
            self.cmd("brctl setageing ", self, " 0")
        if self.stp:
            self.cmd("brctl setbridgeprio", self, self.prio)
            self.cmd("brctl stp", self, "on")
            # Accelerate convergence when requested (kernel requires the
            # forward delay to be at least twice the hello time)
            if self.stp_forward_delay is not None:
                self.cmd("brctl setfd", self, self.stp_forward_delay)
            if self.stp_hello_time is not None:
                self.cmd("brctl sethello", self, self.stp_hello_time)
        for i in self.intfList():
            if self.name in i.name:
                self.cmd("brctl addif", self, i)
                self.cmd(
                    f"brctl setpathcost {self.name} {i.name} "
                    f"{i.params.get('stp_cost', 1)}"
                )
        # Start the captures on this switch
        for capture in self.params.get("captures", []):
            capture.start(node=self)
        for intf in self.intfList():
            for capture in intf.params.get("captures", []):
                capture.start(intf=intf)
        self.cmd("ifconfig", self, "up")

    def stop(self, deleteIntfs=True):
        # Stop the captures on this switch
        for capture in self.params.get("captures", []):
            capture.stop(node=self)
        for intf in self.intfList():
            for capture in intf.params.get("captures", []):
                capture.stop(intf=intf)
        super().stop(deleteIntfs=deleteIntfs)
