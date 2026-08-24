# Stage 1: deps — build tools + uv + tarballs (cached unless pyproject.toml changes)
FROM ubuntu:24.04 AS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git sudo ca-certificates wget \
    autoconf automake libtool make gcc g++ groff patch bison flex gawk \
    texinfo libreadline-dev libc-ares-dev libjson-c-dev \
    perl python3-dev libpam0g-dev libsystemd-dev libsnmp-dev pkg-config \
    libcap-dev cmake libpcre3-dev socat psmisc xterm openssh-client iperf3 \
    ethtool help2man net-tools python3-pexpect python3-tk iproute2 \
    cgroup-tools autotools-dev libc6-dev tcpdump python3-scapy \
    libpcap-dev libconfig-dev openvswitch-switch radvd bind9 dnsutils \
    bridge-utils traceroute nmap netcat-openbsd tshark \
    python3-pip grub-common \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY uv.lock pyproject.toml .python-version /workspace/
WORKDIR /workspace
RUN uv sync --all-extras
RUN mkdir -p /opt/ipmininet-archives \
    && wget -q https://github.com/CESNET/libyang/archive/refs/tags/v1.0.215.tar.gz \
       -O /opt/ipmininet-archives/libyang.tar.gz \
    && wget -q https://github.com/FRRouting/frr/releases/download/frr-7.5/frr-7.5.tar.gz \
       -O /opt/ipmininet-archives/frr.tar.gz

# Stage 2: compile — libyang + frrouting (cached unless install.py changes)
FROM deps AS compile
COPY ipmininet/install/ /workspace/ipmininet/install/
COPY scripts/ci-compile.sh /workspace/scripts/ci-compile.sh
RUN mkdir -p /workspace/.tmp && scripts/ci-compile.sh \
    && mkdir -p /opt/compiled-frr/lib /opt/compiled-frr/share /opt/compiled-frr/lib/x86_64-linux-gnu \
    && find /usr/lib/x86_64-linux-gnu -name 'libyang*' -exec cp -rLt /opt/compiled-frr/lib/x86_64-linux-gnu/ {} + 2>/dev/null || true \
    && cp -r /usr/lib/x86_64-linux-gnu/libyang1 /opt/compiled-frr/lib/x86_64-linux-gnu/ 2>/dev/null || true \
    && cp -r /usr/share/yang /opt/compiled-frr/share/ 2>/dev/null || true

# Stage 3: final — clean image with only runtime deps + compiled binaries
FROM ubuntu:24.04 AS final
RUN apt-get update && apt-get install -y --no-install-recommends \
    git sudo ca-certificates wget build-essential \
    socat psmisc xterm openssh-client iperf3 \
    ethtool help2man net-tools python3-pexpect python3-tk iproute2 \
    cgroup-tools tcpdump python3-scapy \
    openvswitch-switch radvd bind9 dnsutils iputils-ping \
    bridge-utils traceroute nmap netcat-openbsd tshark \
    python3-pip grub-common python3-pytest python3-pytest-timeout python3-pytest-cov \
    libreadline8 libc-ares2 libjson-c5 libcap2 libpam0g libsystemd0 \
    libsnmp-base libpcre3 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=compile /opt/compiled-frr/ /usr/
RUN ldconfig && (groupadd frr || true) && (groupadd frrvty || true) \
    && usermod -a -G frr root && usermod -a -G frrvty root
COPY . /workspace
WORKDIR /workspace
RUN uv sync --all-extras \
    && mkdir -p /etc/default && touch /etc/default/grub /workspace/.tmp \
    && scripts/ci-install.sh
CMD ["bash"]