#!/usr/bin/env bash
# Run the test suite in parallel with pytest-xdist, every worker inside its
# own isolated namespace (see py-unshare.sh). Usage:
#   run-tests-parallel.sh [-j N] [pytest args...]
# -j N overrides the worker count; the default is the number of CPUs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

N="${XDIST_WORKERS:-}"
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        -j) shift; N="${1:?missing worker count after -j}"; shift ;;
        -j*) N="${1#-j}"; shift ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
if [ -z "$N" ]; then
    N="$(nproc)"
fi
if [ ${#ARGS[@]} -eq 0 ]; then
    # Schedule the slow modules first so that their waits overlap with the
    # fast modules under --dist=loadscope (one module per worker at a time).
    # ExaBGP must come first: its 9-minute worst-case wait dwarfs everything
    # else, so start it before any other module claims a worker.
    ARGS=(
        ipmininet/tests/test_exabgp.py
        ipmininet/tests/test_srv6.py
        ipmininet/tests/test_tc.py
        ipmininet/tests/test_ospf6.py
        ipmininet/tests/test_ospf.py
        ipmininet/tests/test_ripng.py
        ipmininet/tests/test_linkfailure.py
        ipmininet/tests/test_switch.py
        ipmininet/tests/test_static.py
        ipmininet/tests/test_bgp.py
        ipmininet/tests/test_dns.py
        ipmininet/tests/test_radv.py
        ipmininet/tests/test_link.py
        ipmininet/tests/test_sshd.py
        ipmininet/tests/test_gre.py
        ipmininet/tests/test_iptables.py
        ipmininet/tests/test_network_capture.py
        ipmininet/tests/test_topologydb.py
        ipmininet/tests/test_cli.py
        ipmininet/tests/test_misc.py
        ipmininet/tests/test_pure.py
        ipmininet/tests/test_physicalinterface.py
        ipmininet/tests/test_address_alllocation.py
        ipmininet/tests/test_openr.py
    )
fi

WRAPPER="$ROOT/scripts/py-unshare.sh"
if [ ! -x "$WRAPPER" ]; then
    echo "error: isolation wrapper not found or not executable: $WRAPPER" >&2
    exit 1
fi

echo "==> pytest-xdist workers: $N (isolated namespaces)"
COVERAGE_FLAGS=()
if [ "${COVERAGE:-0}" = "1" ]; then
    echo "==> coverage enabled (branch mode)"
    COVERAGE_FLAGS=(
        --cov=ipmininet
        --cov-report=html:htmlcov
        --cov-report=xml:coverage.xml
    )
fi
exec uv run python -m pytest \
    -p no:cacheprovider \
    -v \
    --dist=loadscope \
    --tx "${N}*popen//python=${WRAPPER}" \
    "${COVERAGE_FLAGS[@]}" \
    "${ARGS[@]}"
