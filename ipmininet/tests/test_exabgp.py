import json
import os
import re
from collections.abc import Sequence
from contextlib import closing
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv6Address,
    IPv6Interface,
    ip_address,
    ip_network,
)
from typing import Union

import pytest

from ipmininet.clean import cleanup
from ipmininet.examples.exabgp_prefix_injector import ExaBGPTopoInjectPrefixes
from ipmininet.ipnet import IPNet
from ipmininet.router.config import BGPAttribute, BGPRoute, ExaList
from ipmininet.tests import require_exabgp, require_root
from ipmininet.tests.utils import wait_until

exa_routes = {
    "ipv4": [
        BGPRoute(
            ip_network("8.8.8.0/24"),
            [
                BGPAttribute("next-hop", "self"),
                BGPAttribute("as-path", ExaList([1, 56, 97])),
                BGPAttribute("med", 42),
                BGPAttribute("origin", "egp"),
            ],
        ),
        BGPRoute(
            ip_network("30.252.0.0/16"),
            [
                BGPAttribute("next-hop", "self"),
                BGPAttribute("as-path", ExaList([1, 48964, 598])),
                BGPAttribute("med", 100),
                BGPAttribute("origin", "incomplete"),
                BGPAttribute("community", ExaList(["1:666", "468:45687"])),
            ],
        ),
        BGPRoute(
            ip_network("1.2.3.4/32"),
            [
                BGPAttribute("next-hop", "self"),
                BGPAttribute("as-path", ExaList([1, 49887, 39875, 3, 4])),
                BGPAttribute("origin", "igp"),
                BGPAttribute("local-preference", 42),
            ],
        ),
        BGPRoute(
            ip_network("79.232.8.234/31"),
            [
                BGPAttribute("next-hop", "self"),
                BGPAttribute(
                    "as-path",
                    ExaList(
                        [
                            1,
                            5,
                            48643,
                            27269,
                            40070,
                            23066,
                            16156,
                            42942,
                            63941,
                            59598,
                            13519,
                            34769,
                            58452,
                            30040,
                            10201,
                            20699,
                            47328,
                            60517,
                            10726,
                            30566,
                            41722,
                        ]
                    ),
                ),
                BGPAttribute("med", 2983147431),
                BGPAttribute("origin", "incomplete"),
                BGPAttribute(
                    "community",
                    ExaList(
                        [
                            "27143:50178",
                            "43275:3204",
                            "8207:51989",
                            "37776:50582",
                            "43665:5655",
                            "27666:57245",
                            "404:44723",
                            "35094:21563",
                            "43160:60093",
                            "52506:5571",
                            "26526:20041",
                            "64552:41036",
                            "42411:6349",
                            "22060:7250",
                            "5047:27611",
                            "956:27358",
                            "41924:60774",
                            "39756:8423",
                            "55633:46188",
                            "52836:8813",
                            "35178:22387",
                            "37869:27641",
                            "27376:27259",
                            "8825:27516",
                            "37759:17407",
                        ]
                    ),
                ),
            ],
        ),
    ],
    "ipv6": [
        BGPRoute(
            ip_network("dead:beef:15:dead::/64"),
            [
                BGPAttribute("next-hop", "self"),
                BGPAttribute("as-path", ExaList([1, 4, 3, 5])),
                BGPAttribute("origin", "egp"),
                BGPAttribute("local-preference", 1000),
            ],
        ),
        BGPRoute(
            ip_network("bad:c0ff:ee:bad:c0de::/80"),
            [
                BGPAttribute("next-hop", "self"),
                BGPAttribute("as-path", ExaList([1, 3, 4])),
                BGPAttribute("origin", "egp"),
                BGPAttribute(
                    "community", ExaList(["2914:480", "2914:413", "2914:4621"])
                ),
            ],
        ),
        BGPRoute(
            ip_network("1:5ee:bad:c0de::/64"),
            [
                BGPAttribute("next-hop", "self"),
                BGPAttribute("as-path", ExaList([1, 89, 42, 5])),
                BGPAttribute("origin", "igp"),
            ],
        ),
    ],
}

get_rib = (
    "#!/usr/bin/env sh \n"
    "nc {host} {port} <<EOF\n"
    "zebra\n"
    "show bgp {family} json\n"
    "exit\n"
    "EOF\n"
)


def prepare_rib_lookup_script(rib_script) -> Sequence[tuple[str, str]]:
    scripts = []
    for family in ("ipv4", "ipv6"):
        super_path = f"/tmp/_get_{family}_rib.sh"
        scripts.append((super_path, family))
        with closing(open(super_path, "w")) as f:
            f.write(rib_script.format(host="localhost", port=2605, family=family))

    return scripts


def get_rib_routes(node, command, family):
    """Return the parsed BGP RIB routes for the given family, or None if the
    RIB cannot be read yet (e.g. the router has not fully started)."""
    my_output = node.popen(f"sh {command}")
    my_output.wait()
    out, _err = my_output.communicate()

    output = out.decode(errors="ignore")

    p = re.compile(rf"(?s)as2> show bgp {family} json(?P<rib>.*)as2> exit")
    m = p.search(output)
    if m is None:
        return None

    return json.loads(m.group("rib")).get("routes")


