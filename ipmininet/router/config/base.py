"""This modules provides a config object for a router,
that is able to provide configurations for a set of routing daemons.
It also defines the base class for a daemon, as well as a minimalistic
configuration for a router."""

import abc
import os
from collections.abc import Iterable, Sequence
from contextlib import closing, suppress
from ipaddress import ip_address
from operator import attrgetter
from typing import (
    TYPE_CHECKING,
    Union,
)

import mako.exceptions
from mako.lookup import TemplateLookup
from mininet.log import lg as log

from ipmininet.link import OrderedAddress
from ipmininet.utils import realIntfList, require_cmd

from .utils import ConfigDict, ip_statement

if TYPE_CHECKING:
    from ipmininet.iptopo import IPTopo
    from ipmininet.node_description import NodeDescription
    from ipmininet.router import IPNode, OpenrRouter, ProcessHelper, Router
DaemonOption = Union[
    "Daemon", type["Daemon"], tuple[Union["Daemon", type["Daemon"]], dict]
]

__TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
router_template_lookup = TemplateLookup(directories=[__TEMPLATES_DIR])


class NodeConfig:
    """This class manages a set of daemons, and generates the global
    configuration for a node"""

    def __init__(
        self,
        node: "IPNode",
        daemons: Iterable[DaemonOption] = (),
        sysctl: dict[str, str | int] | None = None,
        *args,
        **kwargs,
    ):
        """Initialize our config builder

        :param node: The node for which this object will build configurations
        :param daemons: an iterable of active routing daemons for this node
        :param sysctl: A dictionary of sysctl to set for this node.
                       By default, it enables IPv4/IPv6 forwarding on all
                       interfaces."""
        self._node = node  # The node for which we will build the configuration

        self._daemons = {}  # type: Dict[str, Daemon]  # Active daemons
        for d in daemons:
            self.register_daemon(d)
        self._cfg = ConfigDict()  # Our root config object
        self._sysctl = sysctl if sysctl is not None else {}

    def build(self):
        """Build the configuration for each daemon, then write the
        configuration files"""

        # Mount a separate /etc/resolv.conf and /etc/hosts for the node
        resolv_file_mount = os.path.join(self._node.cwd, "resolv_%(name)s.conf")
        open(resolv_file_mount % self._node.__dict__, "w").close()
        host_file_mount = os.path.join(self._node.cwd, "hosts_%(name)s")
        self.build_host_file(host_file_mount % self._node.__dict__)
        self.add_private_fs_path(
            [
                ("/etc/resolv.conf", resolv_file_mount),
                ("/etc/hosts", host_file_mount),
                "/var/run/frr",
            ]
        )

        self._cfg.clear()
        self._cfg.name = self._node.name
        # Check that all daemons have their dependencies satisfied
        for cls in list(self._daemons.values()):
            for c in cls.DEPENDS:
                if c.NAME not in self._daemons:
                    self.register_daemon(c)
        # Execute any post registering action
        self.post_register_daemons()
        # Build their config
        for name, d in self._daemons.items():
            self._cfg[name] = d.build()
        # Write their config, using the global ConfigDict to handle
        # dependencies
        for d in self._daemons.values():
            cfg = d.render(self._cfg)
            d.write(cfg)

    def post_register_daemons(self):
        """Method called after all daemon classes were instantiated"""

    def cleanup(self):
        """Cleanup all temporary files for the daemons"""
        for d in self._daemons.values():
            d.cleanup()

    def register_daemon(self, cls: DaemonOption, **daemon_opts):
        """Add a new daemon to this configuration

        :param cls: Daemon class or object, or a 2-tuple (Daemon, dict)
        :param daemon_opts: Options to set on the daemons"""
        if isinstance(cls, tuple):
            try:
                cls, kw = cls
            except ValueError:
                raise TypeError(
                    f"Expected a tuple (Daemon, dict)  but got {cls!s}"
                ) from None
            daemon_opts.update(kw)
        if cls.NAME in self._daemons:
            return
        if not isinstance(cls, Daemon):
            if issubclass(cls, Daemon):
                cls = cls(self._node, **daemon_opts)
            else:
                raise TypeError(
                    f"Expected an object or a subclass of Daemon, got {cls} instead"
                )
        else:
            cls.options.update(daemon_opts)
        self._daemons[cls.NAME] = cls
        require_cmd(cls.NAME, "Could not find an executable for a daemon!")

    @property
    def sysctl(self):
        """Return an list of all sysctl to set on this node"""
        return self._sysctl.items()

    @sysctl.setter
    def sysctl(self, *values: str):
        """Sets sysctl to particular value.

        :param values: sysctl strings, as `key=val`
        Example:  RouterConfig().sysctl = 'net.ipv4.ip_forward=1',
                                          'net.ipv6.conf.all.forwarding=1'"""
        for value in values:
            try:
                key, val = value.split("=")
                self._sysctl[key] = val
            except ValueError:
                raise ValueError(
                    f"sysctl must be specified using `key=val` format. Ignoring {value}"
                ) from None

    @property
    def daemons(self):
        return sorted(self._daemons.values(), key=attrgetter("PRIO"))

    def daemon(self, key: Union[str, "Daemon", type["Daemon"]]) -> "Daemon":
        """Return the Daemon object in this config for the given key

        :param key: the daemon name or a daemon class or instance
        :return: the Daemon object
        :raise KeyError: if not found"""
        key_str = key.NAME if not isinstance(key, str) else key
        return self._daemons[key_str]

    def add_private_fs_path(self, loc: Sequence[str | tuple[str, str]] = ()):
        old_private_dirs = self._node.privateDirs
        try:
            self._node.privateDirs = loc
            self._node.mountPrivateDirs()
            old_private_dirs.extend(loc)
        finally:
            self._node.privateDirs = old_private_dirs

    def build_host_file(self, filename: str):
        # Copy the base file
        lines = []
        with open("/etc/hosts", "rb") as fileobj:
            lines.extend(fileobj.readlines())

        with open(filename, "wb") as fileobj:
            for node_name, ips in self._node.network_ips().items():
                fileobj.writelines(f"{ip}\t{node_name}\n".encode() for ip in ips)
            fileobj.write(b"\n")
            fileobj.write(b"".join(lines))


