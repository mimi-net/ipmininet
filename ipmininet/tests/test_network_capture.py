""" "This module test the Link Failure API"""

import os
import tempfile
import threading
import time
from contextlib import contextmanager

import pytest

from ipmininet.clean import cleanup
from ipmininet.ipnet import IPNet
from ipmininet.overlay import (
    _PCAP_GLOBAL_HEADER_SIZE,
    _PCAP_MAGIC_BE,
    _PCAP_MAGIC_LE,
    _PCAPNG_MAGIC,
    _PCAPNG_SECTION_HEADER_SIZE,
    NetworkCapture,
)

from ..examples.network_capture import NetworkCaptureTopo
from . import require_mimidump, require_root
from .utils import assert_connectivity


@require_mimidump
@require_root
def test_network_capture_example():
    try:
        net = IPNet(topo=NetworkCaptureTopo())
        net.start()
        overlay = next(o for o in net.topo.overlays if isinstance(o, NetworkCapture))

        # Capture readiness is asynchronous; wait for it instead of asserting
        # file existence immediately after net.start().
        assert overlay.wait_until_capturing("r2-eth0", timeout=10)
        assert overlay.wait_until_capturing("s2-eth1", timeout=10)
        assert overlay.wait_until_capturing("r1", timeout=10)
        assert overlay.wait_until_capturing("s1", timeout=10)

        # Check example connectivity
        assert_connectivity(net, v6=False)
        assert_connectivity(net, v6=True)

        net.stop()
    finally:
        cleanup()


@require_mimidump
@require_root
def test_network_capture_wait_until_capturing():
    try:
        net = IPNet(topo=NetworkCaptureTopo())
        net.start()
        overlay = next(o for o in net.topo.overlays if isinstance(o, NetworkCapture))

        # Captures on interfaces (mimidump) become live once the READY signal
        # is received
        assert overlay.wait_until_capturing("r2-eth0", timeout=10)
        assert overlay.wait_until_capturing("s2-eth1", timeout=10)

        # Captures on nodes (tcpdump) become live once their output file exists
        assert overlay.wait_until_capturing("r1", timeout=10)
        assert overlay.wait_until_capturing("s1", timeout=10)

        # Captures that were never started are not live
        assert not overlay.wait_until_capturing("does-not-exist", timeout=1)

        net.stop()
    finally:
        cleanup()


class _FakeProc:
    """Popen stand-in that stays alive until poll() is called."""

    def __init__(self, exit_code=None):
        self._exit_code = exit_code

    def poll(self):
        return self._exit_code


_HEADER = _PCAP_GLOBAL_HEADER_SIZE
_GROWTH = 64
_TIMEOUT = 0.5


class TestWaitUntilCapturingStrict:
    """Rootless unit tests for wait_until_capturing(..., strict=True).

    The matrix locks the strict contract: READY on stderr is live; a bare
    pcap/pcapng header-only file is not; data past the header is live, whether
    the file grows between two polls or is already stable past the header (the
    bursty-writer case where the whole exchange landed before the first poll);
    and the default (non-strict) mode still accepts bare file existence for
    backward compatibility.

    A ``tempfile.TemporaryDirectory`` is used instead of the ``tmp_path``
    fixture: the xdist workers run in a private mount namespace with a fresh
    ``/tmp`` (scripts/py-unshare.sh), so pytest's basetemp directory does not
    survive into the worker.
    """

    @staticmethod
    @contextmanager
    def _overlay(ready=False, total=0, magic=_PCAP_MAGIC_LE, exit_code=None):
        overlay = NetworkCapture()
        with tempfile.TemporaryDirectory() as tmp:
            overlay._stderr_lines["eth0"] = [b"READY"] if ready else []
            output_file = os.path.join(tmp, "cap.pcap")
            overlay._output_files["eth0"] = output_file
            if total:
                with open(output_file, "wb") as f:
                    f.write(magic[:total])
                    f.write(b"\0" * max(0, total - len(magic)))
            overlay.ongoing_captures["eth0"] = _FakeProc(exit_code)
            yield overlay

    @pytest.mark.parametrize(
        "strict,ready,total,magic,expected",
        [
            (False, False, _HEADER, _PCAP_MAGIC_LE, True),
            (True, True, 0, _PCAP_MAGIC_LE, True),
            (True, False, _HEADER, _PCAP_MAGIC_LE, False),
            (True, False, _PCAPNG_SECTION_HEADER_SIZE, _PCAPNG_MAGIC, False),
            (True, False, 20, _PCAP_MAGIC_LE, False),
            (True, False, _HEADER + _GROWTH, _PCAP_MAGIC_BE, True),
        ],
    )
    def test_wait_until_capturing(self, strict, ready, total, magic, expected):
        with self._overlay(ready=ready, total=total, magic=magic) as overlay:
            assert (
                overlay.wait_until_capturing("eth0", timeout=_TIMEOUT, strict=strict)
                is expected
            )

    @pytest.mark.parametrize(
        "magic,header",
        [(_PCAP_MAGIC_LE, _HEADER), (_PCAPNG_MAGIC, _PCAPNG_SECTION_HEADER_SIZE)],
    )
    def test_strict_accepts_growth_between_polls(self, magic, header):
        with self._overlay(total=header, magic=magic) as overlay:

            def _grow():
                time.sleep(0.15)
                with open(overlay._output_files["eth0"], "ab") as f:
                    f.write(b"\0" * _GROWTH)

            threading.Thread(target=_grow, daemon=True).start()
            assert overlay.wait_until_capturing("eth0", timeout=_TIMEOUT, strict=True)

    def test_dead_process_is_not_live(self):
        with self._overlay(total=_HEADER, exit_code=1) as overlay:
            assert not overlay.wait_until_capturing(
                "eth0", timeout=_TIMEOUT, strict=True
            )
