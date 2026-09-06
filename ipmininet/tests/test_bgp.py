"""This module tests the BGP daemon"""

import pytest

from ipmininet.examples.bgp_full_config import BGPTopoFull
from ipmininet.examples.bgp_local_pref import BGPTopoLocalPref
from ipmininet.examples.bgp_med import BGPTopoMed
from ipmininet.examples.bgp_policies_1 import BGPPoliciesTopo1
from ipmininet.examples.bgp_policies_2 import BGPPoliciesTopo2
from ipmininet.examples.bgp_policies_3 import BGPPoliciesTopo3
from ipmininet.examples.bgp_policies_4 import BGPPoliciesTopo4
from ipmininet.examples.bgp_policies_5 import BGPPoliciesTopo5
from ipmininet.examples.bgp_policies_adjust import BGPPoliciesAdjustTopo
from ipmininet.examples.bgp_rr import BGPTopoRR
from ipmininet.examples.simple_bgp_network import SimpleBGPTopo
from ipmininet.iptopo import IPTopo
from ipmininet.router.config import AS, BGP, bgp_peering, iBGPFullMesh
from ipmininet.router.config.base import RouterConfig
from ipmininet.router.config.bgp import AF_INET, AF_INET6, CLIENT_PROVIDER
from ipmininet.tests.utils import (
    assert_all_paths,
    assert_config_file,
    assert_connectivity,
    run_ipnet,
)

from . import require_root


class BGPTopo(IPTopo):
    def __init__(self, as2r1_params, *args, **kwargs):
        self.as2r1_params = as2r1_params
        super().__init__(*args, **kwargs)

    def build(self, *args, **kwargs):
        """
               +----------+                                   +--------+
                          |                                   |
             AS1          |                  AS2              |        AS3
                          |                                   |
                          |                                   |
        +-------+   eBGP  |  +-------+     iBGP    +-------+  |  eBGP   +-------+
        | as1r1 +------------+ as2r1 +-------------+ as2r2 +------------+ as3r1 |
        +-------+         |  +-------+             +-------+  |         +-------+
                          |                                   |
                          |                                   |
                          |                                   |
             +------------+                                   +--------+
        """
        # Add all routers
        as1r1 = self.addRouter("as1r1", config=RouterConfig)
        as1r1.addDaemon(
            BGP,
            address_families=[
                AF_INET(redistribute=["connected"]),
                AF_INET6(redistribute=["connected"]),
            ],
        )
        as2r1 = self.addRouter("as2r1", config=RouterConfig)
        as2r1.addDaemon(BGP, **self.as2r1_params)
        as2r2 = self.addRouter("as2r2", config=RouterConfig)
        as2r2.addDaemon(
            BGP,
            address_families=[
                AF_INET(redistribute=["connected"]),
                AF_INET6(redistribute=["connected"]),
            ],
        )
        as3r1 = self.addRouter("as3r1", config=RouterConfig)
        as3r1.addDaemon(
            BGP,
            address_families=[
                AF_INET(redistribute=["connected"]),
                AF_INET6(redistribute=["connected"]),
            ],
        )

        self.addLink(
            as1r1,
            as2r1,
            params1={"ip": ("10.1.1.1/24", "fd00:1:1::1/64")},
            params2={"ip": ("10.1.1.2/24", "fd00:1:1::2/64")},
        )
        self.addLink(
            as2r1,
            as2r2,
            params1={"ip": ("10.2.1.1/24", "fd00:2:1::1/64")},
            params2={"ip": ("10.2.1.2/24", "fd00:2:1::2/64")},
        )
        self.addLink(
            as3r1,
            as2r2,
            params1={"ip": ("10.3.1.1/24", "fd00:3:1::1/64")},
            params2={"ip": ("10.3.1.2/24", "fd00:3:1::2/64")},
        )

        # Set AS-ownerships
        self.addOverlay(AS(1, (as1r1,)))
        self.addOverlay(iBGPFullMesh(2, (as2r1, as2r2)))
        self.addOverlay(AS(3, (as3r1,)))
        # Add eBGP peering
        bgp_peering(self, as1r1, as2r1)
        bgp_peering(self, as3r1, as2r2)

        # Add test hosts
        self.addLink(
            as1r1,
            self.addHost(f"h{as1r1}"),
            params1={"ip": ("10.1.0.1/24", "fd00:1::1/64")},
            params2={"ip": ("10.1.0.2/24", "fd00:1::2/64")},
        )
        self.addLink(
            as3r1,
            self.addHost(f"h{as3r1}"),
            params1={"ip": ("10.3.0.1/24", "fd00:3::1/64")},
            params2={"ip": ("10.3.0.2/24", "fd00:3::2/64")},
        )
        super().build(*args, **kwargs)


@require_root
def test_bgp_example():
    with run_ipnet(SimpleBGPTopo()) as net:
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)


@require_root
@pytest.mark.parametrize(
    "bgp_params,expected_cfg",
    [
        (
            {
                "address_families": [
                    AF_INET(redistribute=["connected"]),
                    AF_INET6(redistribute=["connected"]),
                ]
            },
            [
                "router bgp 2",
                "neighbor 10.1.1.1 remote-as 1",
                "neighbor 10.2.1.2 remote-as 2",
                "neighbor 10.1.1.1 ebgp-multihop",
                "neighbor 10.1.1.1 activate",
                "neighbor 10.2.1.2 activate",
                "redistribute connected",
            ],
        ),
        (
            {
                "address_families": [
                    AF_INET(redistribute=["connected"], networks=["10.0.0.0/24"]),
                    AF_INET6(
                        redistribute=["connected"], networks=["fd00:2001:180::/64"]
                    ),
                ]
            },
            ["network 10.0.0.0/24", "network fd00:2001:180::/64"],
        ),
    ],
)
def test_bgp_daemon_params(bgp_params, expected_cfg):
    with run_ipnet(BGPTopo(bgp_params), allocate_IPs=False) as net:
        # Check generated configuration
        assert_config_file("/tmp/bgpd_as2r1.cfg", expected_cfg, strip=True)

        # Check reachability
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)


