import pytest
import re
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Dict, Pattern, Match, Optional

import mininet.log
from io import StringIO
from ipaddress import ip_address, ip_network
from ipmininet.utils import require_cmd
from ipmininet.ipnet import IPNet
from ipmininet.router import IPNode
from ipmininet.ipswitch import IPSwitch
from ipmininet.host.config.named import DNSRecord


def traceroute(net: IPNet, src: str, dst_ip: str, timeout=300,
               poll=1.0) -> List[str]:
    require_cmd("traceroute", help_str="traceroute is required to run tests")

    t = 0
    old_path_ips = []  # type: List[str]
    same_path_count = 0
    white_space = re.compile(r" +")
    while t != timeout / poll:
        out = net[src].cmd(["traceroute", "-w", "0.05", "-q", "1", "-n",
                            "-m", len(net.routers) + len(net.hosts), dst_ip])
        lines = out.split("\n")[1:-1]
        if "*" not in out and "!" not in out and "unreachable" not in out:
            path_ips = [str(white_space.split(line)[2]) for line in lines]
            if len(path_ips) > 0 and path_ips[-1] == str(dst_ip) \
                    and old_path_ips == path_ips:
                same_path_count += 1
                if same_path_count > 2:
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


def assert_path(net: IPNet, expected_path: List[str], v6=False, retry=5,
                timeout=300, traceroute_fun=traceroute, **kwargs):
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
            assert found, "Traceroute returned the address '%s' " \
                          "that cannot be linked to a node" % path_ip
        i += 1

    assert path == expected_path, "We expected the path from %s to %s to go " \
                                  "through %s but it went through %s" \
                                  % (src, dst, expected_path[1:-1], path[1:-1])


def host_connected(net: IPNet, v6=False, timeout=0.2, translate_address=True) \
        -> bool:
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
                    dst_ip = dst.defaultIntf().ip6 if v6 \
                        else dst.defaultIntf().ip
                else:
                    dst_ip = dst
                cmd = "nmap%s -sn -n --max-retries 0 --max-rtt-timeout %dms %s"\
                      % (" -6" if v6 else "", int(timeout * 1000), dst_ip)
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
    cmd = "nmap%s -sn -n --max-retries 0 --max-rtt-timeout %dms %s" \
          % (" -6" if v6 else "", int(timeout * 1000), dst_ip)
    out = src.cmd(cmd.split(" "))

    assert "0 hosts up" in out, "Node {} is connected to node {} over {}" \
        .format(src.name, dst.name, "IPv4" if not v6 else "IPv6")


def assert_connectivity(net: IPNet, v6=False, attempts=1500,
                        translate_address=True):
    t = 0
    connected = False
    while t != attempts and not connected:
        connected = host_connected(net, v6=v6,
                                   translate_address=translate_address)
        if not connected:
            t += 1
            time.sleep(1)
    assert connected, \
        "Cannot ping all hosts over %s" % ("IPv4" if not v6 else "IPv6")


def check_tcp_connectivity(client: IPNode, server: IPNode, v6=False,
                           server_port=80, server_itf=None, timeout=300) \
        -> Tuple[int, bytes, bytes]:
    require_cmd("nc", help_str="nc is required to run tests")

    if server_itf is None:
        server_itf = server.defaultIntf()
    server_ip = server_itf.ip6 if v6 else server_itf.ip
    server_cmd = "nc %s -l %d" % ("-6" if v6 else "-4", server_port)
    server_p = server.popen(server_cmd.split(" "))

    t = 0
    client_cmd = "nc -z -w 1 -v %s %d" % (server_ip, server_port)

    client_p = client.popen(client_cmd.split(" "))
    while t != timeout * 2 and client_p.wait() != 0:
        t += 1
        if server_p.poll() is not None:
            out, err = server_p.communicate()
            assert False, \
                "The netcat server used to check TCP connectivity failed" \
                " with the output:\n[stdout]\n%s\n[stderr]\n%s" % (out, err)
        time.sleep(.5)
        client_p = client.popen(client_cmd.split(" "))
    out, err = client_p.communicate()
    code = client_p.poll()
    server_p.send_signal(signal.SIGINT)
    server_p.wait()
    return code, out, err


def assert_stp_state(switch: IPSwitch, expected_states: Dict[str, str],
                     timeout=60):
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
    cmd = ("%s %s" % (partial_cmd, switch.name))
    out = switch.cmd(cmd)
    states = re.findall(possible_states, out)
    # wait for the ports to be bounded
    count = 0
    while any(item in states for item in ignore_state):
        if count == timeout:
            pytest.fail("Timeout of %d seconds while waiting for the spanning"
                        " tree to be computed" % timeout)
        time.sleep(1)
        count += 1
        out = switch.cmd(cmd)
        states = re.findall(possible_states, out)

    interfaces = re.findall(switch.name + r"-eth[0-9]+", out)
    state_map = {interfaces[i]: states[i] for i in range(len(states))}
    for itf, _ in expected_states.items():
        assert itf in state_map,\
            "The port %s of switch %s was not mentioned in the output of " \
            "'brctl showstp':\n%s" % (itf, switch.name, out)
        assert state_map[itf] == expected_states[itf],\
            "The state of port %s of switch %s wasn't correct: excepted '%s' " \
            "got '%s'"\
            % (itf, switch.name, expected_states[itf], state_map[itf])


def assert_routing_table(router: IPNode, expected_prefixes: List[str],
                         present: bool = True, timeout: int = 120):
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
    cmd = "ip -%d route" % ip_network(str(next(iter(expected)))).version
    t = 0
    while True:
        found = set(re.findall(r"|".join(re.escape(p) for p in expected),
                               router.cmd(cmd)))
        satisfied = (expected <= found) if present else not (expected & found)
        if satisfied:
            return
        if t >= timeout:
            pytest.fail("Expected prefixes %s to be %s in the routing table "
                        "of %s within %ds (found: %s)"
                        % (expected_prefixes,
                           "present" if present else "absent",
                           router.name, timeout, sorted(found)))
        time.sleep(1)
        t += 1


def search_dns_reply(reply: str, regex: Pattern) \
        -> Tuple[bool, Optional[Match]]:

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


def assert_dns_record(node: IPNode, dns_server_address: str, record: DNSRecord,
                      port=53, timeout=60):
    require_cmd("dig", help_str="dig is required to run tests")

    server_cmd = "dig @{address} -p {port} -t {rtype} {domain_name}"\
        .format(address=dns_server_address, rtype=record.rtype,
                domain_name=record.domain_name, port=port)
    out_regex = re.compile(r" *{name}.?[ \t]+{ttl}[ \t]+IN[ \t]+{rtype}[ \t]+"
                           r"{rdata}"
                           .format(rtype=record.rtype, ttl=record.ttl,
                                   name=record.domain_name,
                                   rdata=record.rdata))

    t = 0
    out = node.cmd(server_cmd.split(" "))
    got_answer, match = search_dns_reply(out, out_regex)
    while t < timeout * 2 and match is None:
        t += 1
        time.sleep(.5)
        out = node.cmd(server_cmd.split(" "))
        got_answer, match = search_dns_reply(out, out_regex)

    assert got_answer, "No answer was received in %s" \
                       " from server %s in the reply of '%s':\n%s" \
                       % (node.name, dns_server_address, server_cmd, out)

    assert match is not None, "The expected data '%s' cannot be found " \
                              "in the DNS reply of '%s' received by %s from " \
                              "%s:\n%s" % (out_regex.pattern, server_cmd,
                                           node.name, dns_server_address, out)


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
