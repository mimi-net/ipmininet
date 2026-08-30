"""This module defines an sshd configuration."""

import os
import subprocess
import tempfile

from distutils.spawn import find_executable

from .base import Daemon

# Generate a new ssh keypair at each run
KEYFILE = tempfile.mktemp(dir="/tmp")
PUBKEY = "%s.pub" % KEYFILE
if os.path.exists(KEYFILE):
    os.unlink(KEYFILE)
if os.path.exists(PUBKEY):
    os.unlink(PUBKEY)
subprocess.call(
    ["ssh-keygen", "-b", "2048", "-t", "rsa", "-f", KEYFILE, "-q", "-P", ""]
)


class SSHd(Daemon):
    NAME = "sshd"
    STARTUP_LINE_BASE = f"{find_executable(NAME)} -D -u0"
    KILL_PATTERNS = (STARTUP_LINE_BASE,)

    @property
    def startup_line(self):
        return f"{self.STARTUP_LINE_BASE} -f {os.path.abspath(self.cfg_filename)}"

    @property
    def dry_run(self):
        return "%s -t" % self.startup_line

    def set_defaults(self, defaults):
        super().set_defaults(defaults)

    def build(self):
        cfg = super().build()
        cfg.authorized_keys = PUBKEY
        return cfg