local_pref_paths = [
    ["as1r1", "as1r6", "as4r1", "as4h1"],
    ["as1r2", "as1r3", "as1r6", "as4r1", "as4h1"],
    ["as1r3", "as1r6", "as4r1", "as4h1"],
    ["as1r4", "as1r5", "as1r6", "as4r1", "as4h1"],
    ["as1r5", "as1r6", "as4r1", "as4h1"],
    ["as1r6", "as4r1", "as4h1"],
]

med_paths = [
    ["as1r1", "as1r6", "as1r5", "as4r2", "as4h1"],
    ["as1r2", "as1r3", "as1r6", "as1r5", "as4r2", "as4h1"],
    ["as1r3", "as1r6", "as1r5", "as4r2", "as4h1"],
    ["as1r4", "as1r5", "as4r2", "as4h1"],
    ["as1r5", "as4r2", "as4h1"],
    ["as1r6", "as1r5", "as4r2", "as4h1"],
]

rr_paths = [
    ["as1r1", "as1r6", "as5r1", "as2r1", "as2h1"],
    ["as1r2", "as1r3", "as1r6", "as5r1", "as2r1", "as2h1"],
    ["as1r3", "as1r6", "as5r1", "as2r1", "as2h1"],
    ["as1r4", "as4r2", "as4r1", "as2r1", "as2h1"],
    ["as1r5", "as4r1", "as2r1", "as2h1"],
    ["as1r6", "as5r1", "as2r1", "as2h1"],
]

full_paths = [
    ["as1r1", "as1r6", "as4r1", "as4h1"],
    ["as1r2", "as1r3", "as1r6", "as4r1", "as4h1"],
    ["as1r3", "as1r6", "as4r1", "as4h1"],
    ["as1r4", "as1r5", "as1r6", "as4r1", "as4h1"],
    ["as1r5", "as1r6", "as4r1", "as4h1"],
    ["as1r6", "as4r1", "as4h1"],
]

_bgp_path_examples = [
    (BGPTopoLocalPref, local_pref_paths),
    (BGPTopoMed, med_paths),
    (BGPTopoRR, rr_paths),
    (BGPTopoFull, full_paths),
]


@require_root
@pytest.mark.parametrize("topo,paths", _bgp_path_examples)
def test_bgp_paths(topo, paths):
    with run_ipnet(topo()) as net:
        assert_all_paths(net, paths, v6=True)


policies_paths = {
    BGPPoliciesTopo1.__name__: [
        ["has1r1", "as1r1", "as5r1", "has5r1"],
        ["has1r1", "as1r1", "as2r1", "has2r1"],
        ["has1r1", "as1r1", "as2r1", "as2r2", "has2r2"],
        ["has2r1", "as2r1", "as5r1", "has5r1"],
        ["has2r2", "as2r2", "as2r1", "as5r1", "has5r1"],
        ["has2r2", "as2r2", "as2r1", "as5r1", "has5r1"],
        ["has4r1", "as4r1", "as5r1", "as1r1", "has1r1"],
    ],
    BGPPoliciesTopo2.__name__: [
        ["has1", "as1", "as2", "has2"],
        ["has4", "as4", "as3", "has3"],
        ["has2", "as2", "as3", "has3"],
    ],
    BGPPoliciesTopo3.__name__: [
        ["has2r", "as2r", "as1r", "has1r"],
        ["has2r", "as2r", "as3r", "has3r"],
        ["has1r", "as1r", "as4r", "has4r"],
        ["has3r", "as3r", "as4r", "has4r"],
    ],
    BGPPoliciesTopo4.__name__: [
        ["has2r", "as2r", "as3r", "has3r"],
        ["has2r", "as2r", "as5r", "has5r"],
        ["has2r", "as2r", "as1r", "has1r"],
        ["has3r", "as3r", "as4r", "has4r"],
    ],
    BGPPoliciesTopo5.__name__: [
        ["has1r", "as1r", "as4r", "as6r", "as7r", "as5r", "has5r"],
        ["has5r", "as5r", "as2r", "as1r", "has1r"],
    ],
    BGPPoliciesAdjustTopo.__name__: [
        ["has4r", "as4r", "as1r", "has1r"],
        ["has5r", "as5r", "as3r", "has3r"],
    ],
}


@require_root
@pytest.mark.parametrize(
    "topology",
    [
        BGPPoliciesTopo1,
        BGPPoliciesTopo2,
        BGPPoliciesTopo3,
        BGPPoliciesTopo4,
        BGPPoliciesTopo5,
        BGPPoliciesAdjustTopo,
    ],
)
def test_bgp_policies(topology):
    with run_ipnet(topology()) as net:
        assert_all_paths(net, policies_paths[topology.__name__], v6=True)


@require_root
def test_bgp_policies_adjust():
    # Adding this new peering link should enable all hosts to ping each others
    with run_ipnet(
        BGPPoliciesAdjustTopo(
            as_start="as5r", as_end="as2r", bgp_policy=CLIENT_PROVIDER
        )
    ) as net:
        assert_connectivity(net, v6=True)
