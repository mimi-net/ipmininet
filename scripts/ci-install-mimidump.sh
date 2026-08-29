#!/usr/bin/env bash
# Build and install mimidump (mimi-net/mimidump) so that the interface-capture
# tests run on bare-metal CI too. Pinned to the commit that ships the
# capture-readiness signal; skips the build when the binary is already present
# (e.g. restored from the compiled-deps cache).
set -euo pipefail

if command -v mimidump >/dev/null 2>&1; then
    echo "==> mimidump already installed, skipping build"
    exit 0
fi

echo "==> Installing mimidump build dependencies"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq libpcap-dev libbsd-dev

echo "==> Building mimidump @ mimi-net/mimidump 854a3b0"
TMPDIR_FULL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_FULL"' EXIT
git clone --quiet https://github.com/mimi-net/mimidump.git "$TMPDIR_FULL"
git -C "$TMPDIR_FULL" checkout --quiet 854a3b0
make -C "$TMPDIR_FULL"
$SUDO make -C "$TMPDIR_FULL" install

echo "==> mimidump installed: $(command -v mimidump)"