#!/usr/bin/env bash
# Restore compiled system dependencies produced by `ipmininet.install -a` from
# $CI_DEPS_DIR (default: $HOME/ci-deps) into their install locations so the
# install step can skip recompiling (see the guards in ipmininet/install/install.py).
# The FRRouting symlinks under /usr/sbin and /usr/bin are recreated by the
# install step itself. Run as the (non-root) runner user before the install step.
set -euo pipefail
SRC="${CI_DEPS_DIR:-$HOME/ci-deps}"
[ -d "$SRC" ] || { echo "no compiled deps cache at $SRC"; exit 0; }
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
echo "==> Restoring compiled dependencies from $SRC"

# apt archives first, so apt-get reuses .debs instead of downloading
[ -d "$SRC/apt-archives" ] && $SUDO cp -a "$SRC/apt-archives/." /var/cache/apt/archives/

[ -f "$SRC/usr.tar" ] && (cd / && $SUDO tar -xf "$SRC/usr.tar")
[ -f "$SRC/libyang.tar" ] && (cd / && $SUDO tar -xf "$SRC/libyang.tar")
[ -f "$SRC/root.tar" ] && $SUDO tar -C /root -xf "$SRC/root.tar"

# Recreate the /usr/sbin/exabgp symlink (points at the /root/exabgp zipapp)
$SUDO ln -sfn /root/exabgp /usr/sbin/exabgp