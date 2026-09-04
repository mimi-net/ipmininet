from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Optional, Union

from .bgp import AF_INET, AF_INET6, BGP_DEFAULT_PORT, AbstractBGP
from .utils import ConfigDict


class NotHexRepresentableError(ValueError):
    """Raised when an ExaBGP list is used for an hexadecimal representation."""

    def __init__(self):
        super().__init__("Must not be used for an Hexadecimal representation")


class UnknownBGPAttributeError(ValueError):
    """Raised when a BGP attribute type is not known to ExaBGP."""

    def __init__(self, attr_type):
        super().__init__(f"{attr_type!s} is not a known attribute")


class Representable(ABC):
    """
    String representation for ExaBGP configuration
    Each sub-part of any ExaBGP route must be representable and must override
    the default __str__ function
    """

    @abstractmethod
    def __str__(self):
        raise NotImplementedError


class HexRepresentable(Representable):
    """
    Representation of an hexadecimal value for ExaBGP.

    In the case of an unknown ExaBGP attribute, the value cannot be interpreted
    by ExaBGP. Then it is needed to use its hexadecimal representation. This Abstract
    class must be implemented by any "unrepresentable" BGP attribute.


    Example:
        Imagine you want to represent a new 64-bits attribute. All you have to do
        is to extend the HexRepresentable class and then create a new BGPAttribute
        as usual. The following code shows an example:

        .. code-block:: python

            class LongAttr(HexRepresentable):
                _uint64_max = 18446744073709551615

                def __init__(self, my_long):
                    assert 0 <= my_long < LongAttr._uint64_max
                    self.val = my_long

                def hex_repr(self):
                    return '{0:#0{1}X}'.format(self.val, 18)

                def __str__(self):
                    return self.hex_repr()

            # your new attribute
            my_new_attr = BGPAttribute(42, LongAttr(2658), BGPAttributesFlags(1,1,0,0))

    """

    @abstractmethod
    def hex_repr(self) -> str:
        """
        :return: The Hexadecimal representation of an BGP attribute value
        """
        raise NotImplementedError

    @abstractmethod
    def __str__(self):
        raise NotImplementedError


class ExaList(HexRepresentable):
    """
    List that can be represented in a form of string for BGP routes attributes.
    This class is only used for string representable attribute. That is attribute
    already defined and known from ExaBGP. If the list is used for an hexadecimal
    attribute, it raises a ValueError
    """

    def hex_repr(self) -> str:
        raise NotHexRepresentableError()

    @property
    def val(self):
        return self.lst

    def __init__(self, lst: list[int | str]):
        assert isinstance(lst, list), f"{type(lst)} is not a list"
        self.lst = lst

    def __str__(self) -> str:
        return "[ {} ]".format(" ".join([str(it) for it in self.lst]))


class BGPAttributeFlags(HexRepresentable):
    """
    Represents the flags part of a BGP attribute (RFC 4271 section 4.3)
    The flags are an 8-bits integer value in the form `O T P E 0 0 0 0`.
    When :

    * bit `O` is set to 0: the attribute is Well-Known. If 1, it is optional
    * bit `T` is set to 0: the attribute is not Transitive. If 1, it is
      transitive
    * bit `P` is set to 0: the attribute is complete; If 1, partial
    * bit `E` is set to 0: the attribute is of length < 256 bits. If set to
      1: 256 <= length < 2^{16}

    The last 4 bits are unused

    This class is notably used to define new attributes unknown from ExaBGP
    or change the flags of an already known attribute. For example, the MED
    value is not transitive. To make it transitive, put the transitive bit
    to 1.
    """

    @staticmethod
    def to_hex_flags(a, b, c, d):
        return (((a << 3) & 8) | ((b << 2) & 4) | ((c << 1) & 2) | (d & 1)) << 4

    def __init__(self, optional, transitive, partial, extended):
        allowed_vals = {0, 1}
        assert optional in allowed_vals
        assert transitive in allowed_vals
        assert partial in allowed_vals
        assert extended in allowed_vals

        self.optional = optional
        self.transitive = transitive
        self.partial = partial
        self.extended = extended

        self._hex = self.to_hex_flags(
            self.optional, self.transitive, self.partial, self.extended
        )

    def __str__(self):
        return self.hex_repr()

    def hex_repr(self):
        return f"0X{self._hex:X}"

    def __repr__(self):
        return (
            "BGPAttributeFlags("
            f"opt={self.optional}, transitive={self.transitive}, "
            f"partial={self.partial}, ext={self.extended}, "
            f"_hex={hex(self._hex)} ({bin(self._hex)})"
            ")"
        )