def wait_for_expected_routes(node, rib_scripts, topo, timeout=900, poll=5):
    """Wait until all the routes ExaBGP is expected to inject appear in the
    FRRouting BGP RIB.

    ExaBGP is configured to only send its routes after a delay (2 minutes by
    default), and the passive BGP session it uses may take a while to
    establish. A fixed sleep is therefore unreliable under load; poll the RIB
    instead. The default timeout accounts for that delay plus the slow
    delivery of the routes under a loaded CI runner (observed up to ~9 minutes
    on the container job).
    """
    expected_routes = topo.routes
    missing = []

    def _all_routes_present():
        nonlocal missing
        missing = []
        for command, family in rib_scripts:
            rib_routes = get_rib_routes(node, command, family)
            if rib_routes is None:
                missing.append((family, "<no RIB>"))
            else:
                for route in expected_routes[family]:
                    if str(route.IPNetwork) not in rib_routes:
                        missing.append((family, str(route.IPNetwork)))
        return not missing

    wait_until(
        _all_routes_present,
        timeout=timeout,
        interval=poll,
        description=lambda: (
            f"the routes injected by ExaBGP to appear in the "
            f"BGP RIB within {timeout}s. Missing: {missing}"
        ),
    )


def check_correct_rib(node, rib_scripts, topo):
    expected_rib_routes = topo.routes
    for command, family in rib_scripts:
        rib_routes = get_rib_routes(node, command, family)

        assert rib_routes is not None, "Unable to find the RIB"

        print(expected_rib_routes)
        print(rib_routes)

        for our_route in expected_rib_routes[family]:
            str_ipnet = str(our_route.IPNetwork)

            assert str_ipnet in rib_routes, (
                f"{our_route.IPNetwork} not in FRRouting BGP RIB"
            )

            # take the first one as ExaBGP sends only one route per prefix
            rib_route = rib_routes[str_ipnet][0]

            assert rib_route["origin"].lower() == our_route["origin"].val, (
                f"Bad origin for route {our_route.IPNetwork}. Expected "
                f"{our_route['origin'].val}. Received {rib_route['origin']}"
            )

            check_as_path(rib_route["path"], our_route["as-path"].val)

            assert check_next_hop(rib_route["nexthops"], topo.addr["as1"]) is True, (
                "Bad next hop"
            )

            if "metric" in rib_route:
                assert rib_route["metric"] == our_route["med"].val, (
                    "Bad MED. Expected {expected}. Received {received}".format(
                        expected=our_route["med"].val, received=rib_route["metric"]
                    )
                )


def check_next_hop(
    next_hops: dict, expected_nh: dict[str, Union["IPv4Interface", "IPv6Interface"]]
):
    for next_hop in next_hops:
        rib_next_hop = ip_address(next_hop["ip"])

        if (
            isinstance(rib_next_hop, IPv4Address)
            and rib_next_hop == expected_nh["ipv4"].ip
        ):
            return True
        if (
            isinstance(rib_next_hop, IPv6Address)
            and rib_next_hop == expected_nh["ipv6"].ip
        ):
            return True

    return False


def check_as_path(as_path_rib: str, as_path_us: ExaList):
    as_rib = [int(asn) for asn in as_path_rib.split(" ")]
    as_rib_us = as_path_us.val

    error_msg = "Bad AS-PATH. Expected {expected}. Received {received}"

    assert len(as_rib) == len(as_rib_us), error_msg.format(
        expected=as_rib_us, received=as_path_rib
    )

    for idx, asn_received, asn_expected in zip(
        range(len(as_rib)), as_rib, as_rib_us, strict=False
    ):
        assert asn_received == asn_expected, (
            f"Bad ASN at index {idx}. Expected AS{asn_expected}. "
            f"Received AS{asn_received}"
        )


@require_root
@require_exabgp
@pytest.mark.timeout(1200)
@pytest.mark.parametrize(
    "topo_test,frr_bgp_node",
    [
        (
            ExaBGPTopoInjectPrefixes(routes=exa_routes),
            "as2",
        ),  # default IPs, custom routes,
        (ExaBGPTopoInjectPrefixes(), "as2"),  # default IPs, random routes
        (
            ExaBGPTopoInjectPrefixes(
                addr={
                    "as1": {"ipv4": "8.8.8.1/24", "ipv6": "2001:4860:4860::1/64"},
                    "as2": {"ipv4": "8.8.8.2/24", "ipv6": "2001:4860:4860::2/64"},
                }
            ),
            "as2",
        ),  # custom IP addr, random routes
        (
            ExaBGPTopoInjectPrefixes(
                routes=exa_routes,
                addr={
                    "as1": {"ipv4": "9.8.8.1/24", "ipv6": "2001:4860:4860::1/64"},
                    "as2": {"ipv4": "9.8.8.2/24", "ipv6": "2001:4860:4860::2/64"},
                },
            ),
            "as2",
        ),  # custom IP addr, custom routes
    ],
)
def test_example_exabgp(topo_test, frr_bgp_node):
    rib_scripts = prepare_rib_lookup_script(get_rib)
    net = IPNet(topo=topo_test)
    try:
        net.start()
        # ExaBGP sends its routes at most 2 minutes after the startup, and the
        # passive session may take a while to establish under load; poll the
        # RIB instead of sleeping a fixed amount.
        wait_for_expected_routes(net[frr_bgp_node], rib_scripts, topo_test)
        check_correct_rib(net[frr_bgp_node], rib_scripts, topo_test)
    finally:
        net.stop()
        for file, _ in rib_scripts:
            os.unlink(file)
        cleanup()
