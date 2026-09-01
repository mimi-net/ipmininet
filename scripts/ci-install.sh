#!/usr/bin/env bash
set -euo pipefail
LOGFILE="${LOGFILE:-/workspace/.tmp/install.log}"
exec > >(tee "$LOGFILE") 2>&1
exec sudo env "PATH=$PATH" \
    ${UV_PROJECT_ENVIRONMENT:+"UV_PROJECT_ENVIRONMENT=$UV_PROJECT_ENVIRONMENT"} \
    uv run python -m ipmininet.install -a
