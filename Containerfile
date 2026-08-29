# Self-contained test container.
#
# Installs the runtime/build dependencies, the uv-managed virtualenv
# (UV_PROJECT_ENVIRONMENT=/opt/venv, which survives the bind-mount in
# container-test.yaml) and then runs the full `ipmininet.install -a` so that
# FRRouting, libyang, mininet, radvd, sshd and named are available.
#
# PEP 668 blocks pip3 system-wide installs on Ubuntu 24.04; the deferred
# install.py refactor will make this explicit in-code, for now we relax it.
FROM ubuntu:24.04 AS final

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update && apt-get install -y --no-install-recommends \
    git sudo ca-certificates wget build-essential \
    autoconf automake libtool make gcc groff patch bison flex gawk \
    texinfo libreadline-dev libc-ares-dev libjson-c-dev \
    perl python3-dev libpam0g-dev libsystemd-dev libsnmp-dev pkg-config \
    libcap-dev cmake libpcre3-dev socat psmisc xterm openssh-client iperf3 \
    ethtool help2man net-tools python3-pexpect python3-tk iproute2 \
    cgroup-tools autotools-dev libc6-dev tcpdump python3-scapy \
    libpcap-dev libbsd-dev libconfig-dev openvswitch-switch radvd bind9 dnsutils \
    bridge-utils traceroute nmap netcat-openbsd tshark iptables iputils-ping \
    python3-pip grub-common \
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

CMD ["bash"]
