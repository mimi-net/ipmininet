from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_network

from ipmininet.router.config.zebra import Mgmtd, QuaggaDaemon, Zebra


class STATIC(QuaggaDaemon):
    NAME = "staticd"
    DEPENDS = (Mgmtd, Zebra)
    KILL_PATTERNS = (NAME,)
    # Since FRR 9.0 staticd is an mgmtd backend: it rejects -f/-C and receives
    # its configuration through mgmtd, so we never pass a config file here and
    # push the rendered config afterwards via vtysh.
    _config_pushed = False

    @property
    def startup_line(self):
        return "{name} -i {pid} -z {api} -u root".format(
            name=self.NAME,
            pid=self._file("pid"),
            api=self.zebra_socket,
        )

    @property
    def dry_run(self):
        # staticd rejects -C; the config is validated when vtysh applies it.
        return "true"

    def build(self):
        cfg = super().build()
        # Update with preset defaults
        cfg.static_routes = self.options.static_routes
        return cfg

    def set_defaults(self, defaults):
        """:param debug: the set of debug events that should be logged
        :param static_routes: The set of StaticRoute to create"""
        defaults.static_routes = []
        super().set_defaults(defaults)

    def has_started(self, node_exec=None) -> bool:
        """Wait until staticd is up (its vty socket exists), then push its
        configuration through mgmtd exactly once via vtysh."""
        if node_exec is None or not self._daemon_up(node_exec):
            return False
        if self._config_pushed:
            return True
        self._push_config(node_exec)
        self._config_pushed = True
        return True

    def _daemon_up(self, node_exec) -> bool:
        """Return whether staticd has created its vty socket (i.e. it is
        running and has registered with mgmtd)."""
        return "staticd.vty" in node_exec.call("ls /var/run/frr/")

    def _push_config(self, node_exec) -> None:
        """Load the rendered staticd config into mgmtd with vtysh.

        vtysh reads the config file and distributes the staticd section to
        staticd through the mgmtd backend, which then programs the routes.
        """
        node_exec.call("vtysh", "-f", self.cfg_filename)


class StaticRoute:
    """A class representing a static route"""

    def __init__(
        self,
        prefix: str | IPv4Network | IPv6Network,
        nexthop: str | IPv4Address | IPv6Address,
        distance=1,
    ):
        """:param prefix: The prefix for this static route
        :param nexthop: The nexthop for this prefix, one of: <IP address,
                        interface name, null0, blackhole, reject>
        :param distance: The distance metric of the route"""
        self.prefix = ip_network(str(prefix))
        self.nexthop = nexthop
        self.distance = distance
