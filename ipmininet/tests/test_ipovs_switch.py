"""This module tests the IPOVSSwitch class."""

from unittest import mock

import pytest

from ipmininet.ipovs_switch import IPOVSSwitch

TEST_PRIORITY = 100


def test_constructor_defaults():
    switch = IPOVSSwitch("s1")

    assert switch.rstp is False
    assert switch.stp is False
    assert switch.priority is None
    assert switch.failMode == "standalone"


@pytest.mark.parametrize(
    "rstp,stp,hub,exp_rstp,exp_stp",
    [
        (True, False, False, True, False),
        (False, True, False, False, True),
        (True, True, False, True, True),
        (True, True, True, False, False),
        (True, False, True, False, False),
    ],
)
def test_constructor_stp_flags(rstp, stp, hub, exp_rstp, exp_stp):
    switch = IPOVSSwitch("s1", stp=stp, rstp=rstp, hub=hub)

    assert switch.rstp is exp_rstp
    assert switch.stp is exp_stp


def test_constructor_priority():
    switch = IPOVSSwitch("s1", priority=TEST_PRIORITY)

    assert switch.priority == TEST_PRIORITY
    assert switch.failMode == "standalone"


def _bridge_opts(**kwargs):
    switch = IPOVSSwitch("s1", **kwargs)
    with mock.patch.object(IPOVSSwitch, "isOldOVS", return_value=False):
        return switch, switch.bridgeOpts()


def test_bridge_opts_defaults():
    switch, opts = _bridge_opts()

    assert "other_config:datapath-id=" in opts
    assert "fail_mode=standalone" in opts
    assert "other_config:disable-in-band=true" in opts
    assert "other_config:dp-desc=s1" in opts
    assert " stp_enable=true" not in opts
    assert " rstp_enable=true" not in opts
    assert switch.priority is None


def test_bridge_opts_priority():
    _, opts = _bridge_opts(priority=TEST_PRIORITY)

    assert f"other_config:stp-priority={TEST_PRIORITY}" in opts
    assert f"other_config:rstp-priority={TEST_PRIORITY}" in opts


def test_bridge_opts_rstp_enabled():
    _, opts = _bridge_opts(rstp=True)

    assert " rstp_enable=true" in opts
    assert " stp_enable=true" not in opts


def test_bridge_opts_stp_enabled():
    _, opts = _bridge_opts(stp=True)

    assert " stp_enable=true" in opts
    assert " rstp_enable=true" not in opts


def test_bridge_opts_stp_blocked_by_controller_mode():
    _, opts = _bridge_opts(stp=True, failMode="secure")

    assert " stp_enable=true" not in opts
    assert " rstp_enable=true" not in opts


def test_bridge_opts_user_datapath():
    _, opts = _bridge_opts(datapath="user")

    assert "datapath_type=netdev" in opts


def test_bridge_opts_protocols_on_new_ovs():
    _, opts = _bridge_opts(protocols="OpenFlow13")

    assert "protocols=OpenFlow13" in opts


def test_bridge_opts_no_protocols_on_old_ovs():
    switch = IPOVSSwitch("s1", protocols="OpenFlow13")
    with mock.patch.object(IPOVSSwitch, "isOldOVS", return_value=True):
        opts = switch.bridgeOpts()

    assert "protocols=" not in opts


def test_bridge_opts_inband_keeps_in_band_control():
    _, opts = _bridge_opts(inband=True)

    assert "other_config:disable-in-band=true" not in opts


def test_start_in_namespace_raises():
    switch = IPOVSSwitch("s1")
    switch.inNamespace = True

    with pytest.raises(RuntimeError, match="does not work in a namespace"):
        switch.start(controllers=[])
