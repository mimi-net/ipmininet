#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/.tmp
LOGFILE="${LOGFILE:-/workspace/.tmp/pytest.log}"
exec > >(tee "$LOGFILE") 2>&1

# sshd -t requires the privilege separation directory; it is created at
# install time but lost between the image build and the container start.
mkdir -p /run/sshd

# Start Open vSwitch if not already running
if [ ! -e /var/run/openvswitch/db.sock ]; then
    mkdir -p /var/run/openvswitch /etc/openvswitch
    ovsdb-tool create /etc/openvswitch/conf.db \
        /usr/share/openvswitch/vswitch.ovsschema 2>/dev/null || true
    ovsdb-server --remote=punix:/var/run/openvswitch/db.sock \
        --pidfile --detach 2>/dev/null || true
    ovs-vswitchd --detach --pidfile 2>/dev/null || true
    sleep 0.5
fi

# Without explicit test files, run the whole suite in parallel (xdist +
# isolated namespaces), mirroring the bare-metal jobs.
if [ "$#" -eq 0 ]; then
    exec sudo env "PATH=$PATH" ${UV_PROJECT_ENVIRONMENT:+"UV_PROJECT_ENVIRONMENT=$UV_PROJECT_ENVIRONMENT"} \
        scripts/run-tests-parallel.sh
fi

exec sudo env "PATH=$PATH" ${UV_PROJECT_ENVIRONMENT:+"UV_PROJECT_ENVIRONMENT=$UV_PROJECT_ENVIRONMENT"} uv run python -m pytest \
    -v \
    -p faulthandler \
    --showlocals --capture=tee-sys --tb=long \
    "$@"
