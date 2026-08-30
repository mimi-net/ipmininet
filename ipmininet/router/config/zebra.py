import os
import socket
from abc import ABC, abstractmethod
from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import Union

from .base import RouterDaemon
from .utils import ConfigDict

#  Route Map actions
DENY = "deny"
PERMIT = "permit"


def get_family(prefix: str | IPv4Network | IPv6Network) -> str | None:
    pfx = ip_network(prefix) if isinstance(prefix, str) else prefix
    if pfx.version == 4:
        return "ipv4"
    if pfx.version == 6:
        return "ipv6"

    return None


class QuaggaDaemon(RouterDaemon):
    """The base class for all Quagga-derived daemons"""

    # Additional parameters to pass when starting the daemon
    STARTUP_LINE_EXTRA = ""

    @property
    def startup_line(self):
        return "{name} -f {cfg} -i {pid} -z {api} -u root {extra}".format(
            name=self.NAME,
            cfg=self.cfg_filename,
            pid=self._file("pid"),
            api=self.zebra_socket,
            extra=self.STARTUP_LINE_EXTRA,
        )

    @property
    def zebra_socket(self):
        """Return the path towards the zebra API socket for the given node"""
        return os.path.join(
            self._node.cwd, "{}_{}.api".format("quagga", self._node.name)
        )

    def build(self):
        cfg = super().build()
        cfg.debug = self.options.debug
        return cfg

    def set_defaults(self, defaults):
        """:param debug: the set of debug events that should be logged"""
        defaults.debug = ()
        super().set_defaults(defaults)

    @property
    def dry_run(self):
        return f"{self.NAME} -Cf {self.cfg_filename} -u root"


class Zebra(QuaggaDaemon):
    NAME = "zebra"
    PRIO = 0
    STARTUP_LINE_EXTRA = ""
    KILL_PATTERNS = (NAME,)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.files.append(self.zebra_socket)

    def build(self):
        cfg = super().build()
        # Update with preset defaults
        cfg.update(self.options)
        # Track interfaces
        cfg.interfaces = (
            ConfigDict(name=itf.name, description=itf.describe)
            for itf in self._node.intfList()
        )
        return cfg

    def set_defaults(self, defaults):
        """:param debug: the set of debug events that should be logged
        :param access_lists: The set of AccessList to create, independently
                             from the ones already included by route_maps
        :param route_maps: The set of RouteMap to create"""
        defaults.access_lists = []
        defaults.route_maps = []
        super().set_defaults(defaults)

    def has_started(self, node_exec=None):
        # We override this such that we wait until we have the API socket
        # and until wa can connect to it
        return os.path.exists(self.zebra_socket) and self.listening()

    def listening(self) -> bool:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self.zebra_socket)
        except OSError:
            return False
        else:
            sock.close()
            return True


class CommunityList:
    """A zebra community-list entry"""

    # Number of CmL
    count = 0

    def __init__(
        self, name: str | None = None, action=PERMIT, community: int | str = 0
    ):
        """

        :param name:
        :param action:
        :param community:
        """
        CommunityList.count += 1
        self.name = name or f"cml{CommunityList.count}"
        self.action = action
        self.community = community
        self.family = "community"

    def __eq__(self, other):
        return self.name == other.name and self.action == other.action

    __hash__ = None


class Entry:
    def __init__(
        self, prefix: str | IPv4Network | IPv6Network, action=PERMIT, family=None
    ):
        """
        :param prefix: The ip_interface prefix for that ACL entry
        :param action: Whether that prefix belongs to the ACL (PERMIT)
                       or not (DENY)
        """

        if isinstance(prefix, str):
            if prefix == "any":
                assert family is not None
                _prefix = prefix
            else:
                _prefix = ip_network(prefix)
                if family is not None:
                    assert get_family(_prefix) == family, (
                        f"prefix family {get_family(_prefix)} != family ({family})"
                    )
        else:
            _prefix = prefix

        self.prefix = _prefix
        self.action = action
        self.family = family or get_family(self.prefix)

    @property
    def zebra_family(self):
        if self.family == "ipv4":
            return "ip"
        return "ipv6"


class AccessListEntry(Entry):
    """A zebra access-list entry"""

    def __init__(
        self, prefix: str | IPv4Network | IPv6Network, action=PERMIT, family=None
    ):
        super().__init__(prefix, action, family)


