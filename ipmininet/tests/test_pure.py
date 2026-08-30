"""Rootless unit tests for pure logic.

These tests never require root privileges and never start a network, so they
can be run locally by any user (see scripts/run-tests-local.sh) and will run
in a rootless CI job. Tests that require root are marked with `require_root`
in the other test modules.
"""

import time
from ipaddress import IPv4Network, IPv6Network, ip_network

import pytest

from ipmininet.link import _parse_addresses
from ipmininet.router.config.utils import ConfigDict, ip_statement
from ipmininet.tests.test_srv6 import _infer_sub_paths
from ipmininet.tests.utils import wait_until
from ipmininet.utils import get_set, is_container, is_subnet_of

_EXPECTED_CALLS = 3
_MAX_SETUP_WAIT = 0.1


class TestWaitUntil:
    """Tests for the anti-flaky polling helper."""

    def test_immediate_success(self):
        assert wait_until(lambda: True, timeout=1) is True

    def test_success_after_several_calls(self):
        calls = {"n": 0}

        def _eventually():
            calls["n"] += 1
            return calls["n"] >= _EXPECTED_CALLS

        assert wait_until(_eventually, timeout=1, interval=0.01) is True
        assert calls["n"] == _EXPECTED_CALLS

    def test_timeout_fails(self):
        with pytest.raises(
            pytest.fail.Exception,
            match="Timed out after 0s while waiting for the condition",
        ):
            wait_until(lambda: False, timeout=0.05, interval=0.01)

    def test_timeout_evaluates_callable_description(self):
        with pytest.raises(pytest.fail.Exception, match="last observed state: 5"):
            wait_until(
                lambda: False,
                timeout=0.05,
                interval=0.01,
                description=lambda: "last observed state: 5",
            )

    def test_success_does_not_wait(self):
        # Check-then-sleep: an immediate success must return without sleeping.
        start = time.monotonic()
        wait_until(lambda: True, timeout=1, interval=0.5)
        assert time.monotonic() - start < _MAX_SETUP_WAIT

    def test_callable_predicate_receives_no_args(self):
        assert wait_until(lambda: True, timeout=1, interval=0.01) is True


class TestInferSubPaths:
    """Tests for the SRv6 capture-path inference (burst-of-probes aware)."""

    _NODES = ["h6", "r6", "r5", "r4", "h4"]
    _DEST = "fc00:0:d::1"
    _BURST = [0.3 + k for k in range(20)]

    @staticmethod
    def _burst_events(gaps, probes):
        """Build packet_received for a burst of probes, mirroring sr_path: a
        node that is live when probe k is sent records it."""
        events = {TestInferSubPaths._DEST: []}
        for pos, node in enumerate(TestInferSubPaths._NODES):
            for probe_time in probes:
                if probe_time >= gaps.get(node, 0.0):
                    events[TestInferSubPaths._DEST].append(
                        (probe_time + 0.005 * pos, node)
                    )
        return events

    def test_single_probe(self):
        packet_received = self._burst_events({}, [0.3])
        assert _infer_sub_paths(packet_received)[self._DEST] == self._NODES

    def test_burst_preserves_path_order(self):
        # Every node live from the first probe: all probes are recorded on
        # every node, and the path must not repeat once per probe.
        packet_received = self._burst_events({}, self._BURST)
        assert _infer_sub_paths(packet_received)[self._DEST] == self._NODES

    def test_burst_with_staggered_liveness(self):
        # Nodes become live at different times (the CI failure case: early
        # probes are lost on the slow nodes); the path must still be recovered
        # from a probe that every node eventually saw.
        gaps = {"h6": 1.0, "r6": 2.0, "r5": 3.0, "r4": 4.0, "h4": 5.0}
        packet_received = self._burst_events(gaps, self._BURST)
        assert _infer_sub_paths(packet_received)[self._DEST] == self._NODES

    def test_last_probe_missed_on_every_node(self):
        packet_received = self._burst_events({}, self._BURST)
        packet_received[self._DEST] = [
            (t, n) for t, n in packet_received[self._DEST] if t < self._BURST[-1]
        ]
        assert _infer_sub_paths(packet_received)[self._DEST] == self._NODES

    def test_double_capture_on_router(self):
        # A router captures a forwarded packet once per interface, so a probe
        # can appear twice on one node; the path must still be recovered.
        packet_received = {
            self._DEST: [
                (0.300, "h6"),
                (0.3005, "r6"),
                (0.3010, "r6"),
                (0.302, "r5"),
                (0.303, "r4"),
                (0.305, "h4"),
                (0.800, "h6"),
                (0.8005, "r6"),
                (0.8010, "r6"),
                (0.802, "r5"),
                (0.803, "r4"),
                (0.805, "h4"),
            ]
        }
        assert _infer_sub_paths(packet_received)[self._DEST] == self._NODES

    def test_probes_not_split_at_half_second_boundary(self):
        # Probes must be grouped by time gap, not by rounding: a probe at
        # .648 and the next one +0.5s later (.156) both round to the same
        # integer and must not be merged into one fake probe.
        packet_received = {
            self._DEST: [
                (176.648, "h6"),
                (176.6485, "r6"),
                (176.649, "r5"),
                (176.650, "r4"),
                (176.651, "h4"),
                (177.156, "h6"),
                (177.1565, "r6"),
                (177.157, "r5"),
                (177.158, "r4"),
                (177.159, "h4"),
            ]
        }
        assert _infer_sub_paths(packet_received)[self._DEST] == self._NODES


