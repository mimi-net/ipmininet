import functools
from typing import TYPE_CHECKING, Optional

from ipmininet.host.config import HostConfig
from ipmininet.router.config import BasicRouterConfig
from ipmininet.router.config.base import Daemon, NodeConfig, RouterConfig

if TYPE_CHECKING:
    from ipmininet.iptopo import IPTopo


class LinkIndexError(IndexError):
    """Raised when a link is indexed with an unsupported integer index."""

    def __init__(self):
        super().__init__("Links have only two nodes and one key")


class NodeNotOnLinkError(KeyError):
    """Raised when a node that is not an endpoint indexes a link."""

    def __init__(self, node):
        super().__init__(f"Node '{node}' is not on this link")


class NodeDescription(str):
    def __new__(cls, value, *args, **kwargs):
        return super().__new__(cls, value)

    def __init__(self, o, topo: Optional["IPTopo"] = None):
        self.topo = topo
        self.node = o
        super().__init__()

    def addDaemon(
        self,
        daemon: Daemon | type[Daemon],
        default_cfg_class: type[NodeConfig] = BasicRouterConfig,
        cfg_daemon_list="daemons",
        **daemon_params,
    ):
        """Add the daemon to the list of daemons to start on the node.

        :param daemon: daemon class
        :param default_cfg_class: config class to use
            if there is no configuration class defined for the router yet.
        :param cfg_daemon_list: name of the parameter containing
            the list of daemons in your config class constructor.
            For instance, RouterConfig uses 'daemons'
            but BasicRouterConfig uses 'additional_daemons'.
        :param daemon_params: all the parameters to give
            when instantiating the daemon class."""
        if self.topo is None:
            return
        self.topo.addDaemon(
            self,
            daemon,
            default_cfg_class=default_cfg_class,
            cfg_daemon_list=cfg_daemon_list,
            **daemon_params,
        )

    def get_config(self, daemon: Daemon | type[Daemon], **kwargs):
        if self.topo is None:
            return None
        return daemon.get_config(topo=self.topo, node=self, **kwargs)


class RouterDescription(NodeDescription):
    def addDaemon(
        self,
        daemon: Daemon | type[Daemon],
        default_cfg_class: type[RouterConfig] = BasicRouterConfig,
        **kwargs,
    ):
        super().addDaemon(daemon, default_cfg_class=default_cfg_class, **kwargs)


class HostDescription(NodeDescription):
    def addDaemon(
        self,
        daemon: Daemon | type[Daemon],
        default_cfg_class: type[HostConfig] = HostConfig,
        **kwargs,
    ):
        super().addDaemon(daemon, default_cfg_class=default_cfg_class, **kwargs)


@functools.total_ordering
class LinkDescription:
    # Integer indexes used to access the two node interfaces and the key
    # of a link description, mirroring mininet.topo.Topo indexing.
    SRC_INDEX = 0
    DST_INDEX = 1
    KEY_INDEX = 3

    def __init__(self, topo: "IPTopo", src: str, dst: str, key, link_attrs: dict):
        self.src = src
        self.dst = dst
        self.key = key
        self.link_attrs = link_attrs
        self.src_intf = IntfDescription(
            self.src, topo, self, self.link_attrs.setdefault("params1", {})
        )
        self.dst_intf = IntfDescription(
            self.dst, topo, self, self.link_attrs.setdefault("params2", {})
        )
        super().__init__()

    def __getitem__(self, item):
        if isinstance(item, int):
            if item == self.SRC_INDEX:
                return self.src_intf
            if item == self.DST_INDEX:
                return self.dst_intf
            if item == self.KEY_INDEX:
                return self.key
            raise LinkIndexError()

        if item == self.src:
            return self.src_intf
        if item == self.dst:
            return self.dst_intf
        raise NodeNotOnLinkError(item)

    # The following methods allow this object to behave like an edge key
    # for mininet.topo.MultiGraph

    def __hash__(self):
        return self.key.__hash__()

    def __eq__(self, other):
        return self.key == other

    def __lt__(self, other):
        return self.key.__lt__(other)


class IntfDescription(NodeDescription):
    def __init__(self, o: str, topo: "IPTopo", link: LinkDescription, intf_attrs: dict):
        self.link = link
        self.intf_attrs = intf_attrs
        super().__init__(o, topo)

    def addParams(self, **kwargs):
        self.intf_attrs.update(kwargs)

    def __hash__(self):
        return self.node.__hash__()

    def __eq__(self, other):
        return self.node.__eq__(other)
