"""Scenarios building ExaBGP route attributes the way an experiment would.

These tests compose BGP routes from attributes and verify their ExaBGP string
and hexadecimal renderings, mirroring what the exabgp daemon config generation
produces (known attributes, unknown attributes described in hex and flag
overrides). They never require root privileges and never start a network.
"""

from ipaddress import ip_network

import pytest

from ipmininet.router.config.exabgp import (
    BGPAttribute,
    BGPAttributeFlags,
    BGPRoute,
    ExaList,
    HexRepresentable,
    NotHexRepresentableError,
    UnknownBGPAttributeError,
)

_MAX_UINT16 = 65535
_MED_VALUE = 42
_UNKNOWN_ATTR_ID = 42
_HEX_VALUE = 2658
_ASN_FIRST = 1
_ASN_SECOND = 56
_ASN_THIRD = 97
_COMMUNITY_FIRST = "1:666"
_COMMUNITY_SECOND = "468:45687"
_KNOWN_MED = "med"


class _Uint16HexAttr(HexRepresentable):
    """A user-defined attribute stored as an unsigned 16-bits value."""

    def __init__(self, value):
        assert 0 <= value <= _MAX_UINT16
        self.value = value

    def hex_repr(self):
        return f"0X{self.value:04X}"

    def __str__(self):
        return self.hex_repr()


def test_exalist_renders_known_values():
    as_path = ExaList([_ASN_FIRST, _ASN_SECOND, _ASN_THIRD])
    assert as_path.val == [_ASN_FIRST, _ASN_SECOND, _ASN_THIRD]
    assert str(as_path) == "[ 1 56 97 ]"

    communities = ExaList([_COMMUNITY_FIRST, _COMMUNITY_SECOND])
    assert str(communities) == "[ 1:666 468:45687 ]"


def test_exalist_rejects_non_list():
    with pytest.raises(AssertionError):
        ExaList(_COMMUNITY_FIRST)


def test_exalist_cannot_be_rendered_as_hex():
    with pytest.raises(NotHexRepresentableError):
        ExaList([_ASN_FIRST, _ASN_SECOND]).hex_repr()


def test_known_attribute_string_rendering():
    med = BGPAttribute(_KNOWN_MED, _MED_VALUE)
    assert med.flags is None
    assert str(med) == "med 42"

    origin = BGPAttribute("origin", "igp")
    assert str(origin) == "origin igp"

    as_path = BGPAttribute("as-path", ExaList([_ASN_FIRST, _ASN_SECOND]))
    assert str(as_path) == "as-path [ 1 56 ]"


def test_unknown_attribute_name_raises():
    with pytest.raises(UnknownBGPAttributeError, match="not a known attribute"):
        BGPAttribute("not-an-attribute", _MED_VALUE)


def test_unknown_attribute_hex_rendering():
    flags = BGPAttributeFlags(optional=1, transitive=1, partial=0, extended=0)
    attr = BGPAttribute(_UNKNOWN_ATTR_ID, _Uint16HexAttr(_HEX_VALUE), flags)
    assert str(attr) == "attribute [ 0x2a 0XC0 0X0A62 ]"
    assert repr(attr) == "BGPAttribute(attr_type=42, val=0X0A62 flags=0XC0)"


def test_hex_attribute_requires_hex_value():
    with pytest.raises(AssertionError):
        BGPAttribute(_UNKNOWN_ATTR_ID, _HEX_VALUE, BGPAttributeFlags(1, 1, 0, 0))


def test_attribute_flags_rendering():
    flags = BGPAttributeFlags(optional=1, transitive=1, partial=1, extended=1)
    assert flags.hex_repr() == "0XF0"
    assert str(flags) == "0XF0"
    assert "opt=1" in repr(flags)

    none = BGPAttributeFlags(0, 0, 0, 0)
    assert str(none) == "0X0"


def test_attribute_flags_reject_invalid_bits():
    with pytest.raises(AssertionError):
        BGPAttributeFlags(2, 0, 0, 0)
    with pytest.raises(AssertionError):
        BGPAttributeFlags(0, -1, 0, 0)


def test_bgp_route_string_rendering():
    route = BGPRoute(
        ip_network("8.8.8.0/24"),
        [BGPAttribute("next-hop", "self"), BGPAttribute(_KNOWN_MED, _MED_VALUE)],
    )
    assert str(route) == "unicast 8.8.8.0/24 next-hop self med 42"


def test_bgp_route_attribute_lookup():
    route = BGPRoute(
        ip_network("8.8.8.0/24"),
        [
            BGPAttribute(_KNOWN_MED, _MED_VALUE),
            BGPAttribute("origin", "igp"),
        ],
    )
    assert route["network"] == ip_network("8.8.8.0/24")
    assert route["IPnetwork"] == ip_network("8.8.8.0/24")
    assert route["med"].val == _MED_VALUE
    assert route["origin"].val == "igp"
    assert route["local-preference"] is None