class BGPAttribute(Representable):
    """
    A BGP attribute as represented in ExaBGP. Either the Attribute is known
    from ExaBGP and so the class uses its string representation. Or the
    attribute is not known, then the class uses its hexadecimal
    representation. The latter representation is also useful to modify flags
    of already known attributes. For example the MED value is a known
    attribute which is not transitive. By passing a BGPAttributeFlags object
    to the constructor, it is now possible to make it transitive with
    BGPAttributeFlags(1, 1, 0, 0) (both optional and transitive bits are set
    to 1)
    """

    @property
    def _known_attr(self):
        return {
            "next-hop",
            "origin",
            "med",
            "as-path",
            "local-preference",
            "atomic-aggregate",
            "aggregator",
            "originator-id",
            "cluster-list",
            "community",
            "large-community",
            "extended-community",
            "name",
            "aigp",
        }

    def hex_repr(self) -> str:
        return (
            f"attribute [ {hex(self.type)} {self.flags.hex_repr()} "
            f"{self.val.hex_repr()} ]"
        )

    def str_repr(self) -> str:
        return f"{self.type!s} {self.val!s}"

    def __init__(
        self,
        attr_type: str | int,
        val: Union["HexRepresentable", int, str],
        flags: Optional["BGPAttributeFlags"] = None,
    ):
        """
        Constructs an Attribute known from ExaBGP or an unknown attribute if
        flags is not None. It raises a ValueError if the initialisation of
        BGPAttribute fails. Either because type_attr is not an int (for an
        unknown attribute), or the string of type_attr is not recognised by
        ExaBGP (for a known attribute)

        :param attr_type: In the case of a Known attribute, attr_type is a
                          valid string recognised by ExaBGP. In the case of
                          an unknown attribute, attr_type is the integer ID
                          of the attribute. Valid strings are:
                          'next-hop', 'origin', 'med', 'as-path',
                          'local-preference', 'atomic-aggregate',
                          'aggregator', 'originator-id', 'cluster-list',
                          'community', 'large-community', 'extended-community',
                          'name', 'aigp'
        :param val: The actual value of the attribute
        :param flags: If None, the BGPAttribute object contains a known
                      attribute from ExaBGP. In this case, the representation
                      of this attribute will be a string. If flags is an
                      instance of BGPAttribute, the hexadecimal representation
                      will be used
        """

        if flags is None:
            if str(attr_type) not in self._known_attr:
                raise UnknownBGPAttributeError(attr_type)
        else:
            assert isinstance(val, HexRepresentable), (
                "If flags are set, val must be of type 'HexRepresentable'"
            )

        self.flags = flags
        self.type = attr_type
        self.val = val

    def __str__(self):
        if self.flags is None:
            return self.str_repr()
        return self.hex_repr()

    def __repr__(self) -> str:
        return "BGPAttribute(attr_type={attr_type}, val={val}{flags})".format(
            attr_type=self.type,
            val=self.val,
            flags=" flags={val}".format(
                val=self.flags.hex_repr() if self.flags is not None else ""
            ),
        )


class BGPRoute(Representable):
    """
    A BGP route as represented in ExaBGP
    """

    def __init__(self, network: "Representable", attributes: Sequence["BGPAttribute"]):
        self.IPNetwork = network
        self.attributes = attributes

    def __str__(self):
        route = f"unicast {self.IPNetwork!s}"
        for attr in self.attributes:
            route += f" {attr!s}"

        return route

    def __repr__(self):
        return str(self)

    def __getitem__(self, item):
        if item in ("network", "IPnetwork"):
            return self.IPNetwork

        for attr in self.attributes:
            if isinstance(attr.type, str) and attr.type == item:
                return attr
        return None


