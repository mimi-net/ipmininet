import argparse
import os
import re
import sys
import sysconfig

# For imports to work during setup and afterwards
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import find_executable, identify_distribution, sh, supported_distributions

MininetVersion = "2.3.0"
FRRoutingVersion = "10.7.1"
LibyangVersion = "v3.13.6"
ExaBGPVersion = "5.0.13"

# XXX: We need the explicit script until the following issue is fixed:
#      https://github.com/mininet/mininet/issues/1120
MininetInstallCommit = "c3ba039a9781c6c5f475b7c88ff577185747a1da"

os.environ["PATH"] = "{}:/sbin:/usr/sbin/:/usr/local/sbin".format(os.environ["PATH"])


def _needs_rebuild(*paths: str | None) -> bool:
    """Return True when a component must be (re)built: one of its artifacts is
    missing or the user requested a forced rebuild (IPMININET_FORCE_INSTALL=1).
    """
    return os.environ.get("IPMININET_FORCE_INSTALL") == "1" or not all(
        p is not None and os.path.exists(p) for p in paths
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Install IPMininet with its dependencies"
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        help="Path to the directory that will store the dependencies",
        default=os.environ["HOME"],
    )
    parser.add_argument(
        "-i", "--install-ipmininet", help="Install IPMininet", action="store_true"
    )
    parser.add_argument(
        "-m",
        "--install-mininet",
        help="Install the last version of mininet and its dependencies",
        action="store_true",
    )
    parser.add_argument("-a", "--all", help="Install all daemons", action="store_true")
    parser.add_argument(
        "-q",
        "--install-frrouting",
        help=f"Install FRRouting (version {FRRoutingVersion}) daemons",
        action="store_true",
    )
    parser.add_argument(
        "-e",
        "--install-exabgp",
        help=f"Install ExaBGP (version {ExaBGPVersion}) daemon",
        action="store_true",
    )
    parser.add_argument(
        "-r", "--install-radvd", help="Install the RADVD daemon", action="store_true"
    )
    parser.add_argument(
        "-s", "--install-sshd", help="Install the OpenSSH server", action="store_true"
    )
    parser.add_argument(
        "-n", "--install-named", help="Install the Named daemon", action="store_true"
    )
    parser.add_argument("-6", "--enable-ipv6", help="Enable IPv6", action="store_true")
    return parser.parse_args()


def install_mininet(output_dir: str, pip_install=True):
    dist.install("git")
    if dist.package_family == "apt":
        dist.install("openvswitch-switch")

    if dist.package_family == "rpm":
        mininet_opts = "-fnp"
        dist.install("openvswitch", "openvswitch-devel", "openvswitch-test")
        sh("systemctl enable openvswitch")
        sh("systemctl start openvswitch")
    else:
        mininet_opts = "-a"

    if not pip_install:
        # Minimal install: only build the mnexec binary. The full
        # install.sh -a installs packages (e.g. pep8) that no longer exist
        # on Ubuntu 24.04. The Python package itself is provided by uv
        # (see pyproject.toml) and OVS comes from the openvswitch-switch
        # apt package installed above.
        if _needs_rebuild("/usr/local/bin/mnexec"):
            sh(
                "rm -rf mininet",
                "git clone https://github.com/mininet/mininet.git",
                cwd=output_dir,
            )
            sh(
                f"git checkout {MininetVersion}",
                cwd=os.path.join(output_dir, "mininet"),
            )
            sh("make mnexec", cwd=os.path.join(output_dir, "mininet"))
            sh("cp mnexec /usr/local/bin/", cwd=os.path.join(output_dir, "mininet"))
        return
    if _needs_rebuild(os.path.join(output_dir, "mininet")):
        sh("git clone https://github.com/mininet/mininet.git", cwd=output_dir)
    # Save valid version of mininet install script
    sh(
        f"git checkout {MininetInstallCommit}",
        cwd=os.path.join(output_dir, "mininet/util"),
    )
    sh("cp install.sh install.tmp.sh", cwd=os.path.join(output_dir, "mininet/util"))
    # Use it in the fixed version of Mininet
    sh(f"git checkout {MininetVersion}", cwd=os.path.join(output_dir, "mininet/util"))
    sh("mv install.tmp.sh install.sh", cwd=os.path.join(output_dir, "mininet/util"))
    sh(
        f"./install.sh {mininet_opts} -s .",
        cwd=os.path.join(output_dir, "mininet/util"),
    )

    if pip_install:
        dist.pip_install("mininet/", cwd=output_dir)


