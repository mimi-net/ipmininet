"""This modules contains various utilities to streamline config generation"""

from ipaddress import IPv4Address, IPv6Address, ip_interface

from ipmininet.utils import IP_V6, L3Router


def is_l3router_interface(itf) -> bool:
    """Return whether an interface is active for an IGP daemon (i.e. whether
    it faces another L3 router)."""
    if itf.broadcast_domain is None:
        return False
    return any(L3Router.is_l3router_intf(i) for i in itf.broadcast_domain if i != itf)


def interface_props(interfaces, props):
    """Build the per-interface ConfigDict list shared by the IGP daemons.

    Each entry holds the interface description, name and activeness, decorated
    with the daemon-specific keys returned by ``props(intf)``.
    """
    return [
        ConfigDict(
            description=i.describe,
            name=i.name,
            # Is the interface between two routers?
            active=is_l3router_interface(i),
            **props(i),
        )
        for i in interfaces
    ]


class ConfigDict(dict):
    """A dictionary whose attributes are its keys.
    Be careful if subclassing, as attributes defined by doing
    assignments such as self.xx = yy in __init__ will be shadowed!"""

    def __init__(self, **kwargs):
        super().__init__()
        for key, val in kwargs.items():
            self[key] = val

    def __getattr__(self, item):
        # so that self.item == self[item]
        try:
            # But preserve i.e. methods
            return super().__getattr__(item)
        except AttributeError:
            try:
                return self[item]
            except KeyError:
                return None

    def __setattr__(self, key, value):
        # so that self.key = value <==> self[key] = key
        self[key] = value


def ip_statement(ip: int | str | IPv6Address | IPv4Address):
    """Return the zebra ip statement for a given ip prefix

    :type ip: ip_interface, ip_network, ip_address, int, str"""
    if not isinstance(ip, int):
        ip = ip_interface(str(ip)).version
    return "ipv6" if ip == IP_V6 else "ip"
