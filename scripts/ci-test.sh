#!/usr/bin/env bash
set -euo pipefail
LOGFILE="${LOGFILE:-/workspace/.tmp/pytest.log}"
exec > >(tee "$LOGFILE") 2>&1

mkdir -p /workspace/htmlcov

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

export PATH="/root:$PATH"

exec sudo env "PATH=$PATH" uv run python -m pytest \
    --cov-config=.coveragerc \
    --cov=ipmininet/ \
    --cov-report=html \
    --cov-report=term \
    -v \
    -p faulthandler \
    --showlocals --capture=tee-sys --tb=long \
    "$@"