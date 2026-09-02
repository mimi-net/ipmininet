#!/usr/bin/env bash
# Snapshot the compiled system dependencies produced by `ipmininet.install -a`
# into $CI_DEPS_DIR (default: $HOME/ci-deps) so a later CI run can restore them
# (ci-restore-deps.sh) and the install step skips recompiling FRRouting,
# libyang and mininet (see the guards in ipmininet/install/install.py).
# ExaBGP 5.x is pip-installed and is not cached here.
# Run as the (non-root) runner user after the install step.
set -euo pipefail
shopt -s nullglob
DEST="${CI_DEPS_DIR:-$HOME/ci-deps}"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
echo "==> Saving compiled dependencies to $DEST"
rm -rf "$DEST"
mkdir -p "$DEST"

# apt archives, so apt-get in the install step reuses .debs instead of downloading
$SUDO cp -a /var/cache/apt/archives "$DEST/apt-archives"

# System-installed artifacts: libyang and the mnexec binary.
# Glob expansion happens in a subshell rooted at / so tar stores relative members.
(
    cd /
    $SUDO tar -cf "$DEST/usr.tar" usr/bin/yanglint usr/local/bin/mnexec || true
    $SUDO tar -cf "$DEST/libyang.tar" \
        usr/lib/libyang* usr/lib/*/libyang* \
        usr/include/libyang* usr/share/libyang* || true
)

# Per-run install prefix ($HOME of the sudo install step, e.g. /root)
$SUDO tar -C /root -cf "$DEST/root.tar" frr || true
