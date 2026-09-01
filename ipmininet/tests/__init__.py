"""Test-skip policy.

Tests that require root are marked with `require_root`; they are skipped in
the rootless CI job (see .github/workflows/test.yaml) and run everywhere root
is available (the bare-metal `test`/`heavy` jobs run with sudo, the container
job runs as root).

Tests that depend on a daemon binary that may be absent use the conditional
markers below (require_exabgp, require_mimidump). They run wherever the daemon
is available and are skipped with a reason otherwise. The reasons are surfaced
in CI via `pytest -rs`; these files are intentionally not --ignore'd at the
workflow level so the skip reason stays next to the test.
"""

import os
import subprocess

import pytest

from ipmininet.utils import has_cmd

require_root = pytest.mark.skipif(
    os.getuid() != 0, reason="Running this test requires to be root"
)


def _exabgp_usable() -> bool:
    """Return whether a working ExaBGP daemon is available.

    ExaBGP 4.2.11 shipped a vendored six too old for Python 3.12 (broken
    ``six.moves``), so simply being on PATH is not enough: the daemon must
    also start (--version) cleanly.
    """
    if not has_cmd("exabgp"):
        return False
    try:
        return (
            subprocess.run(
                ["exabgp", "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


require_exabgp = pytest.mark.skipif(
    not _exabgp_usable(),
    reason="ExaBGP daemon not available (broken vendored six on Py3.12)",
)

require_mimidump = pytest.mark.skipif(
    not has_cmd("mimidump"),
    reason="interface captures rely on mimidump which is not shipped",
)
