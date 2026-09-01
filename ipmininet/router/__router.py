"""This modules defines a L3 router class,
with a modular config system."""

import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from ipaddress import IPv4Interface, IPv6Interface

import mininet.clean
from mininet.log import lg
from mininet.node import Host, Node

from ipmininet import DEBUG_FLAG
from ipmininet.link import IPIntf
from ipmininet.utils import L3Router, otherIntf, realIntfList

from .config import BasicRouterConfig, NodeConfig, RouterConfig
from .config.base import Daemon
from .config.utils import ConfigDict


class ProcessHelper:
    """This class holds processes that are part of a given family, e.g. routing
    daemons. This also provides the abstraction to execute a new process,
    currently in a mininet namespace, but could be extended to execute in
    a different environment."""

    def __init__(self, node: "IPNode"):
        """:param node: The object to use to create subprocesses."""
        self.node = node
        self._pid_gen = 0
        self._processes = {}  # type: Dict[int, subprocess.Popen]

    def call(self, *args, **kwargs) -> str | None:
        """Call a command, wait for it to end and return its output.

        :param args: the command + arguments
        :param kwargs: key-val arguments, as used in subprocess.Popen"""
        return self.node.cmd(*args, **kwargs)

    def popen(self, *args, **kwargs) -> int:
        """Call a command and return a Popen handle to it.

        :param args: the command + arguments
        :param kwargs: key-val arguments, as used in subprocess.Popen
        :return: a process index in this family"""
        self._pid_gen += 1
        self._processes[self._pid_gen] = self.node.popen(*args, **kwargs)
        return self._pid_gen

    def pexec(self, *args, **kw) -> tuple[str, str, int]:
        """Call a command, wait for it to terminate and save stdout, stderr and
        its return code"""
        return self.node.pexec(*args, **kw)

    def get_process(self, pid):
        """Return a given process handle in this family

        :param pid: a process index, as return by popen"""
        return self._processes[pid]

    def terminate(self):
        """Terminate all processes in this family"""
        for p in self._processes.values():
            try:
                p.terminate()
                # we need to wait for the termination of the current
                # process so that the kernel can remove it from the
                # process table
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # if the process has not terminated yet,
                # we send a SIGKILL as ultimate resort.
                p.kill()
                # p.wait frees kernel resources and cleans the process table
                p.wait()

            except OSError:
                pass  # Process is already dead


