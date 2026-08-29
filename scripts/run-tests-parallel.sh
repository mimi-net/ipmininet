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
    ARGS=(ipmininet/tests/)
fi

WRAPPER="$ROOT/scripts/py-unshare.sh"
if [ ! -x "$WRAPPER" ]; then
    echo "error: isolation wrapper not found or not executable: $WRAPPER" >&2
    exit 1
fi

echo "==> pytest-xdist workers: $N (isolated namespaces)"
exec uv run python -m pytest \
    -p no:cacheprovider \
    -v \
    --dist=load \
    --tx "${N}*popen//python=${WRAPPER}" \
    "${ARGS[@]}"
