from .base import HostDaemon
from ipmininet.router.config.utils import ConfigDict
from mininet.log import info
import re
import tempfile


class Dnsmasq(HostDaemon):
    NAME = "dnsmasq"
    KILL_PATTERNS = ("dnsmasq",)

    def __init__(self, node, ip_range, mask, gw, **kwargs):
        self.node = node
        self.pid_file = tempfile.mktemp(dir='/tmp')
        self.popen = None
        self.ip_range = ip_range
        self.mask = mask
        self.gw = gw
        self.opts = {
            "dhcp-range": f"{ip_range},{mask}", 
            "dhcp-option": f"3,{gw}", 
            "pid-file": self.pid_file,
            "port": 0,
            "log-queries": None, 
            "log-dhcp": None, 
            "bind-interfaces": None,
        }
        super().__init__(node, **kwargs)

    def build(self) -> ConfigDict:
        cfg = super().build()
        cfg.pid_file = self.pid_file
        cfg.ip_range = self.ip_range
        cfg.mask = self.mask
        cfg.gw = self.gw
        cfg.interfaces = self.node.intfNames()
        self.opts["interface"] = self.node.intfNames()
        cfg.opts = self.opts
        return cfg

    @property
    def startup_line(self):
        return f"{self.NAME} --conf-file={self.cfg_filenames[0]}"

    @property
    def dry_run(self):
        return ""

    @property
    def cfg_filenames(self):
        return [self._file(suffix=f"cfg")]

    @property
    def template_filenames(self):
        return super().template_filenames + ["%s.mako" % self.NAME]

    def set_defaults(self, defaults):
        pass

    @property
    def pids(self):
        output = self.node.cmd("ss -tulnp | grep dnsmasq")

        if not output:
            return None
        match = re.findall(r'pid=(\d+)', output)
        if match:
            return match
        
        return None

    def kill(self):
        pid_str = self.node.cmd(f"cat {self.pid_file}").strip()
        self.node.cmd(f"kill -9 {pid_str}")

    def cleanup(self):
        self.kill()