class IPNode(Node):
    """A Node which manages a set of daemons"""

    def __init__(
        self,
        name: str,
        config: type[NodeConfig] | tuple[type[NodeConfig], dict] = NodeConfig,
        cwd="/tmp",
        process_manager: type[ProcessHelper] = ProcessHelper,
        use_v4=True,
        use_v6=True,
        create_logdirs=True,
        *args,
        **kwargs,
    ):
        """Most of the heavy lifting for this node should happen in the
        associated config object.

        :param config: The configuration generator for this node. Either a
                        class or a tuple (class, kwargs)
        :param cwd: The base directory for temporary files such as configs
        :param process_manager: The class that will manage all the associated
                                processes for this node
        :param use_v4: Whether this node has IPv4
        :param use_v6: Whether this node has IPv6"""
        super().__init__(name, *args, **kwargs)
        self.use_v4 = use_v4
        self.use_v6 = use_v6
        self.cwd = cwd
        self._old_sysctl = {}  # type: Dict[str, Union[str, int]]
        self.create_logdirs = create_logdirs
        if isinstance(config, tuple):
            try:
                self.nconfig = config[0](self, **config[1])
            except ValueError:
                lg.error(
                    "Expected a tuple (class, kwargs) for the config "
                    f"parameter but got instead {config!s}"
                )
        else:
            self.nconfig = config(self)
        self._processes = process_manager(self)
        self._daemons = []

    def start(self):
        """Start the node: Configure the daemons, set the relevant sysctls,
        and fire up all needed processes"""
        # Start the captures on this node
        for capture in self.get("captures", []):
            capture.start(node=self)
        # Build the config
        self.nconfig.build()
        # Check them
        err_code = False
        for d in self.nconfig.daemons:
            if self.create_logdirs and d.logdir:
                self._mklogdirs(d.logdir)
            out, err, code = self._processes.pexec(shlex.split(d.dry_run))
            err_code = err_code or code
            if code:
                lg.error(
                    d.NAME,
                    "configuration check failed [rcode:",
                    code,
                    "]\nstdout:",
                    out,
                    "\nstderr:",
                    err,
                )
        if err_code:
            lg.error("Config checks failed, aborting!")
            mininet.clean.cleanup()
            sys.exit(1)
        # Set relevant sysctls
        for opt, val in self.nconfig.sysctl:
            self._old_sysctl[opt] = self._set_sysctl(opt, val)

        # wait until NDP has finished to check each IPv6 addresses assigned
        # to the interface of the node.
        # The command lists addresses failing duplicate address detection (IPv6)
        # If any, it waits until all addresses has been checked.
        # Only IPv6 networks have addresses that go through DAD; for IPv4-only
        # nodes (use_v6=False) this poll would wait ~0.5 s per iteration on
        # nothing, so skip it entirely.
        if self.use_v6:
            lg.debug(
                self._processes.node.name, 'Checking for any "tentative" addresses'
            )
            tentative_cmd = "ip -6 addr show tentative"
            tentative_chk = self._processes.call(tentative_cmd)
            while tentative_chk is not None and tentative_chk != "":
                if tentative_chk.find("dadfailed") != -1:
                    lg.error("At least two nodes have the same IPv6 address!\n")
                    mininet.clean.cleanup()
                    sys.exit(1)
                time.sleep(0.5)
                tentative_chk = self._processes.call(tentative_cmd)
            lg.debug(
                self._processes.node.name,
                "All IPv6 addresses have passed the Duplicate address "
                "detection mechanism",
            )

        # Fire up all daemons
        for d in self.nconfig.daemons:
            self._processes.popen(shlex.split(d.startup_line), cwd=self.cwd)
            # Busy-wait if the daemon needs some time before being started
            while not d.has_started(self._processes):
                time.sleep(0.001)

    def build_daemon(self, daemon: Daemon):
        _cfg = ConfigDict()
        _cfg.name = self.name
        _cfg[daemon.NAME] = daemon.build()
        cfg = daemon.render(_cfg)
        daemon.write(cfg)

    def start_daemon(self, daemon: Daemon):
        self._processes.popen(shlex.split(daemon.startup_line), cwd=self.cwd)
        self._daemons.append(daemon)

    def terminate(self):
        """Stops this node and sets back all sysctls to their old values"""
        self._processes.terminate()
        if not DEBUG_FLAG:
            self.nconfig.cleanup()
            for d in self._daemons:
                d.cleanup()
        for opt, val in self._old_sysctl.items():
            self._set_sysctl(opt, val)
        # Stop the captures on this node
        for capture in self.get("captures", []):
            capture.stop(node=self)
        for intf in self.intfList():
            for capture in intf.get("captures", []):
                capture.stop(intf=intf)
        super().terminate()

    def _set_sysctl(self, key: str, val: str | int):
        """Change a sysctl value, and return the previous set value"""
        try:
            v = None
            out = self._processes.call("sysctl", key)
            if out is not None:
                v = out.split("=")[1].strip(" \n\t\r")
        except IndexError:
            v = None
        if v != val:
            self._processes.call("sysctl", "-w", f"{key}={val}")
        return v

    def _mklogdirs(self, logdir) -> tuple[str, str, int]:
        """Creates directories for the given logdir.

        :param logdir: The log directory path to create
        :return: (stdout, stderr, return_code)
        """
        lg.debug(f"{self.name}: Creating logdir {logdir}.\n")
        cmd = f"mkdir -p {logdir}"
        stdout, stderr, return_code = self._processes.pexec(shlex.split(cmd))
        if not return_code:
            lg.debug(f"{self.name}: Logdir {logdir} successfully created.\n")
        else:
            lg.error(
                f"{self.name}: Could not create logdir {logdir}. Stderr: \n{stderr}\n"
            )
        return (stdout, stderr, return_code)

    def get(self, key, val=None):
        """Check for a given key in the node parameters"""
        return self.params.get(key, val)

    def network_ips(self) -> dict[str, list[str]]:
        """Return all the addresses of the nodes connected directly or not
        to this node"""
        ips = {}  # type: Dict[str, List[str]]
        visited = set()  # type: Set[str]
        to_visit = [self]
        while to_visit:
            node = to_visit.pop()
            if node.name in visited:
                continue
            visited.add(node.name)
            if isinstance(node, (Host, IPNode)):
                for i in node.intfList():
                    for ip in list(i.ips()) + list(i.ip6s(exclude_lls=True)):
                        ips.setdefault(node.name, []).append(ip.ip.compressed)

            for i in realIntfList(node):
                adj_i = otherIntf(i)
                if adj_i is not None:
                    to_visit.append(adj_i.node)
        return ips


class Router(IPNode, L3Router):
    """The actual router, which manages a set of daemons"""

    def __init__(
        self,
        name,
        config: type[RouterConfig]
        | tuple[type[RouterConfig], dict] = BasicRouterConfig,
        password="zebra",
        lo_addresses: Sequence[str | IPv4Interface | IPv6Interface] = (),
        *args,
        **kwargs,
    ):
        """:param password: The password for the routing daemons vtysh access
        :param lo_addresses: The list of addresses to set on the loopback
                             interface"""
        super().__init__(name, *args, config=config, **kwargs)
        self.password = password

        # This interface already exists in the node,
        # so no need to move it
        node_params_for_lo = ["igp_area"]
        params = {k: v for k, v in kwargs.items() if k in node_params_for_lo}
        lo = IPIntf("lo", node=self, port=-1, moveIntfFn=lambda x, y: None, **params)
        lo.ip = lo_addresses

    @property
    def asn(self) -> int:
        return self.get("asn")