class RouterConfig(NodeConfig):
    # Last generated router id
    _last_routerid = ip_address("0.0.0.1")

    def __init__(self, node: "Router", sysctl=None, *args, **kwargs):
        self._sysctl = {"net.ipv4.ip_forward": 1, "net.ipv6.conf.all.forwarding": 1}
        if sysctl:
            self._sysctl.update(sysctl)
        super().__init__(node, *args, sysctl=self._sysctl, **kwargs)
        self.routerid = None

    def post_register_daemons(self):
        self._cfg.password = self._node.password
        # Set the router id
        self.routerid = self.compute_routerid()

    @classmethod
    def incr_last_routerid(cls):
        cls._last_routerid += 1

    def _equal_routerid(self, n: "Router") -> bool:

        # Router id of 'n' already set
        if n.nconfig.routerid:
            return str(n.nconfig.routerid) != str(self._last_routerid)

        # Check that a router id explicitly set
        # in any other daemon is not in conflict
        # with the current router id
        for d in n.nconfig.daemons:
            if (
                d != self
                and d.options.routerid
                and str(d.options.routerid) == str(self._last_routerid)
            ):
                return True

        # Check that the most-visible IPv4 address is not in conflict
        # with the current router id
        ip_list = sorted(
            (ip for itf in n.intfList() for ip in itf.ips()), key=OrderedAddress
        )
        return bool(
            len(ip_list) != 0 and str(ip_list.pop().ip) == str(self._last_routerid)
        )

    def compute_routerid(self) -> str:
        """Computes the default router id for all daemons.
        If a router ids were explicitly set for some of its daemons,
        the router id set to the daemon with the highest priority is chosen
        as the global router id.
        Otherwise if it has IPv4 addresses, it returns the most-visible one
        among its router interfaces.
        If both conditions are wrong, it generates a unique router id."""

        for d in self.daemons:
            if d.options.routerid:
                return d.options.routerid

        ip_list = sorted(
            (ip for itf in self._node.intfList() for ip in itf.ips()),
            key=OrderedAddress,
        )
        if len(ip_list) == 0:
            to_visit = realIntfList(self._node)
            # Explore all routers to check that none has the same router id
            while to_visit:
                self.incr_last_routerid()
                visited = set()  # type: Set[IPIntf]
                while to_visit:
                    i = to_visit.pop()
                    if i in visited:
                        continue
                    visited.add(i)
                    for n in i.broadcast_domain.routers:
                        if self._equal_routerid(n.node):
                            break  # We need to change the router id
                        to_visit.extend(realIntfList(n.node))
                to_visit = realIntfList(self._node) if to_visit else []
            return self._last_routerid.compressed
        return ip_list.pop().ip.compressed


