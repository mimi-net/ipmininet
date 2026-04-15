from .base import RouterDaemon
from ipmininet.router.config.utils import ConfigDict
import tempfile

class DHCPRelay(RouterDaemon):
    NAME = "dhcprelay"
    KILL_PATTERNS = ("dnsmasq",)

    def __init__(self, node, dhcp_server_ip, dhcp_server_mask, intf, **kwargs):
        self.node = node
        self.dhcp_server_ip = dhcp_server_ip
        self.dhcp_server_mask = dhcp_server_mask
        self.intf = intf
        self.pid_file = tempfile.mktemp(dir='/tmp')
        super().__init__(node, **kwargs)
    
    '''
    def build(self) -> ConfigDict:
        cfg = super().build()
        cfg.pid_file = self.pid_file
        cfg.dhcp_server_ip = self.dhcp_server_ip
        cfg.dhcp_server_mask = self.dhcp_server_mask
        cfg.intf = self.intf
        return cfg
    '''
    
    @property
    def startup_line(self):
        return f"dnsmasq --dhcp-relay=172.16.10.3,192.168.10.2"
    
    @property
    def dry_run(self):
        return ""
    
    @property
    def cfg_filenames(self):
        return [self._file(suffix=f"%s.cfg" % self.intf)]
    
    def set_defaults(self, defaults):
        pass

    def kill(self):
        pid_str = self.node.cmd(f"cat {self.pid_file}").strip()
        self.node.cmd(f"kill -9 {pid_str}")

    def cleanup(self):
        self.kill()
