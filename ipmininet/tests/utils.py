import re
import signal
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from ipaddress import ip_address, ip_network
from re import Match, Pattern

import mininet.log
import pytest

from ipmininet.host.config.named import DNSRecord
from ipmininet.ipnet import IPNet
from ipmininet.ipswitch import IPSwitch
from ipmininet.router import IPNode
from ipmininet.utils import require_cmd

# Number of identical successive traceroutes required to consider that the
# network has converged on a stable path.
CONVERGED_PATH_COUNT = 2


def wait_until(
    predicate: Callable[[], bool],
    timeout: float = 60,
    interval: float = 0.5,
    description=None,
):
    """Wait until ``predicate()`` returns a truthy value.

    Polls every ``interval`` seconds up to ``timeout`` seconds and returns
    ``True`` as soon as the predicate succeeds. Fails the test with a
    descriptive error if the timeout is reached.

    Use this instead of a fixed ``time.sleep()`` whenever the test waits for
    an asynchronous effect (daemon startup, routing convergence, packet
    flush, ...): a fixed sleep is either too short (flaky under load) or too
    long (slow for no reason).

    :param predicate: Zero-argument callable returning whether the awaited
                      condition is satisfied.
    :param timeout: Maximum time, in seconds, to wait for the condition.
    :param interval: Time, in seconds, between two polls.
    :param description: Human-readable description of the awaited condition.
                        May be a callable returning a string, evaluated only
                        on timeout so it can include the last observed state.
    """
    if description is None:
        description = "the condition"
    elapsed = 0
    while elapsed < timeout:
        if predicate():
            return True
        time.sleep(interval)
        elapsed += interval
    if callable(description):
        description = description()
    pytest.fail(f"Timed out after {int(elapsed)}s while waiting for {description}")


def traceroute(net: IPNet, src: str, dst_ip: str, timeout=300, poll=1.0) -> list[str]:
    require_cmd("traceroute", help_str="traceroute is required to run tests")

    t = 0
    old_path_ips = []  # type: List[str]
    same_path_count = 0
    white_space = re.compile(r" +")
    while t < timeout / poll:
        out = net[src].cmd(
            [
                "traceroute",
                "-w",
                "0.05",
                "-q",
                "1",
                "-n",
                "-m",
                len(net.routers) + len(net.hosts),
                dst_ip,
            ]
        )
        lines = out.split("\n")[1:-1]
        if "*" not in out and "!" not in out and "unreachable" not in out:
            path_ips = [str(white_space.split(line)[2]) for line in lines]
            if (
                len(path_ips) > 0
                and path_ips[-1] == str(dst_ip)
                and old_path_ips == path_ips
            ):
                same_path_count += 1
                if same_path_count > CONVERGED_PATH_COUNT:
                    # Network has converged
                    return path_ips
            else:
                same_path_count = 0

            old_path_ips = path_ips
        else:
            same_path_count = 0
            old_path_ips = []
        # Only sleep before the next poll; the iteration above returns as soon
        # as the path is stable, so this does not add latency on success.
        time.sleep(poll)
        t += 1
    return []


def assert_path(
    net: IPNet,
    expected_path: list[str],
    v6=False,
    retry=5,
    timeout=300,
    traceroute_fun=traceroute,
    **kwargs,
):
    src = expected_path[0]
    dst = expected_path[-1]
    dst_ip = net[dst].defaultIntf().ip6 if v6 else net[dst].defaultIntf().ip

    path = []  # type: List[str]
    i = 0
    while path != expected_path and i < retry:
        path_ips = traceroute_fun(net, src, dst_ip, timeout=timeout, **kwargs)

        path = [src]
        for path_ip in path_ips:
            found = False
            for n in net.routers + net.hosts:
                for itf in n.intfList():
                    itf_ips = itf.ip6s() if v6 else itf.ips()
                    for ip in itf_ips:
                        if ip.ip == ip_address(path_ip):
                            found = True
                            break
                    if found:
                        break
                if found:
                    path.append(n.name)
                    break
            assert found, (
                f"Traceroute returned the address '{path_ip}' "
                "that cannot be linked to a node"
            )
        i += 1

    assert path == expected_path, (
        f"We expected the path from {src} to {dst} to go "
        f"through {expected_path[1:-1]} but it went through {path[1:-1]}"
    )


