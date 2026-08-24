#!/usr/bin/env bash
set -euo pipefail
LOGFILE="${LOGFILE:-/workspace/.tmp/compile.log}"
exec > >(tee "$LOGFILE") 2>&1
echo "Starting compile: $(date)"
exec sudo env "PATH=$PATH" uv run python -m ipmininet.install --install-frrouting-compile