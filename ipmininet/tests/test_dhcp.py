"""This module tests the Dnsmasq and DHCPRelay daemon configurations."""

import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ipmininet.host.config.dnsmasq import Dnsmasq
from ipmininet.router.config.dhcprelay import DHCPRelay

SERVER_IP = "192.168.0.1"
LISTENING_IP = "192.168.0.254"
GW_IP = "192.168.1.1"
DHCP_RANGE = "192.168.1.100,192.168.1.200"
MASK = "255.255.255.0"
PID = "1234"


@pytest.fixture
def tmp_cwd():
    cwd = tempfile.mkdtemp(dir="/tmp")
    yield cwd
    shutil.rmtree(cwd, ignore_errors=True)


def _node(name, cwd, routerid=None):
    node = SimpleNamespace(name=name, cwd=cwd)
    node.cmd = MagicMock()
    if routerid is not None:
        node.nconfig = SimpleNamespace(routerid=routerid)
    return node


def _dnsmasq(tmp_cwd, intfs=None):
    node = _node("h1", tmp_cwd)
    daemon = Dnsmasq(node, DHCP_RANGE, MASK, GW_IP, intfs or ["eth0"])
    return node, daemon


def test_dnsmasq_build_and_files(tmp_cwd):
    node, daemon = _dnsmasq(tmp_cwd, ["eth0", "eth1"])

    cfg = daemon.build()

    assert cfg.pid_file == daemon.pid_file
    assert cfg.ip_range == DHCP_RANGE
    assert cfg.mask == MASK
    assert cfg.gw == GW_IP
    assert cfg.interfaces == ["eth0", "eth1"]
    assert cfg.opts["dhcp-range"] == f"{DHCP_RANGE},{MASK}"
    assert cfg.opts["dhcp-option"] == f"3,{GW_IP}"
    assert cfg.opts["interface"] == ["eth0", "eth1"]
    assert cfg.opts["port"] == 0
    assert cfg.opts["log-queries"] is None

    filename = daemon.cfg_filenames[0]
    assert filename == os.path.join(str(tmp_cwd), "dnsmasq_h1.eth0_eth1.cfg")
    assert daemon.startup_line == f"dnsmasq --conf-file={filename}"
    assert daemon.dry_run == ""
    assert daemon.template_filenames == ["dnsmasq.mako", "dnsmasq.mako"]
    assert node.cmd.call_count == 0


def test_dnsmasq_pids_found(tmp_cwd):
    _, daemon = _dnsmasq(tmp_cwd)
    daemon.node.cmd.return_value = (
        'udp 0 0 0.0.0.0:53 users:(("dnsmasq",pid=1234,fd=5))\n'
        'tcp 0 0 0.0.0.0:53 users:(("dnsmasq",pid=5678,fd=6))\n'
    )

    assert daemon.pids == ["1234", "5678"]
    daemon.node.cmd.assert_called_once_with("ss -tulnp | grep dnsmasq")


def test_dnsmasq_pids_without_match(tmp_cwd):
    _, daemon = _dnsmasq(tmp_cwd)
    daemon.node.cmd.return_value = "ss output without any pid"

    assert daemon.pids is None


def test_dnsmasq_pids_empty_output(tmp_cwd):
    _, daemon = _dnsmasq(tmp_cwd)
    daemon.node.cmd.return_value = ""

    assert daemon.pids is None


def test_dnsmasq_kill(tmp_cwd):
    node, daemon = _dnsmasq(tmp_cwd)
    node.cmd.side_effect = [f" {PID} \n", ""]

    daemon.kill()

    assert node.cmd.call_args_list[0].args[0] == f"cat {daemon.pid_file}"
    assert node.cmd.call_args_list[1].args[0] == f"kill -9 {PID}"


def test_dnsmasq_cleanup(tmp_cwd):
    node, daemon = _dnsmasq(tmp_cwd)
    node.cmd.side_effect = [f" {PID} \n", ""]

    daemon.cleanup()

    assert node.cmd.call_args_list[1].args[0] == f"kill -9 {PID}"


def test_dhcprelay_build_and_files(tmp_cwd):
    node = _node("r1", str(tmp_cwd), routerid="10.0.0.1")
    daemon = DHCPRelay(node, SERVER_IP, LISTENING_IP)

    cfg = daemon.build()

    assert cfg.pid_file == daemon.pid_file
    assert cfg.dhcp_server_ip == SERVER_IP
    assert cfg.listening_ip == LISTENING_IP
    assert cfg.routerid == "10.0.0.1"

    filename = daemon.cfg_filenames[0]
    assert filename == os.path.join(str(tmp_cwd), f"dhcprelay_r1.{LISTENING_IP}.cfg")
    assert daemon.startup_line == f"dnsmasq --conf-file={filename}"
    assert daemon.dry_run == ""
    assert daemon.KILL_PATTERNS == ("dnsmasq",)
    assert node.cmd.call_count == 0


def test_dhcprelay_kill_and_cleanup(tmp_cwd):
    node = _node("r1", str(tmp_cwd))
    daemon = DHCPRelay(node, SERVER_IP, LISTENING_IP)
    node.cmd.side_effect = [f" {PID} \n", "", f" {PID} \n", ""]

    daemon.kill()
    daemon.cleanup()

    assert node.cmd.call_args_list[0].args[0] == f"cat {daemon.pid_file}"
    assert node.cmd.call_args_list[1].args[0] == f"kill -9 {PID}"
    assert node.cmd.call_args_list[2].args[0] == f"cat {daemon.pid_file}"
    assert node.cmd.call_args_list[3].args[0] == f"kill -9 {PID}"
