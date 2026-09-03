import os
import select
import shlex
import signal
import time
import traceback

import pytest

from ipmininet.clean import cleanup
from ipmininet.examples.srv6 import SRv6Topo
from ipmininet.ipnet import IPNet
from ipmininet.srv6 import (
    LocalSIDTable,
    SRv6Encap,
    SRv6EndB6EncapsFunction,
    SRv6EndDT6Function,
    SRv6EndDX6Function,
    SRv6EndFunction,
    SRv6EndTFunction,
    SRv6EndXFunction,
)
from ipmininet.tests import require_root
from ipmininet.tests.utils import assert_connectivity, assert_path, wait_until
from ipmininet.utils import require_cmd

MAIN_TABLE = 254


class SRv6TestTopo(SRv6Topo):
    def __init__(self, new_routes: dict[str, tuple], *args, **kwargs):
        """
        :param new_routes: A dictionary mapping the host name to the router name
                           to a list of tuples (SRv6Route class, params).
                           The params have to contain all the constructor
                           parameter except the node and the network.
        """
        self.new_routes = new_routes
        super().__init__(*args, **kwargs)

    def post_build(self, net):
        super().post_build(net)

        for r in self.new_routes:
            route_class, route_params = self.new_routes[r]

            if issubclass(route_class, SRv6EndFunction):
                if r not in self.tables:
                    r_segment_space = next(net[r].intf("lo").ip6s()).network
                    self.tables[r] = LocalSIDTable(net[r], matching=[r_segment_space])
                # We use the local SID table
                route_params["table"] = self.tables[r]
            try:
                route_class(net=net, node=net[r], **route_params)
            except Exception:
                traceback.print_exc()
                raise


def _tshark_capturing(tsharks: list, stderr_buf: dict) -> bool:
    """Return whether every tshark announced it is capturing.

    tshark prints "Capturing on <interface>" to stderr once the capture is
    live. Waiting on that notification is more reliable than checking that the
    process is merely alive: a just-started tshark may not have attached to the
    interface yet, and the measurement ping would then be missed.
    """
    for p in tsharks:
        if p.poll() is not None:
            return False
        try:
            ready, _, _ = select.select([p.stderr], [], [], 0)
            if ready:
                stderr_buf[p] = stderr_buf.get(p, "") + os.read(
                    p.stderr.fileno(), 4096
                ).decode(errors="ignore")
        except OSError:
            return False
        if "Capturing on" not in stderr_buf.get(p, ""):
            return False
    return True


def _infer_sub_paths(
    packet_received: dict[str, list[tuple[float, str]]],
) -> dict[str, list[str]]:
    """Return, for each observed destination, the ordered nodes on its path.

    The measurement ping is spread over a burst of probes because tshark only
    becomes live a moment after announcing "Capturing on ...": the probes sent
    before that are lost, and every node that is live records every later
    probe (a router records a forwarded packet once per interface). A
    destination therefore appears once per probe on each node, and ordering
    the events naively repeats the path once per probe. Group the events per
    probe instead: a single probe is captured within a few milliseconds on
    every node along the path, while probes are sent well over 0.25s apart.
    Use the latest probe that was seen on every node: it is a single, complete
    traversal, ordered by capture time.
    """
    sub_paths = {}  # type: Dict[str, List[str]]
    for dest, events in packet_received.items():
        ordered = sorted(events)
        probes = []  # type: List[List[Tuple[float, str]]]
        for capture_time, node in ordered:
            if probes and capture_time - probes[-1][-1][0] < 0.25:
                probes[-1].append((capture_time, node))
            else:
                probes.append([(capture_time, node)])
        node_count = len({node for _, node in ordered})
        complete = [
            group for group in probes if len({node for _, node in group}) == node_count
        ]
        if complete:
            chosen = max(complete, key=lambda group: group[-1][0])
            nodes = []  # type: List[str]
            for _, node in chosen:
                if not nodes or nodes[-1] != node:
                    nodes.append(node)
            sub_paths[dest] = nodes
        else:
            # No single probe was seen on every node: fall back to ordering
            # the nodes by their latest observation.
            latest = {}  # type: Dict[str, float]
            for capture_time, node in ordered:
                latest[node] = max(latest.get(node, 0.0), capture_time)
            sub_paths[dest] = [
                node for node, _ in sorted(latest.items(), key=lambda kv: kv[1])
            ]
    return sub_paths


