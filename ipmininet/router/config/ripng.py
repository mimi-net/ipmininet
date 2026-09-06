"""Base classes to configure a RIP daemon"""

from ipaddress import IPv6Interface, ip_interface

from ipmininet.link import IPIntf

from .utils import ConfigDict, interface_props
from .zebra import MgmtdBackendDaemon

UPDATE_TIMER = 30
TIMEOUT_TIMER = 180
GARBAGE_TIMER = 120


class RIPng(MgmtdBackendDaemon):
    """This class provides a simple configuration for an RIP daemon.
    It advertizes one network per interface (the primary one),
    and set interfaces not facing another L3Router to passive"""

    NAME = "ripngd"
    KILL_PATTERNS = (NAME,)

    def build(self):
        cfg = super().build()
        cfg.redistribute = self.options.redistribute
        cfg.split_horizon = self.options.split_horizon
        cfg.split_horizon_with_poison = self.options.split_horizon_with_poison
        cfg.update_timer = self.options.update_timer
        cfg.timeout_timer = self.options.timeout_timer
        cfg.garbage_timer = self.options.garbage_timer
        return self.build_interface_config(cfg)

    @staticmethod
    def _build_networks(interfaces: list[IPIntf]) -> list["RIPNetwork"]:
        """Return the list of RIP networks to advertize from the list of
        active RIP interfaces"""
        return [
            RIPNetwork(domain=ip_interface(f"{i.ip6}/{i.prefixLen6}"))
            for i in interfaces
            if i.ip6
        ]

    def _build_interfaces(self, interfaces: list[IPIntf]) -> list[ConfigDict]:
        """Return the list of RIP interface properties from the list of
        active interfaces"""
        return interface_props(
            interfaces,
            lambda i: {
                "cost": i.igp_metric - 1,
                "domain": ip_interface(f"{i.ip6}/{i.prefixLen6}"),
            },
        )

    def set_defaults(self, defaults):
        """:param debug: the set of debug events that should be logged
                         (default: []).
        :param redistribute: set of RIPngRedistributedRoute sources
                             (default: []).
        :param split_horizon: the daemon uses the split-horizon method
                              (default: False).
        :param split_horizon_with_poison: the daemon uses the split-horizon.
         with reversed poison method. If both split_horizon_with_poison
         and split_horizon are set to True, RIPng will use the split-horizon
         with reversed poison method (default: True).
        :param update_timer: routing table timer value in second
                             (default value:30).
        :param timeout_timer: routing information timeout timer
                              (default value:180).
        :param garbage_timer: garbage collection timer
                              (default value:120)."""
        defaults.redistribute = []
        defaults.split_horizon = False
        defaults.split_horizon_with_poison = True
        defaults.update_timer = UPDATE_TIMER
        defaults.timeout_timer = TIMEOUT_TIMER
        defaults.garbage_timer = GARBAGE_TIMER
        super().set_defaults(defaults)


class RIPNetwork:
    """A class holding an RIP network properties"""

    def __init__(self, domain: IPv6Interface):
        self.domain = domain


class RIPRedistributedRoute:
    """A class representing a redistributed route type in RIP"""

    def __init__(self, subtype: str, metric=1000):
        self.subtype = subtype
        self.metric = metric