def install_libyang(output_dir: str):
    if not _needs_rebuild("/usr/bin/yanglint"):
        print("IPMininet: libyang already installed; skipping build")
        return
    dist.install("git", "cmake")
    # libyang v3, which FRRouting 8+ builds against, needs PCRE2.
    if dist.package_family == "rpm":
        dist.install("pcre2-devel")
    else:
        dist.install("libpcre2-dev")

    sh(
        "rm -rf libyang",
        "git clone https://github.com/CESNET/libyang.git",
        cwd=output_dir,
    )
    cloned_repo = os.path.join(output_dir, "libyang")
    sh(f"git checkout {LibyangVersion}", "mkdir build", cwd=cloned_repo)
    sh(
        "cmake -DENABLE_LYD_PRIV=ON -DCMAKE_INSTALL_PREFIX:PATH=/usr"
        ' -D CMAKE_BUILD_TYPE:String="Release" ..',
        "make",
        "make install",
        cwd=os.path.join(cloned_repo, "build"),
    )


def link_to_standard_dir(base_dir: str, standard_dir: str):
    for root, _, files in os.walk(base_dir):
        for f in files:
            link = os.path.join(standard_dir, os.path.basename(f))
            if os.path.exists(link):
                os.remove(link)
            os.symlink(os.path.join(root, f), link)
        break


def _python_lib_dir() -> str | None:
    """Directory holding the shared libpython of the running interpreter.

    FRR's build-time `clippy` tool embeds the Python that configured it. When
    that interpreter is a uv-managed CPython (as in the test container), its
    libpython lives outside the loader's default search path, so expose it via
    LD_LIBRARY_PATH during the build.
    """
    libdir = sysconfig.get_config_var("LIBDIR")
    if libdir and os.path.isdir(libdir):
        return libdir
    libdir = os.path.join(sys.base_prefix, "lib")
    return libdir if os.path.isdir(libdir) else None


def install_frrouting(output_dir: str):
    dist.install(
        "autoconf",
        "automake",
        "libtool",
        "make",
        "gcc",
        "groff",
        "patch",
        "bison",
        "flex",
        "gawk",
        "texinfo",
        "python3-pytest",
    )

    if dist.package_family == "apt":
        dist.install(
            "libreadline-dev",
            "libc-ares-dev",
            "libjson-c-dev",
            "perl",
            "python3-dev",
            "libpam0g-dev",
            "libsystemd-dev",
            "libsnmp-dev",
            "pkg-config",
            "libcap-dev",
            "libelf-dev",
            "libunwind-dev",
            "python3-sphinx",
        )
    elif dist.package_family == "rpm":
        dist.install(
            "readline-devel",
            "c-ares-devel",
            "json-c-devel",
            "perl-core",
            "python3-devel",
            "pam-devel",
            "systemd-devel",
            "net-snmp-devel",
            "pkgconfig",
            "libcap-devel",
            "elfutils-libelf-devel",
            "libunwind-devel",
        )

    install_libyang(output_dir)

    frrouting_install = os.path.join(output_dir, "frr")
    if _needs_rebuild(os.path.join(frrouting_install, "sbin", "zebra")):
        frrouting_src = os.path.join(output_dir, f"frr-{FRRoutingVersion}")
        frrouting_tar = frrouting_src + ".tar.gz"
        # FRRouting no longer ships release assets; use the tag archive. It
        # contains no generated configure, so bootstrap it with autotools.
        sh(
            f"wget https://github.com/FRRouting/frr/archive/refs/tags/frr-{FRRoutingVersion}.tar.gz"
            f" -O '{frrouting_tar}'",
            f"tar -zxvf '{frrouting_tar}'",
            # The tag archive extracts as frr-frr-<version>; normalize it.
            f"mv 'frr-frr-{FRRoutingVersion}' 'frr-{FRRoutingVersion}'",
            cwd=output_dir,
        )

        env = dict(os.environ)
        python_libdir = _python_lib_dir()
        if python_libdir:
            env["LD_LIBRARY_PATH"] = os.pathsep.join(
                filter(None, [python_libdir, env.get("LD_LIBRARY_PATH")])
            )
        sh(
            "./bootstrap.sh",
            # protobuf is a build-time experiment requiring protobuf-c headers;
            # we do not use the gRPC/protobuf northbound plugin.
            # Standard system paths: FRR 9.2+ appends /frr and /run/frr itself.
            f"./configure '--prefix={frrouting_install}'"
            " --sysconfdir=/etc --localstatedir=/var --runstatedir=/var/run"
            " --enable-protobuf=no",
            "make",
            "make install",
            cwd=frrouting_src,
            env=env,
        )

        sh(f"rm -r '{frrouting_src}' '{frrouting_tar}'")

    sh("groupadd frr", may_fail=True)
    sh("groupadd frrvty", may_fail=True)
    sh("usermod -a -G frr root", may_fail=True)
    sh("usermod -a -G frrvty root", may_fail=True)

    for curr_dir in ("sbin", "bin"):
        link_to_standard_dir(
            os.path.join(frrouting_install, curr_dir), f"/usr/{curr_dir}"
        )