def sr_path(net: IPNet, src: str, dst_ip: str, timeout=1, through=()) -> list[str]:
    require_cmd("tshark", help_str="tshark is required to run tests")
    require_cmd("nmap", help_str="nmap is required to run tests")

    # Check connectivity
    ping_cmd = f"ping -6 -c 1 -W {int(timeout)} {dst_ip}"
    out = net[src].cmd(shlex.split(ping_cmd))
    if ", 0% packet loss" not in out:
        return []

    # Start captures of the IPv6 traffic on every node
    tsharks = []
    stderr_buf = {}
    nodes = net.routers + net.hosts
    try:
        for n in nodes:
            p = n.popen(shlex.split(f"tshark -n -i any -f 'ip6' -w /tmp/{n.name}.pcap"))
            tsharks.append(p)
        # Wait for tshark to announce it started capturing. A freshly started
        # tshark only becomes functionally live a moment *after* printing this
        # message, so we then wait for each capture to record packets.
        wait_until(
            lambda: _tshark_capturing(tsharks, stderr_buf),
            timeout=30,
            interval=0.2,
            description="tshark to start capturing on every node",
        )

        probe_cmd = f"ping -6 -c 1 -W {int(timeout)} {dst_ip}"

        def _pcap_size(node):
            path = f"/tmp/{node.name}.pcap"
            return os.path.getsize(path) if os.path.isfile(path) else 0

        # Phase 1: a capture is live once its file grew past the header
        # written at start. Probe until every capture is live; the
        # announcement alone is not a reliable signal under load.
        baseline = {n.name: _pcap_size(n) for n in nodes}
        deadline = time.monotonic() + 20
        while (
            not all(_pcap_size(n) > baseline[n.name] for n in nodes)
            and time.monotonic() < deadline
        ):
            out = net[src].cmd(shlex.split(probe_cmd))
            assert "100% packet loss" not in out, (
                f"Connectivity from {src} to {dst_ip} is not ensured, "
                "so we cannot infer the path."
            )
            time.sleep(0.5)

        # Phase 2: every capture is live; send the single measurement probe.
        # Nodes off the measurement path never see it, so we cannot wait for
        # every capture to record it: stopping with SIGINT flushes whatever
        # was captured, and the read-back assert below is the confirmation
        # that the measurement actually landed on the path.
        out = net[src].cmd(shlex.split(probe_cmd))
        assert "100% packet loss" not in out, (
            f"Connectivity from {src} to {dst_ip} is not ensured, "
            "so we cannot infer the path."
        )

        for p in tsharks:
            assert p.poll() is None, (
                f"tshark stopped unexpectedly:stderr '{p.stderr.read()}'"
            )
    finally:
        # Stop captures; SIGINT makes tshark flush the captured packets to disk
        for p in tsharks:
            p.send_signal(signal.SIGINT)
            p.wait()

    # Retrieve packet captures
    captures = {}  # type: Dict[str, List[Tuple[float, str]]]
    for n in net.routers + net.hosts:
        out = n.cmd(
            shlex.split(
                f"tshark -n -r /tmp/{n.name}.pcap -T fields "
                "-E separator=/t "
                "-e icmpv6.type -e ipv6.dst -e frame.time_epoch"
            )
        )
        data = out.split("\n")[1:-1]
        for line in data:
            values = line.strip().split("\t")
            if len(values) < 3:
                continue
            icmp_type = values[0]
            # On newer tshark, ipv6.dst lists every IPv6 header of an
            # encapsulated packet (e.g. the SRv6 SID and the inner
            # destination).  Keep the outermost one, which is the
            # destination each router actually forwards on, and matches
            # the addresses used by the `through` segments of the test.
            data_dst = values[1].split(",")[0]
            data_time = values[-1]
            if icmp_type == "128":
                captures.setdefault(n.name, []).append((float(data_time), data_dst))

    # Verify the measurement actually landed in the captures: this is the
    # notification that tshark was capturing when the probes were sent.
    captured_dests = {dest for _, packets in captures.items() for _, dest in packets}
    assert dst_ip in captured_dests, (
        f"No capture recorded the ping to {dst_ip} (captured destinations: "
        f"{sorted(captured_dests)}). tshark was probably not capturing yet."
    )

    # Analyze results

    packet_received = {}  # type: Dict[str, List[Tuple[float, str]]]
    for n, packets in captures.items():
        for data_time, destination in packets:
            packet_received.setdefault(destination, []).append((data_time, n))

    sub_paths = _infer_sub_paths(packet_received)

    # Order sub paths with the trough list
    path = []  # type: List[str]
    for intermediate in through:
        found = False

        try:
            intermediate_ips = [
                ip.ip.compressed
                for itf in net[intermediate].intfList()
                for ip in itf.ip6s(exclude_lls=True)
            ]
        except KeyError:
            intermediate_ips = [intermediate]

        for ip in intermediate_ips:
            if ip in sub_paths:
                found = True
                path.extend(sub_paths[ip])
                break
        if not found:
            return path
    path.extend(sub_paths[dst_ip])

    # Remove duplicates
    compressed_path = []  # type: List[str]
    for n in path:
        if len(compressed_path) == 0 or n != compressed_path[-1]:
            compressed_path.append(n)

    # Remove source to get a similar output to traceroute
    path = [net[n].intf().ip6 for n in compressed_path][1:]

    # Clean up the per-node captures so no stale file lingers between the
    # parametrized cases of this module.
    for n in net.routers + net.hosts:
        pcap_path = f"/tmp/{n.name}.pcap"
        if os.path.isfile(pcap_path):
            os.unlink(pcap_path)

    return path