class TestParseAddresses:
    """Tests for the pure `ip address` output parser."""

    def test_parse_full_output(self):
        out = """1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host
       valid_lft forever preferred_lft forever
"""
        mac, v4, v6 = _parse_addresses(out)
        assert mac == "00:00:00:00:00:00"
        assert [a.with_prefixlen for a in v4] == ["127.0.0.1/8"]
        assert [a.with_prefixlen for a in v6] == ["::1/128"]

    def test_parse_empty(self):
        mac, v4, v6 = _parse_addresses("")
        assert mac is None
        assert v4 == []
        assert v6 == []

    def test_parse_ignores_malformed_lines(self):
        out = """2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue
    link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff
    this is not a valid ip line
    inet 192.168.0.2/24 brd 192.168.0.255 scope global eth0
"""
        mac, v4, v6 = _parse_addresses(out)
        assert mac == "00:11:22:33:44:55"
        assert [a.with_prefixlen for a in v4] == ["192.168.0.2/24"]
        assert v6 == []


class TestIsSubnetOf:
    def test_v4_subnet(self):
        assert is_subnet_of(ip_network("10.0.0.0/24"), ip_network("10.0.0.0/16"))
        assert not is_subnet_of(ip_network("10.1.0.0/16"), ip_network("10.0.0.0/16"))

    def test_v4_self(self):
        assert is_subnet_of(ip_network("10.0.0.0/16"), ip_network("10.0.0.0/16"))

    def test_v6_subnet(self):
        assert is_subnet_of(ip_network("2001:db8::/32"), ip_network("2001::/16"))
        assert not is_subnet_of(ip_network("2002::/16"), ip_network("2001::/16"))

    def test_cross_version_raises(self):
        with pytest.raises(TypeError):
            is_subnet_of(IPv4Network("10.0.0.0/8"), IPv6Network("2001:db8::/32"))

    def test_non_network_raises(self):
        with pytest.raises(TypeError):
            is_subnet_of("10.0.0.0/8", IPv4Network("10.0.0.0/8"))


class TestIsContainer:
    def test_sequences(self):
        assert is_container([1, 2, 3])
        assert is_container((1, 2, 3))

    def test_not_container(self):
        assert not is_container("a string")
        assert not is_container(42)


class TestGetSet:
    def test_existing_key(self):
        d = {"a": 1}
        assert get_set(d, "a", list) == 1
        assert d == {"a": 1}

    def test_missing_key(self):
        d = {}
        assert get_set(d, "b", list) == []
        assert d == {"b": []}


class TestConfigDict:
    def test_attribute_access(self):
        d = ConfigDict(foo="bar")
        assert d.foo == "bar"
        assert d["foo"] == "bar"

    def test_missing_attribute_is_none(self):
        d = ConfigDict()
        assert d.missing is None

    def test_attribute_assignment(self):
        d = ConfigDict()
        d.foo = "bar"
        assert d["foo"] == "bar"


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("10.0.0.0/8", "ip"),
        (4, "ip"),
        ("2001:db8::/32", "ipv6"),
        (6, "ipv6"),
    ],
)
def test_ip_statement(ip, expected):
    assert ip_statement(ip) == expected
