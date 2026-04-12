from .base import RouterDaemon
import tempfile

class DHCPHelper(RouterDaemon):
    NAME = "dhcp-helper"
    KILL_PATTERNS = ("dhcp-helper",)

    def __init__(self, node, dhcp_server_ip, dhcp_server_mask, intf, **kwargs):
        self.node = node
        self.dhcp_server_ip = dhcp_server_ip
        self.dhcp_server_mask = dhcp_server_mask
        self.intf = intf
        self.pid_file = tempfile.mktemp(dir='/tmp')
        super().__init__(node, **kwargs)
    
    @property
    def startup_line(self):
        return f"{self.NAME} -s {self.dhcp_server_ip} -i {self.intf} -r {self.pid_file}"
    
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