def _wait_v6_connectivity(net: IPNet, src: str, dst_ip: str, timeout=120) -> None:
    """Wait until ``src`` can ping ``dst_ip`` over IPv6.

    The path assertions below measure IPv6 routes, but the routing only
    converges after the IPv4 one asserted by ``assert_connectivity``: under
    parallel CI load OSPFv6 could still be settling when ``sr_path`` started
    probing, which made it return an empty path and flaked the test.
    """

    def _connected() -> bool:
        out = net[src].cmd(shlex.split(f"ping -6 -c 1 -W 1 {dst_ip}"))
        return ", 0% packet loss" in out

    wait_until(
        _connected,
        timeout=timeout,
        interval=1,
        description=lambda: f"IPv6 connectivity from {src} to {dst_ip} to converge",
    )


@require_root
@pytest.mark.parametrize(
    "routes,paths,through",
    [
        (
            {},
            [
                ["h6", "r6", "r5", "r4", "h4"],
                ["h1", "r1", "r6", "r5", "r2", "r3", "r4", "h4"],
            ],
            [[], ["r6", "r5", "2042:3:3::34", "r4"]],
        ),  # Intermediate destinations
        (
            {
                "h6": (
                    SRv6Encap,
                    {
                        "to": "h4",
                        "through": ["2042:6:6::600"],
                        "mode": SRv6Encap.INLINE,
                    },
                ),
                "r6": (SRv6EndFunction, {"to": "2042:6:6::600"}),
            },
            [
                ["h6", "r6", "r5", "r4", "h4"],
                ["h1", "r1", "r6", "r5", "r2", "r3", "r4", "h4"],
            ],
            [["2042:6:6::600"], ["r6", "r5", "2042:3:3::34", "r4"]],
        ),
        (
            {
                "h6": (
                    SRv6Encap,
                    {
                        "to": "h4",
                        "through": ["2042:5:5::500"],
                        "mode": SRv6Encap.INLINE,
                    },
                ),
                "r5": (
                    SRv6EndXFunction,
                    {"to": "2042:5:5::500", "nexthop": "2042:2:2::1"},
                ),
            },
            [
                ["h6", "r6", "r5", "r2", "r5", "r4", "h4"],
                ["h1", "r1", "r6", "r5", "r2", "r3", "r4", "h4"],
            ],
            [["2042:5:5::500"], ["r6", "r5", "2042:3:3::34", "r4"]],
        ),
        (
            {
                "h6": (
                    SRv6Encap,
                    {
                        "to": "h4",
                        "through": ["2042:5:5::501", "2042:2:2::1"],
                        "mode": SRv6Encap.INLINE,
                    },
                ),
                "r5": (
                    SRv6EndTFunction,
                    {"to": "2042:5:5::501", "lookup_table": MAIN_TABLE},
                ),
            },
            [
                ["h6", "r6", "r5", "r2", "r5", "r4", "h4"],
                ["h1", "r1", "r6", "r5", "r2", "r3", "r4", "h4"],
            ],
            [["2042:5:5::501", "2042:2:2::1"], ["r6", "r5", "2042:3:3::34", "r4"]],
        ),
        (
            {
                "h6": (
                    SRv6Encap,
                    {"to": "h4", "through": ["2042:5:5::500"], "mode": SRv6Encap.ENCAP},
                ),
                "r5": (
                    SRv6EndDX6Function,
                    {"to": "2042:5:5::500", "nexthop": "2042:2:2::1"},
                ),
            },
            [
                ["h6", "r6", "r5", "r2", "r5", "r4", "h4"],
                ["h1", "r1", "r6", "r5", "r2", "r3", "r4", "h4"],
            ],
            [["2042:5:5::500"], ["r6", "r5", "2042:3:3::34", "r4"]],
        ),
        (
            {
                "h6": (
                    SRv6Encap,
                    {
                        "to": "h4",
                        "through": ["2042:5:5::501", "2042:4:4::1"],
                        "mode": SRv6Encap.INLINE,
                    },
                ),
                "r5": (
                    SRv6EndB6EncapsFunction,
                    {"to": "2042:5:5::501", "segments": ["2042:2:2::1"]},
                ),
            },
            [
                ["h6", "r6", "r5", "r2", "r5", "r4", "h4"],
                ["h1", "r1", "r6", "r5", "r2", "r3", "r4", "h4"],
            ],
            [
                ["2042:5:5::501", "2042:2:2::1", "2042:4:4::1"],
                ["r6", "r5", "2042:3:3::34", "r4"],
            ],
        ),
        (
            {
                "h6": (
                    SRv6Encap,
                    {
                        "to": "h4",
                        "through": ["2042:5:5::501", "2042:4:4::1"],
                        "mode": SRv6Encap.INLINE,
                    },
                ),
                "r5": (
                    SRv6EndB6EncapsFunction,
                    {"to": "2042:5:5::501", "segments": ["2042:2:2::200"]},
                ),
                "r2": (
                    SRv6EndDT6Function,
                    {"to": "2042:2:2::200", "lookup_table": MAIN_TABLE},
                ),
            },
            [
                ["h6", "r6", "r5", "r2", "r5", "r4", "h4"],
                ["h1", "r1", "r6", "r5", "r2", "r3", "r4", "h4"],
            ],
            [
                ["2042:5:5::501", "2042:2:2::200", "2042:4:4::1"],
                ["r6", "r5", "2042:3:3::34", "r4"],
            ],
        ),
    ],
)
def test_static_examples(routes, paths, through):
    try:
        topo = SRv6TestTopo(new_routes=routes)
        net = IPNet(topo=topo)
        net.start()

        assert_connectivity(net, v6=False)
        for i, p in enumerate(paths):
            dst_ip = net[p[-1]].defaultIntf().ip6
            _wait_v6_connectivity(net, p[0], dst_ip)
            assert_path(
                net,
                p,
                v6=True,
                traceroute_fun=sr_path,
                through=through[i],
                timeout=1,
                retry=30,
            )

        topo.clean()
        net.stop()
    finally:
        cleanup()