def host_connected(net: IPNet, v6=False, timeout=0.2, translate_address=True) -> bool:
    require_cmd("nmap", help_str="nmap is required to run tests")

    hosts = list(net.hosts)
    if not hosts:
        # Nothing to probe (e.g. router-only topologies); the sequential
        # loop also returns True immediately in this case.
        return True
    # Refresh the target addresses once, before probing
    for dst in hosts:
        dst.defaultIntf().updateIP()
        dst.defaultIntf().updateIP6()

    def _check_src(src) -> bool:
        for dst in hosts:
            if src != dst:
                if translate_address:
                    dst_ip = dst.defaultIntf().ip6 if v6 else dst.defaultIntf().ip
                else:
                    dst_ip = dst
                cmd = (
                    f"nmap{' -6' if v6 else ''} -sn -n --system-dns "
                    f"--max-retries 0 "
                    f"--max-rtt-timeout {int(timeout * 1000)}ms {dst_ip}"
                )
                out = src.cmd(cmd.split(" "))
                if "0 hosts up" in out:
                    return False
                # In case of flooding, hosts might not answer
                # So, we wait a bit before testing the next pair of hosts
                time.sleep(0.1)
        return True

    # Each source is probed by its own worker (never two threads touch the
    # same node), which collapses the sweep to the cost of a single source.
    with ThreadPoolExecutor(max_workers=min(len(hosts), 32)) as pool:
        return all(pool.map(_check_src, hosts))


def assert_node_not_connected(src: IPNode, dst: IPNode, v6=False, timeout=0.2):
    require_cmd("nmap", help_str="nmap is required to run tests")

    dst.defaultIntf().updateIP()
    dst.defaultIntf().updateIP6()
    dst_ip = dst.defaultIntf().ip6 if v6 else dst.defaultIntf().ip
    cmd = (
        f"nmap{' -6' if v6 else ''} -sn -n --max-retries 0 "
        f"--max-rtt-timeout {int(timeout * 1000)}ms {dst_ip}"
    )
    out = src.cmd(cmd.split(" "))

    assert "0 hosts up" in out, (
        f"Node {src.name} is connected to node {dst.name} "
        f"over {'IPv4' if not v6 else 'IPv6'}"
    )


def assert_connectivity(net: IPNet, v6=False, attempts=1500, translate_address=True):
    t = 0
    connected = False
    while t < attempts and not connected:
        connected = host_connected(net, v6=v6, translate_address=translate_address)
        if not connected:
            t += 1
            time.sleep(1)
    assert connected, "Cannot ping all hosts over %s" % ("IPv4" if not v6 else "IPv6")


def check_tcp_connectivity(
    client: IPNode,
    server: IPNode,
    v6=False,
    server_port=80,
    server_itf=None,
    timeout=300,
) -> tuple[int, bytes, bytes]:
    require_cmd("nc", help_str="nc is required to run tests")

    if server_itf is None:
        server_itf = server.defaultIntf()
    server_ip = server_itf.ip6 if v6 else server_itf.ip
    server_cmd = f"nc {'-6' if v6 else '-4'} -l {server_port}"
    server_p = server.popen(server_cmd.split(" "))

    t = 0
    client_cmd = f"nc -z -w 1 -v {server_ip} {server_port}"

    client_p = client.popen(client_cmd.split(" "))
    while t < timeout * 2 and client_p.wait() != 0:
        t += 1
        if server_p.poll() is not None:
            out, err = server_p.communicate()
            raise AssertionError(
                "The netcat server used to check TCP connectivity failed"
                f" with the output:\n[stdout]\n{out}\n[stderr]\n{err}"
            )
        time.sleep(0.5)
        client_p = client.popen(client_cmd.split(" "))
    out, err = client_p.communicate()
    code = client_p.poll()
    server_p.send_signal(signal.SIGINT)
    server_p.wait()
    return code, out, err


