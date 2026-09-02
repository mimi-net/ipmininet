# Self-contained test container, built in two stages to keep the runtime
# image lean.
#
# builder: installs every build dependency and runs the full
# `ipmininet.install -a` (FRRouting 10.x, libyang v3, mininet, radvd, sshd,
# named, exabgp) plus the uv-managed virtualenv and mimidump.
#
# runtime: a plain ubuntu:26.04 with only the packages the test suite needs,
# plus the compiled artifacts copied over from the builder. The build
# toolchain (compilers, autotools, *-dev headers) never reaches this stage.

FROM ubuntu:26.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Build-time and run-time packages in one shot for the builder; the runtime
# stage installs only its own subset below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git sudo ca-certificates wget build-essential \
    autoconf automake libtool make gcc groff patch bison flex gawk \
    texinfo libreadline-dev libc-ares-dev libjson-c-dev \
    perl python3-dev libpam0g-dev libsystemd-dev libsnmp-dev pkg-config \
    libcap-dev cmake socat psmisc xterm openssh-client iperf3 \
    ethtool help2man net-tools python3-pexpect python3-tk iproute2 \
    cgroup-tools autotools-dev libc6-dev tcpdump python3-scapy \
    libpcap-dev libbsd-dev libconfig-dev openvswitch-switch radvd bind9 dnsutils \
    bridge-utils traceroute nmap netcat-openbsd tshark iptables iputils-ping \
    python3-pip grub-common libpcre2-dev libelf-dev libunwind-dev python3-sphinx \
    && rm -rf /var/lib/apt/lists/*

# Build mimidump (mimi-net/mimidump) so the interface-capture tests can run in
# the container. Pinned to the commit that ships the capture-readiness signal.
RUN git clone --quiet https://github.com/mimi-net/mimidump.git /tmp/mimidump \
    && git -C /tmp/mimidump checkout --quiet 854a3b0 \
    && make -C /tmp/mimidump \
    && make -C /tmp/mimidump install \
    && rm -rf /tmp/mimidump

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /workspace
COPY uv.lock pyproject.toml .python-version /workspace/
RUN uv sync --all-extras

COPY . /workspace
RUN mkdir -p /workspace/.tmp && scripts/ci-install.sh

# ---------------------------------------------------------------- runtime ---

FROM ubuntu:26.04 AS final

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Run-time packages only: the tools the test suite actually invokes. The FRR
# daemons themselves and libyang come over from the builder.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git sudo ca-certificates wget \
    socat psmisc xterm openssh-client openssh-server iperf3 ethtool net-tools \
    python3-pexpect python3-tk iproute2 tcpdump python3-scapy \
    openvswitch-switch radvd bind9 dnsutils bridge-utils traceroute \
    nmap netcat-openbsd tshark iptables iputils-ping python3-pip grub-common \
    libjson-c5 libcap2 libpcre2-8-0 libunwind8 \
    && rm -rf /var/lib/apt/lists/*

# FRR daemons and helpers from the builder install (prefix /root/frr).
COPY --from=builder /root/frr /root/frr
# libyang v3 runtime library and headers.
COPY --from=builder /usr/lib/x86_64-linux-gnu/libyang* /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/include/libyang /usr/include/
COPY --from=builder /usr/share/yang/modules/libyang /usr/share/yang/modules/
COPY --from=builder /usr/bin/yanglint /usr/bin/yanglint
# mininet mnexec and exabgp.
COPY --from=builder /usr/local/bin/mnexec /usr/local/bin/mnexec
COPY --from=builder /root/exabgp /root/exabgp
COPY --from=builder /usr/sbin/exabgp /usr/sbin/exabgp
# mimidump.
COPY --from=builder /usr/local/bin/mimidump /usr/local/bin/mimidump
# The uv-managed virtualenv and its CPython toolchain (the venv's
# bin/python* are symlinks into it).
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /root/.local/share/uv/python /root/.local/share/uv/python
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# FRR runtime identity and the /usr/{sbin,bin} links (matching what the
# installer's link_to_standard_dir() would have created).
RUN groupadd frr && groupadd frrvty \
    && usermod -a -G frr root \
    && usermod -a -G frrvty root \
    && for f in /root/frr/sbin/*; do ln -sf "$f" /usr/sbin/; done \
    && for f in /root/frr/bin/*; do ln -sf "$f" /usr/bin/; done \
    && mkdir -p /var/run/frr /var/lib/frr /etc/frr

WORKDIR /workspace
COPY . /workspace
RUN mkdir -p /workspace/.tmp

CMD ["bash"]
