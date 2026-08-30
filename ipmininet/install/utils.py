import os
import shlex
import subprocess
import sys

from distutils.spawn import find_executable


def sh(*cmds, **kwargs) -> subprocess.Popen | None:
    if "stdout" not in kwargs:
        kwargs["stdout"] = subprocess.PIPE
    if "stderr" not in kwargs:
        kwargs["stderr"] = subprocess.STDOUT
    may_fail = kwargs.pop("may_fail", False)
    output_stdout = kwargs.pop("output_stdout", True)
    env = kwargs.pop("env", os.environ)
    env["LC_ALL"] = "C"

    p = None
    for cmd in cmds:
        print("\n*** " + cmd)
        try:
            p = subprocess.Popen(shlex.split(cmd), env=env, **kwargs)
        except OSError as e:
            if not may_fail:
                raise
            sys.stderr.write("*** failed to run %s: %s\n" % (cmd, e))
            continue

        if output_stdout:
            while p.poll() is None:
                out = p.stdout.readline()
                if out != "":
                    sys.stdout.write(out.decode("utf-8"))

            out = p.stdout.read()
            if out != "":
                sys.stdout.write(out.decode("utf-8"))

            if p.poll() != 0:
                if not may_fail:
                    sys.exit(1)
                return p
    return p


class Distribution:
    NAME = None  # type: Optional[str]
    INSTALL_CMD = None  # type: Optional[str]
    UPDATE_CMD = None  # type: Optional[str]
    PIP_CMD = "pip"
    SpinPipVersion = "18.1"

    def __init__(self):
        self.pip_args = self.check_pip_version(self.PIP_CMD)

    def check_pip_version(self, pip: str) -> str:
        from packaging.version import parse as parse_version

        if find_executable(pip) is None:
            return ""
        p = sh("%s -V" % pip, output_stdout=False)
        if p is None or p.wait() != 0:
            print("Print cannot get the version of %s" % pip)
            return ""
        content, _ = p.communicate()
        try:
            v = content.decode("utf-8").split(" ")[1]

            if parse_version(v) >= parse_version(self.SpinPipVersion):
                return ""
            return "--process-dependency-links"
        except (ValueError, IndexError):
            print("Cannot retrieve version number of %s" % pip)
            sys.exit(1)

    def install(self, *packages: str):
        if self.INSTALL_CMD:
            sh(self.INSTALL_CMD + " " + " ".join(packages))

    def update(self):
        sh(self.UPDATE_CMD)

    def pip_install(self, *packages: str, **kwargs):
        if find_executable(self.PIP_CMD) is not None:
            sh(
                self.PIP_CMD
                + " -q install "
                + self.pip_args
                + " "
                + " ".join(packages),
                **kwargs,
            )

    def require_pip(self):
        if find_executable(self.PIP_CMD) is None:
            raise RuntimeError("Cannot find %s" % self.PIP_CMD)


class Ubuntu(Distribution):
    NAME = "Ubuntu"
    INSTALL_CMD = "apt-get -y -q install"
    UPDATE_CMD = "apt-get update"
    PIP_CMD = "pip3"


class Debian(Distribution):
    NAME = "Debian"
    INSTALL_CMD = "apt-get -y -q install"
    UPDATE_CMD = "apt-get update"
    PIP_CMD = "pip3"


class Fedora(Distribution):
    NAME = "Fedora"
    INSTALL_CMD = "yum -y install"
    UPDATE_CMD = "true"
    PIP_CMD = "pip"


def supported_distributions() -> list[type]:
    return Distribution.__subclasses__()


def identify_distribution() -> Distribution | None:
    try:
        subprocess.check_call(shlex.split("grep Ubuntu /etc/lsb-release"))
        return Ubuntu()
    except subprocess.CalledProcessError:
        pass

    if os.path.exists("/etc/debian_version"):
        return Debian()

    if os.path.exists("/etc/fedora-release"):
        return Fedora()

    return None