class Daemon(metaclass=abc.ABCMeta):
    """This class serves as base for routing daemons"""

    # The name of this routing daemon
    NAME = None  # type: str
    # The priority of this daemon, relative to others
    # (e.g. to define startup order)
    PRIO = 10
    # The eventual dependencies of this daemon on other daemons
    DEPENDS = ()  # type: Sequence[Type[Daemon]]
    # The kill patterns to cleanup any processes started by this daemon
    KILL_PATTERNS = ()  # type: Sequence[str]

    def __init__(
        self,
        node: "IPNode",
        template_lookup: TemplateLookup = router_template_lookup,
        **kwargs,
    ):
        """:param node: The node for which we build the config
        :param template_lookup: The TemplateLookup object of the template
                                directory
        :param kwargs: Pre-set options for the daemon, see defaults()"""
        self._node = node
        self._startup_line = None  # type: Optional[str]
        self.files = []  # type: List[str]
        self.template_lookup = template_lookup
        self._options = self._defaults(**kwargs)

    @property
    def options(self) -> ConfigDict:
        """Get the options ConfigDict for this daemon"""
        return self._options

    @property
    def logdir(self) -> str:
        if "logfile" in self._options:
            return os.path.dirname(self._options["logfile"])
        return None

    def build(self) -> ConfigDict:
        """Build the configuration tree for this daemon

        :return: ConfigDict-like object describing this configuration"""
        cfg = ConfigDict()
        cfg.logfile = self._options["logfile"]
        return cfg

    def cleanup(self):
        """Cleanup the files belonging to this daemon"""
        for f in self.files:
            with suppress(OSError):
                os.unlink(f)
        self.files = []

    def render(self, cfg, **kwargs) -> dict[str, str]:
        """Render the configuration content for each config file of this daemon

        :param cfg: The global config for the node
        :param kwargs: Additional keywords args. will be passed directly
                       to the template"""
        self.files.extend(self.cfg_filenames)
        cfg_content = {}
        for i, filename in enumerate(self.cfg_filenames):
            log.debug(f"Generating {filename}\n")
            try:
                cfg.current_filename = filename
                kwargs["node"] = cfg
                kwargs["ip_statement"] = ip_statement
                template = self.template_lookup.get_template(self.template_filenames[i])
                cfg_content[filename] = template.render(**kwargs)
            except Exception:
                # Display template errors in a less cryptic way
                log.error(
                    "Couldnt render a config file(", self.template_filenames[i], ")"
                )
                log.error(mako.exceptions.text_error_template().render())
                raise ValueError(
                    f"Cannot render a configuration [{self._node.name}: {self.NAME}]"
                ) from None
        return cfg_content

    def write(self, cfg: dict[str, str]):
        """Write down the configuration files for this daemon

        :param cfg: The configuration string for each filename"""
        for filename in self.cfg_filenames:
            with closing(open(filename, "w")) as f:
                f.write(cfg[filename])

    @property
    @abc.abstractmethod
    def startup_line(self) -> str:
        """Return the corresponding startup_line for this daemon"""

    @property
    @abc.abstractmethod
    def dry_run(self) -> str:
        """The startup line to use to check that the daemon is
        well-configured"""

    def _filename(self, suffix: str) -> str:
        """Return a filename for this daemon and node,
        with the specified suffix"""
        return f"{self.NAME}_{self._node.name}.{suffix}"

    def _filepath(self, f: str) -> str:
        """Return a path towards a given file"""
        return os.path.join(self._node.cwd, f)

    def _file(self, suffix: str) -> str:
        """Generates a file name in the daemon's node cwd"""
        return self._filepath(self._filename(suffix=suffix))

    @property
    def cfg_filename(self) -> str:
        """Return the main filename in which this daemon config should be
        stored"""
        return self.cfg_filenames[0]

    @property
    def cfg_filenames(self) -> list[str]:
        """Return the list of filenames in which this daemon config should be
        stored"""
        return [self._file(suffix="cfg")]

    @property
    def template_filenames(self) -> list[str]:
        return [f"{self.NAME}.mako"]

    def _defaults(self, **kwargs) -> ConfigDict:
        """Return the default options for this daemon

        :param logfile: the path to the logfile for the daemon"""
        defaults = ConfigDict()
        defaults.logfile = self._file("log")
        # Apply daemon-specific defaults
        self.set_defaults(defaults)
        # Use user-supplied defaults if present
        defaults.update(**kwargs)
        return defaults

    @abc.abstractmethod
    def set_defaults(self, defaults):
        """Update defaults to contain the defaults specific to this daemon"""

    def has_started(self, node_exec: "ProcessHelper" = None) -> bool:
        """Return whether this daemon has started or not
        :param node_exec:
        """
        return True

    @classmethod
    def get_config(cls, topo: "IPTopo", node: "NodeDescription", **kwargs):
        """Returns a config object for the daemon if any"""
        return