def assert_stp_state(switch: IPSwitch, expected_states: dict[str, str], timeout=60):
    """
    :param switch: The switch to test
    :param expected_states: Dictionary mapping an interface name to
                            its expected state
    :param timeout: Time to wait for the stp convergence
    :return:
    """
    require_cmd("brctl", help_str="brctl is required to run tests")

    partial_cmd = "brctl showstp"
    possible_states = "listening|learning|forwarding|blocking"
    # In these states the STP has not converged
    ignore_state = "listening", "learning"
    cmd = f"{partial_cmd} {switch.name}"
    out = None
    states = None

    def _converged():
        nonlocal out, states
        out = switch.cmd(cmd)
        states = re.findall(possible_states, out)
        return not any(item in states for item in ignore_state)

    wait_until(
        _converged,
        timeout=timeout,
        interval=1,
        description="the spanning tree to be computed",
    )

    interfaces = re.findall(switch.name + r"-eth[0-9]+", out)
    state_map = {interfaces[i]: states[i] for i in range(len(states))}
    for itf, expected in expected_states.items():
        assert itf in state_map, (
            f"The port {itf} of switch {switch.name} was not mentioned "
            f"in the output of 'brctl showstp':\n{out}"
        )
        assert state_map[itf] == expected, (
            f"The state of port {itf} of switch {switch.name} wasn't correct: "
            f"expected '{expected}' got '{state_map[itf]}'"
        )


def assert_routing_table(
    router: IPNode,
    expected_prefixes: list[str],
    present: bool = True,
    timeout: int = 120,
):
    """
    Wait until all expected prefixes are (present=True) or none are
    (present=False) in the router's IPv4/IPv6 routing table.

    :param router: The router to test
    :param expected_prefixes: The list of prefixes to look for
    :param present: Whether to wait for the prefixes to be present (True) or
                    absent (False) from the routing table
    :param timeout: Time to wait for the routing convergence
    """
    expected = set(expected_prefixes)
    cmd = f"ip -{ip_network(str(next(iter(expected)))).version} route"
    found = set()

    def _satisfied():
        nonlocal found
        found = set(
            re.findall(r"|".join(re.escape(p) for p in expected), router.cmd(cmd))
        )
        return (expected <= found) if present else not (expected & found)

    wait_until(
        _satisfied,
        timeout=timeout,
        interval=1,
        description=lambda: (
            f"prefixes {expected_prefixes} to be "
            f"{'present' if present else 'absent'} in the routing table "
            f"of {router.name} within {timeout}s (found: {sorted(found)})"
        ),
    )


def search_dns_reply(reply: str, regex: Pattern) -> tuple[bool, Match | None]:

    got_answer = False
    for line in reply.split("\n"):
        if got_answer:
            if "SECTION" in line:
                break  # End of the answer section
            match = regex.match(line)
            if match is not None:
                return True, match  # Got the right answer
        elif ";; ANSWER SECTION:" in line:  # Beginning of the answer section
            got_answer = True
    return got_answer, None


def assert_dns_record(
    node: IPNode, dns_server_address: str, record: DNSRecord, port=53, timeout=60
):
    require_cmd("dig", help_str="dig is required to run tests")

    server_cmd = (
        f"dig @{dns_server_address} -p {port} -t {record.rtype} {record.domain_name}"
    )
    out_regex = re.compile(
        rf" *{record.domain_name}.?[ \t]+{record.ttl}[ \t]+IN[ \t]+{record.rtype}[ \t]+"
        rf"{record.rdata}"
    )

    out = None
    got_answer = False
    match = None

    def _answered():
        nonlocal out, got_answer, match
        out = node.cmd(server_cmd.split(" "))
        got_answer, match = search_dns_reply(out, out_regex)
        return match is not None

    wait_until(
        _answered,
        timeout=timeout,
        interval=0.5,
        description=lambda: (
            f"the expected data '{out_regex.pattern}' to be found in the DNS "
            f"reply of '{server_cmd}' received by {node.name} from "
            f"{dns_server_address}:\n{out}"
        ),
    )

    assert got_answer, (
        f"No answer was received in {node.name}"
        f" from server {dns_server_address} in the reply of '{server_cmd}':\n{out}"
    )

    assert match is not None, (
        f"The expected data '{out_regex.pattern}' cannot be found "
        f"in the DNS reply of '{server_cmd}' received by {node.name} from "
        f"{dns_server_address}:\n{out}"
    )


class CLICapture:
    def __init__(self, loglevel: str):
        self.loglevel = loglevel
        self.stream = None
        self.handler = None
        self.out = []  # type: List[str]

    def __enter__(self):
        self.stream = StringIO()
        self.handler = mininet.log.StreamHandlerNoNewline(self.stream)
        mininet.log.lg.addHandler(self.handler)
        return self

    def __exit__(self, *args):
        mininet.log.lg.removeHandler(self.handler)
        self.handler.flush()
        self.handler.close()
        self.out = self.stream.getvalue().splitlines()