class ExaBGPDaemon(AbstractBGP):
    NAME = "exabgp"
    KILL_PATTERNS = (NAME,)

    def __init__(self, node, port=BGP_DEFAULT_PORT, *args, **kwargs):
        super().__init__(*args, node=node, **kwargs)
        self.port = port

    def build(self):
        cfg = super().build()
        cfg.asn = self._node.asn
        cfg.port = self.port
        cfg.neighbors = self._build_neighbors()
        cfg.address_families = self._address_families(
            self.options.address_families, cfg.neighbors
        )
        self.options.base_env.update(self.options.env)
        cfg.env = self.options.base_env
        cfg.passive = self.options.passive

        return cfg

    @property
    def STARTUP_LINE_EXTRA(self):
        return ""

    @property
    def env_filename(self):
        return self._file("env")

    @property
    def cfg_filenames(self):
        return [*super().cfg_filenames, self.env_filename]

    @property
    def template_filenames(self):
        return [*super().template_filenames, f"{self.NAME}_env.mako"]

    @property
    def startup_line(self) -> str:
        # ExaBGP 5.x moved to a subcommand CLI: the env file is passed with
        # --env-file and the config is the trailing argument.
        return f"{self.NAME} --env-file {self.env_filename} server {self.cfg_filename}"

    @property
    def dry_run(self) -> str:
        return (
            f"{self.NAME} --env-file {self.env_filename} validate {self.cfg_filename}"
        )

    def set_defaults(self, defaults):
        """
        Modifies the default configuration of this ExaBGP daemon

        :param env: a dictionary of all the environment variables that
                    configure ExaBGP. Type "exabgp --help" to take a look on
                    every environment variable. env.tcp.delay is set by
                    default to 2 min as FRRouting BGPD daemon seems to reject
                    routes if ExaBGP injects routes to early. Each environment
                    variable is either a string or an int.

                    The following environment variable are set :

                    * daemon.user = 'root'
                    * daemon.drop = 'false'
                    * daemon.daemonize = 'false'
                    * daemon.pid = <default configuration folder
                      /tmp/exabgp_<node>.pid>

                    * log.level = 'CRITICAL'
                    * log.destination = <default configuration folder
                      /tmp/exabgp_<node>.log>
                    * log.reactor = 'false'
                    * log.processes = false'
                    * log.network = 'false'

                    * api.cli = 'false'

                    * tcp.delay = 2 # waits at most 2 minutes
        :param address_families: the routes to inject for both IPv4 and IPv6
                                 unicast AFI.
        :param passive: Tells to ExaBGP to not send active BGP Open messages.
                        The daemon waits until the remote peer sends first
                        the Open message to start the BGP session. Its default
                        value is set to True.
        """
        defaults.base_env = ConfigDict(
            daemon=ConfigDict(
                user="root", drop="false", daemonize="false", pid=self._file("pid")
            ),
            log=ConfigDict(
                level="CRITICAL",
                destination=self._file("log"),
                reactor="false",
                processes="false",
                network="false",
            ),
            api=ConfigDict(
                cli="false",
            ),
            tcp=ConfigDict(
                delay=2  # wait at most 2 minutes before sending UPDATE, the other peer
                # may not be ready yet. FRRouting do not accept incoming routes
                # if ExaBGP sends directly its routes. Debugging information
                # says that routes are denied due to a "deny" action from a
                # route map
                # (rcvd UPDATE about 8.8.8.0/24 -- DENIED due to route-map;)
                # However, if the daemon waits a little bit, routes are all
                # accepted...
            ),
        )
        defaults.address_families = [AF_INET(), AF_INET6()]
        defaults.passive = True
        defaults.env = ConfigDict()
        super().set_defaults(defaults)
