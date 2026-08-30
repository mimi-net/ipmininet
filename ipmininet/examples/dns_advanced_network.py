"""This file contains topology with a full DNS hierarchy"""

from ipmininet.host.config import Named
from ipmininet.iptopo import IPTopo


class DNSAdvancedNetwork(IPTopo):
    """This network runs a named daemon on both master and slave hosts.
    The zone 'mydomain.org' is configured on both named daemons.
    org_dns is the name server of 'org' domain while root_dns is a root
    name server."""

    def build(self, *args, **kwargs):
        """
                             +--------+
                             | server |
                             +---+----+
                                 |
                              +--+-+
                        +-----+ r1 +-----+
                        |     +----+     |
        +-------+     +-+--+          +--+-+     +--------+
        | slave +-----+ r2 +----------+ r3 +-----+ master |
        +-------+     +-+--+          +--+-+     +--------+
                        |                |
        +--------+    +-+--+          +--+-+     +---------+
        | orgdns +----+ r4 +----------+ r5 +-----+ rootdns |
        +--------+    +----+          +----+     +---------+
        """
        # Add routers

        r1, r2, r3, r4, r5 = self.addRouters("r1", "r2", "r3", "r4", "r5")
        self.addLinks((r1, r2), (r1, r3), (r3, r2), (r2, r4), (r3, r5), (r4, r5))

        # Add hosts
        server = self.addHost("server")
        self.addLink(r1, server)

        master = self.addHost("master")
        master.addDaemon(Named)
        self.addLink(r3, master)

        slave = self.addHost("slave")
        slave.addDaemon(Named)
        self.addLink(r2, slave)

        orgdns = self.addHost("orgdns")
        orgdns.addDaemon(Named)
        self.addLink(r4, orgdns)

        rootdns = self.addHost("rootdns")
        rootdns.addDaemon(Named)
        self.addLink(r5, rootdns)

        # Declare the mydomain.org, org and root DNS zones.
        # The orgdns server will have the NS records for 'mydomain.org' zone
        # and the rootdns server will have the NS records for the 'org' zone.
        self.addDNSZone(
            name="mydomain.org", dns_master=master, dns_slaves=[slave], nodes=[server]
        )
        self.addDNSZone(name="org", dns_master=orgdns)
        self.addDNSZone(name="", dns_master=rootdns)

        super().build(*args, **kwargs)