class RouterDaemon(Daemon, metaclass=abc.ABCMeta):
    def build(self):
        cfg = super().build()
        cfg.routerid = self._options.routerid or self._node.nconfig.routerid
        return cfg

    @abc.abstractmethod
    def set_defaults(self, defaults):
        """:param logfile: the path to the logfile for the daemon
        :param routerid: the router id for this daemon"""


class BasicRouterConfig(RouterConfig):
    """A basic router that will run an OSPF daemon"""

    def __init__(
        self,
        node: "Router",
        daemons: Iterable[DaemonOption] = (),
        additional_daemons: Iterable[DaemonOption] = (),
        *args,
        **kwargs,
    ):
        """A simple router made of at least an OSPF daemon

        :param additional_daemons: Other daemons that should be used"""
        # Importing here to avoid circular import
        from .ospf import OSPF
        from .ospf6 import OSPF6

        # We don't want any zebra-specific settings, so we rely on the
        # OSPF/OSPF6 DEPENDS list for that daemon to run it with default
        # settings. We also don't want specific settings beside the defaults,
        # so we don't provide an instance but the class instead
        d = list(daemons)
        if node.use_v4:
            d.append(OSPF)
        if node.use_v6:
            d.append(OSPF6)
        d.extend(additional_daemons)
        super().__init__(node, *args, daemons=d, **kwargs)


class BorderRouterConfig(BasicRouterConfig):
    """A router config that will run both OSPF and BGP, and redistribute all
    connected router into BGP."""

    def __init__(
        self,
        node: "Router",
        daemons: Iterable[DaemonOption] = (),
        additional_daemons: Iterable[DaemonOption] = (),
        *args,
        **kwargs,
    ):
        """A simple router made of at least an OSPF daemon and a BGP daemon

        :param additional_daemons: Other daemons that should be used"""
        from .bgp import AF_INET, AF_INET6, BGP

        af = []
        if node.use_v4:
            af.append(AF_INET(redistribute=("connected", "ospf")))
        if node.use_v6:
            af.append(AF_INET6(redistribute=("connected", "ospf6")))
        if af:
            d = list(daemons)
            d.append((BGP, {"address_families": af}))
        super().__init__(node, *args, daemons=d, **kwargs)


class OpenrRouterConfig(RouterConfig):
    """A basic router that will run an OpenR daemon"""

    def __init__(
        self,
        node: "OpenrRouter",
        daemons: Iterable[DaemonOption] = (),
        additional_daemons: Iterable[DaemonOption] = (),
        *args,
        **kwargs,
    ):
        """A simple router made of at least an OpenR daemon

        :param additional_daemons: Other daemons that should be used"""
        # Importing here to avoid circular import
        from .openr import Openr

        daemon_list = list(daemons)
        daemon_list.append(Openr)
        daemon_list.extend(additional_daemons)
        super().__init__(node, *args, daemons=daemon_list, **kwargs)