def install_exabgp(output_dir: str, may_fail=False):
    # ExaBGP 5.x is a src/ layout Python package installed with pip; its
    # console script lands in the interpreter's bin dir and is already on
    # PATH, so nothing more is needed. Inside a uv-managed virtualenv (CI and
    # the container build) it is installed into that env with `uv pip`, so the
    # runtime image inherits it together with the rest of the venv.
    if not _needs_rebuild(exabgp_executable()):
        print("IPMininet: ExaBGP already installed; skipping build")
        return

    if find_executable("uv") and os.environ.get("VIRTUAL_ENV"):
        sh(f"uv pip install -q exabgp=={ExaBGPVersion}", may_fail=may_fail)
    else:
        dist.pip_install(f"exabgp=={ExaBGPVersion}", may_fail=may_fail)
    if not exabgp_executable():
        print("WARNING: pip did not install the exabgp entry point.", file=sys.stderr)


def exabgp_executable() -> str | None:
    """Return the path to the exabgp console script, if installed."""
    return find_executable("exabgp")


def update_grub():
    if dist.package_family == "rpm":
        cmd = "grub2-mkconfig --output=/boot/grub2/grub.cfg"
    elif dist.package_family == "apt":
        cmd = "update-grub"
    else:
        return
    sh(cmd, may_fail=True)


def enable_ipv6():
    if dist.NAME == "Debian":
        dist.install("grub-common")

    grub_cfg = "/etc/default/grub"
    if not os.path.exists(grub_cfg):
        print(
            f"Skipping IPv6 grub configuration: {grub_cfg} not present"
            " (e.g. inside a container)",
            file=sys.stderr,
        )
        return
    with open(grub_cfg, "r+") as f:
        data = f.read()
        f.seek(0)
        f.write(data.replace("ipv6.disable=1 ", ""))
        f.truncate()
    update_grub()

    sysctl_cfg = "/etc/sysctl.conf"
    with open(sysctl_cfg, "r+") as f:
        data = f.read()
        f.seek(0)
        # Comment out lines
        f.write(re.sub(r"\n(.*disable_ipv6.*)", r"\n#\g<1>", data))
        f.truncate()
    sh("sysctl -p")


# Force root

if os.getuid() != 0:
    print("This program must be run as root")
    sys.exit(1)

# Identify the distribution

dist = identify_distribution()
if dist is None:
    supported = ", ".join([d.NAME for d in supported_distributions()])
    print(f"The installation script only supports {supported}")
    sys.exit(1)
dist.update()
