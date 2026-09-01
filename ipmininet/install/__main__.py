import os

from .install import (
    dist,
    enable_ipv6,
    install_exabgp,
    install_frrouting,
    install_mininet,
    parse_args,
)

if __name__ == "__main__":
    args = parse_args()
    args.output_dir = os.path.normpath(os.path.abspath(args.output_dir))

    dist.require_pip()

    if args.all or args.install_mininet:
        install_mininet(args.output_dir, pip_install=not args.all)

    if args.all or args.install_frrouting:
        install_frrouting(args.output_dir)

    if args.all or args.install_exabgp:
        install_exabgp(args.output_dir)

    if args.all or args.install_radvd:
        if dist.package_family == "apt":
            dist.install("resolvconf")
        dist.install("radvd")

    if args.all or args.install_sshd:
        dist.install("openssh-server")
        os.makedirs("/run/sshd", exist_ok=True)

    if args.all or args.install_named:
        if dist.package_family == "apt":
            dist.install("bind9")
        elif dist.package_family == "rpm":
            dist.install("bind")

    # Install IPMininet

    if args.install_ipmininet:
        dist.install("git")
        source_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dist.pip_install(source_dir)

    # Enable IPv6 (disabled by mininet installation)

    if args.all or args.enable_ipv6:
        enable_ipv6()

    # Install test dependencies

    dist.install("bridge-utils", "traceroute", "nmap", "iperf3")
    if dist.package_family == "rpm":
        dist.install("nc", "bind-utils", "wireshark", "tc", "kernel-modules-extra")
    else:
        dist.install("netcat-openbsd", "dnsutils", "tshark")

    dist.pip_install("pytest")