class PrefixListEntry(Entry):
    def __init__(
        self,
        prefix: str | IPv4Network | IPv6Network,
        action=PERMIT,
        family=None,
        le=None,
        ge=None,
    ):
        type_mask = {"ipv4": 32, "ipv6": 128}

        super().__init__(prefix, action, family)

        # The 'any' prefix-list entry has a special action
        if self.prefix == "any":
            self.prefix = (
                ip_network("0.0.0.0/0") if self.family == "ipv4" else ip_network("::/0")
            )
            self.le = type_mask[self.family]
            return

        if le is not None:
            assert 0 <= le <= type_mask[self.family], (
                f"assertion 0 <= le ({le}) <= {type_mask[self.family]} failed"
            )
        if ge is not None:
            assert 0 <= ge <= type_mask[self.family], (
                f"assertion 0 <= ge ({ge}) <= {type_mask[self.family]} failed"
            )
        if le is not None and ge is not None:
            assert le >= ge, (
                f"assertion le ({le}) >= ge ({ge}) failed! le must be lower than ge"
            )

        self.le = le
        self.ge = ge


class ZebraList(ABC):
    count = 0

    @property
    @abstractmethod
    def prefix_name(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def Entry(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def zebra_family(self):
        raise NotImplementedError

    def __init__(
        self,
        family,
        entries: Sequence[Union["ZebraList.Entry", str, IPv4Network, IPv6Network]] = (),
        name=None,
    ):
        """Setup a new zebra-list.

        :param name: The name of the acl, which will default to acl## where ##
                     is the instance number
        :param entries: A sequence of ZebraListEntry instance,
                        or of ip_interface which describes which prefixes
                        are composing the list
        """

        assert family in {"ipv4", "ipv6"}, (
            f"PrefixList unknown {family} type. type must be either ipv4 or ipv6"
        )

        ZebraList.count += 1

        self.name = name or f"{self.prefix_name}{ZebraList.count}"
        self.entries = []
        for e in entries:
            if isinstance(e, self.Entry):
                assert e.family == family, "The prefix entry must be of the same type"
                self.entries.append(e)
            elif isinstance(e, str) and e == "any":
                self.entries.append(self.Entry(prefix=e, family=family))
            elif isinstance(e, (IPv4Network, IPv6Network, str)):
                self.entries.append(self.Entry(prefix=e))
            else:
                raise ValueError(
                    f'"{e}" is not a valid prefix entry for the {family} family'
                )

        self.family = family

    def __eq__(self, other):
        return self.name == other.name

    __hash__ = None


class PrefixList(ZebraList):
    @property
    def zebra_family(self):
        if self.family == "ipv4":
            return "ip"
        return "ipv6"

    @property
    def prefix_name(self):
        return "pfxl"

    @property
    def Entry(self):
        return PrefixListEntry


class AccessList(ZebraList):
    """A zebra access-list class. It contains a set of AccessListEntry,
    which describes all prefix belonging or not to this ACL"""

    @property
    def zebra_family(self):
        if self.family == "ipv4":
            return ""
        return "ipv6 "

    @property
    def prefix_name(self):
        return "acl"

    @property
    def Entry(self):
        return AccessListEntry


class RouteMapMatchCond:
    """
    A class representing a RouteMap matching condition
    """

    def __init__(self, cond_type: str, condition, family: str | None = None):
        """
        :param condition: Can be an ip address, the id of an access
                          or prefix list
        :param cond_type: The type of condition access list, prefix list,
                          peer ...
        :param family: if cond_type is an access-list or a prefix-list,
                       specify the family of the list (either ipv4 or ipv6)
        """
        if family:
            assert family in {"ipv4", "ipv6", "community"}, (
                f"Unrecognized family type ({family})"
            )
        self.condition = condition
        self.cond_type = cond_type
        self.family = family

    @property
    def zebra_family(self):
        if self.family == "ipv4":
            return "ip"
        if self.family == "ipv6":
            return "ipv6"
        if self.family == "community":
            return "community"

        raise ValueError(f"Unsupported family; {self.family}")

    def __eq__(self, other):
        return (
            self.condition == other.condition
            and self.cond_type == other.cond_type
            and self.family == other.family
        )

    __hash__ = None


class RouteMapSetAction:
    """
    A class representing a RouteMap set action
    """

    def __init__(self, action_type: str, value):
        """
        :param action_type: Type of value to me modified
        :param value: Value to be modified
        """
        self.action_type = action_type
        self.value = value

    def __eq__(self, other):
        return self.action_type == other.action_type and self.value == other.value

    __hash__ = None


class RouteMapEntry:
    def __init__(
        self,
        family: str,
        match_policy=PERMIT,
        match_cond: Sequence[RouteMapMatchCond | tuple] = (),
        set_actions: Sequence[RouteMapSetAction | tuple] = (),
        call_action: str | None = None,
        exit_policy: str | None = None,
    ):
        """
        :param match_policy: Deny or permit the actions if the route match
                             the condition
        :param match_cond: Specify one or more conditions which must be matched
                           if the entry is to be considered further
        :param set_actions: Specify one or more actions to do
                            if there is a match
        :param call_action: call to an other route map
        :param exit_policy: An entry may, optionally specify an alternative exit
                            policy if the entry matched or of (action, [acl,
                            acl, ...]) tuples that will compose the route map
        """

        assert family in {"ipv4", "ipv6", "community"}, "Unrecognized family"

        self.family = family

        self.match_policy = match_policy
        self.match_cond = [
            e
            if isinstance(e, RouteMapMatchCond)
            else RouteMapMatchCond(cond_type=e[0], condition=e[1], family=family)
            for e in match_cond
        ]
        self.set_actions = [
            e
            if isinstance(e, RouteMapSetAction)
            else RouteMapSetAction(action_type=e[0], value=e[1])
            for e in set_actions
        ]
        self.call_action = call_action
        self.exit_policy = exit_policy

    def append_match_cond(self, match_conditions):
        """

        :return:
        """
        for match_condition in match_conditions:
            if match_condition not in self.match_cond:
                self.match_cond.append(match_condition)

    def append_set_action(self, set_actions):
        """

        :param set_actions:
        :return:
        """
        for set_action in set_actions:
            if set_action not in self.set_actions:
                self.set_actions.append(set_action)

    def update(self, rm_entry: "RouteMapEntry"):
        if not self.can_merge(rm_entry):
            raise ValueError("Attempting to merge incompatible RouteMap Entries")

        self.append_set_action(rm_entry.set_actions)
        self.append_match_cond(rm_entry.match_cond)

    def can_merge(self, rm_entry):
        return (
            self.family == rm_entry.family
            and self.match_policy == rm_entry.match_policy
            and self.call_action == rm_entry.call_action
            and self.exit_policy == rm_entry.exit_policy
        )


class RouteMap:
    """A class representing a set of route maps applied to a given protocol"""

    # Number of route maps
    count = 0
    DEFAULT_POLICY = 65535

    def __init__(
        self,
        family: str,
        name: str | None = None,
        proto: set[str] = (),
        neighbor: str | None = None,
        direction: str = "in",
    ):
        """
        :param name: The name of the route-map, defaulting to rm##
        :param proto: The set of protocols to which this route-map applies
        :param neighbor: List of peers this route map is applied to
        :param direction: Direction of the routemap(in, out, both)
        """
        RouteMap.count += 1

        assert family in {"ipv4", "ipv6", "community"}, "Unrecognized family"

        self.name = name or f"rm{RouteMap.count}"

        self.entries = {}  # type: Dict[int, 'RouteMapEntry']

        self.neighbor = neighbor
        self.direction = direction
        self.proto = proto
        self.family = family
        # Highest route-map entry order added so far
        self._hi_order = 0

        # used to indicate that the current route map has a default
        # entry that accepts all routes as default policy.
        # By default, RMs deny at the very end. Yet, the user can
        # override this default behavior if is inserts an entry in the
        # DEFAULT_POLICY order of the route map
        self._default_policy_set = False

    def _inc_order(self):
        self._hi_order += 10
        assert self._hi_order < self.DEFAULT_POLICY, (
            f"Maximum route-map order exceeded (> {self.DEFAULT_POLICY})"
        )

    def default_policy_set(self):
        return self._default_policy_set

    def entry(self, rm_entry: "RouteMapEntry", order: int | None = None):
        if order is None:
            self._inc_order()
            order = self._hi_order
        elif order == self.DEFAULT_POLICY:
            self._default_policy_set = True
        else:
            self._hi_order = max(order, self._hi_order)

        if order not in self.entries:
            self.entries[order] = rm_entry
        else:
            self.entries[order].update(rm_entry)

    def remove_entry(self, order: int):
        if order in self.entries:
            self.entries.pop(order, None)

    def remove_default_policy(self):
        if self.DEFAULT_POLICY in self.entries:
            self.entries.pop(self.DEFAULT_POLICY, None)

    def update(self, rm: "RouteMap"):
        if self != rm:
            raise ValueError("Attempting to update incompatible RouteMaps")

        for order in rm.entries:
            self.entry(rm.entries[order], order)

    def find_entry_by_match_condition(self, condition: Sequence["RouteMapMatchCond"]):
        for entry in self.entries:
            if self.entries[entry].match_cond == condition:
                return self.entries[entry]
        return None

    def __len__(self):
        return len(self.entries)

    def __eq__(self, other):
        return (
            self.name == other.name
            and self.direction == other.direction
            and self.family == other.family
            and self.proto == other.proto
            and self.neighbor == other.neighbor
        )

    __hash__ = None

    @property
    def describe(self):
        """Return the zebra description of this route map and apply it to the
        relevant protocols"""
        return "route-map"
