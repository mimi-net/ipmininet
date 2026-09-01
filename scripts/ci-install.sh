#!/usr/bin/env bash
set -euo pipefail
LOGFILE="${LOGFILE:-/workspace/.tmp/install.log}"
exec > >(tee "$LOGFILE") 2>&1
# PEP 668 on Ubuntu 24.04 and newer blocks pip3 system installs; relax it.
export PIP_BREAK_SYSTEM_PACKAGES="${PIP_BREAK_SYSTEM_PACKAGES:-1}"
exec sudo env "PATH=$PATH" PIP_BREAK_SYSTEM_PACKAGES="$PIP_BREAK_SYSTEM_PACKAGES" \
    ${UV_PROJECT_ENVIRONMENT:+"UV_PROJECT_ENVIRONMENT=$UV_PROJECT_ENVIRONMENT"} \
    uv run python -m ipmininet.install -a
