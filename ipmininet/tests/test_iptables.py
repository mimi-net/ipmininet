"""This module tests iptables"""

from ipmininet.clean import cleanup
from ipmininet.examples.iptables import IPTablesTopo
from ipmininet.ipnet import IPNet
from ipmininet.tests.utils import check_tcp_connectivity, wait_until

from . import require_root


@require_root
def test_iptables_example():
    try:
        net = IPNet(topo=IPTablesTopo())
        net.start()

        ip = net["r2"].intf("r2-eth0").ip
        cmd = f"ping -W 1 -c 1 {ip}"
        last_out = ""
        last_err = ""

        def _ipv4_ping_ok():
            nonlocal last_out, last_err
            p = net["r1"].popen(cmd.split(" "))
            ret = p.wait()
            last_out, last_err = p.communicate()
            return ret == 0

        wait_until(
            _ipv4_ping_ok,
            timeout=30,
            interval=0.5,
            description=lambda: (
                "IPv4 pings from {} to {} to not be blocked\n"
                "[stdout]\n{}\n[stderr]\n{}".format(net["r1"], ip, last_out, last_err)
            ),
        )

        ip6 = net["r2"].intf("r2-eth0").ip6
        cmd = f"ping6 -W 1 -c 1 {ip6}"
        wait_until(
            lambda: net["r1"].popen(cmd.split(" ")).wait() != 0,
            timeout=50,
            interval=5,
            description="IPv6 pings from {} to {} to be blocked".format(net["r1"], ip6),
        )

        ret, _, _ = check_tcp_connectivity(
            net["r1"],
            net["r2"],
            server_port=80,
            server_itf=net["r2"].intf("r2-eth0"),
            timeout=0.5,
        )
        assert ret != 0, "TCP over port 80 should be blocked over IPv4"

        ret, _, _ = check_tcp_connectivity(
            net["r1"],
            net["r2"],
            server_port=1480,
            server_itf=net["r2"].intf("r2-eth0"),
            timeout=0.5,
        )
        assert ret != 0, "TCP over port 1480 should be blocked over IPv4"

        ret, _, _ = check_tcp_connectivity(
            net["r1"],
            net["r2"],
            server_port=2000,
            server_itf=net["r2"].intf("r2-eth0"),
            timeout=0.5,
        )
        assert ret == 0, "TCP over port 2000 should not be blocked over IPv4"

        ret, out, err = check_tcp_connectivity(
            net["r1"],
            net["r2"],
            v6=True,
            server_port=80,
            server_itf=net["r2"].intf("r2-eth0"),
        )
        assert ret == 0, (
            "TCP over port 80 should not be blocked over IPv6.\n"
            f"[stdout]\n{out}\n[stderr]\n{err}"
        )

        net.stop()
    finally:
        cleanup()
