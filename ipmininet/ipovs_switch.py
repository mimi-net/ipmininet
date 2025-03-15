from mininet.node import OVSSwitch
from mininet.log import info, error, warn, debug


class IPOVSSwitch(OVSSwitch):
    def __init__(self, name: str, stp=False, hub=False, cwd='/tmp', rstp=False,
                 failMode="standalone", batch=False, priority=None, **params):
        self.cwd = cwd
        self.priority = priority
        self.rstp = rstp and not hub
        stp = stp and not hub
        OVSSwitch.__init__(self, failMode=failMode, name=name, stp=stp, batch=False, **params)

    def start(self, controllers):
        """Start up a new OVS OpenFlow switch using ovs-vsctl"""
        if self.inNamespace:
            raise Exception('OVS kernel switch does not work in a namespace')

        self.cmd('ifconfig', self, 'down')
        int(self.dpid, 16)  # DPID must be a hex string
        # Command to add interfaces
        intfs = ''.join(' -- add-port %s %s' % (self, intf) + self.intfOpts(intf)
                        for intf in self.intfList() if self.ports[intf] and not intf.IP())
        # Command to create controller entries
        clist = [(self.name + c.name, '%s:%s:%d' % (c.protocol, c.IP(), c.port)) for c in controllers]
        if self.listenPort:
            clist.append((self.name + '-listen', 'ptcp:%s' % self.listenPort))
        ccmd = '-- --id=@%s create Controller target=\\"%s\\"'
        if self.reconnectms:
            ccmd += ' max_backoff=%d' % self.reconnectms
        cargs = ' '.join(ccmd % (name, target) for name, target in clist)
        # Try to delete any existing bridges with the same name
        if not self.isOldOVS():
            cargs += ' --if-exists del-br %s' % self
        # One ovs-vsctl command to rule them all!
        self.vsctl(cargs)
        self.vsctl(' add-br %s' % self)
        self.vsctl(' set bridge %s' % self + self.bridgeOpts())
        self.vsctl(intfs)
        # Start the captures on this switch
        for capture in self.params.get("captures", []):
            capture.start(node=self)
        for intf in self.intfList():
            for capture in intf.params.get("captures", []):
                capture.start(intf=intf)
        self.cmd('ifconfig', self, 'up')

    def bridgeOpts(self):
        """Return OVS bridge options"""
        opts = (' other_config:enable-vlan-filtering=true' +
                ' other_config:datapath-id=%s' % self.dpid +
                 ' fail_mode=%s' % self.failMode)
        if self.priority is not None:
            opts += (' other_config:stp-priority=%s' % self.priority +
                    ' other_config:rstp-priority=%s' % self.priority)
        if not self.inband:
            opts += ' other_config:disable-in-band=true'
        if self.datapath == 'user':
            opts += ' datapath_type=netdev'
        if self.protocols and not self.isOldOVS():
            opts += ' protocols=%s' % self.protocols
        if self.rstp and self.failMode == 'standalone':
            opts += ' rstp_enable=true'
        elif self.stp and self.failMode == 'standalone':
            opts += ' stp_enable=true'
        opts += ' other_config:dp-desc=%s' % self.name
        return opts

    def stop(self, deleteIntfs=True):
        # Stop the captures on this switch
        for capture in self.params.get("captures", []):
            capture.stop(node=self)
        for intf in self.intfList():
            for capture in intf.params.get("captures", []):
                capture.stop(intf=intf)
        OVSSwitch.stop(self, deleteIntfs)
