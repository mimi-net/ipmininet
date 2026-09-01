import argparse
import hashlib
import os
import re
import sys
import sysconfig
import urllib.request

# For imports to work during setup and afterwards
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import find_executable, identify_distribution, sh, supported_distributions

MininetVersion = "2.3.0"
FRRoutingVersion = "7.5"
LibyangVersion = "v1.0.215"
ExaBGPVersion = "4.2.25"

# PCRE1 (libpcre3) is required to build libyang v1, which FRRouting pins to.
# Ubuntu 26.04 and newer dropped the obsolete PCRE1 packages, so the installer
# builds this release from source there.
PcreVersion = "8.45"
PcreSha256 = "4e6ce03e0336e8b4a3d6c2b70b1c5e18590a5673a98186da90d4f33c23defc09"
PcreUrl = "https://downloads.sourceforge.net/project/pcre/pcre/8.45/pcre-8.45.tar.gz"

# XXX: We need the explicit script until the following issue is fixed:
#      https://github.com/mininet/mininet/issues/1120
MininetInstallCommit = "c3ba039a9781c6c5f475b7c88ff577185747a1da"

os.environ["PATH"] = "{}:/sbin:/usr/sbin/:/usr/local/sbin".format(os.environ["PATH"])


def _needs_rebuild(*paths: str) -> bool:
    """Return True when a component must be (re)built: one of its artifacts is
    missing or the user requested a forced rebuild (IPMININET_FORCE_INSTALL=1).
    """
    return os.environ.get("IPMININET_FORCE_INSTALL") == "1" or not all(
        os.path.exists(p) for p in paths
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
    parser.add_argument(
        "-f",
        "--install-openr",
        help="Install OpenR. OpenR is not installed with '-a'"
        " option since the build takes quite long. We"
        " also experienced that the build requires a"
        " substantial amount of memory (~4GB).",
        action="store_true",
    )
    return parser.parse_args()


def install_mininet(output_dir: str, pip_install=True):
    dist.install("git")
    if dist.NAME in {"Ubuntu", "Debian"}:
        dist.install("openvswitch-switch")

    if dist.NAME == "Fedora":
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


def ensure_pcre1(dist, output_dir: str) -> None:
    """Provide the PCRE1 library needed to build libyang.

    libyang v1, which FRRouting requires, is built against PCRE1 (libpcre3 on
    Debian/Ubuntu). Ubuntu 26.04 and newer dropped the obsolete PCRE1 packages,
    so fall back to building PCRE from source when the distro does not ship it.
    """
    if dist.NAME == "Fedora":
        dist.install("pcre-devel")
        return
    if dist.NAME not in ("Ubuntu", "Debian") or find_executable("pcre-config"):
        return
    p = sh("apt-get -y -q install libpcre3-dev", may_fail=True)
    if p is not None and p.wait() == 0:
        return
    if find_executable("pcre-config"):
        return
    print("IPMininet: libpcre3-dev is unavailable, building PCRE from source")
    pcre_archive = os.path.join(output_dir, f"pcre-{PcreVersion}.tar.gz")
    pcre_src = os.path.join(output_dir, f"pcre-{PcreVersion}")
    if not os.path.exists(pcre_archive):
        urllib.request.urlretrieve(PcreUrl, pcre_archive)
        with open(pcre_archive, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if digest != PcreSha256:
            raise RuntimeError(
                f"PCRE {PcreVersion} download has an unexpected SHA-256 digest: {digest}"
            )
    sh(f"rm -rf {pcre_src}", f"tar -xzf {pcre_archive}", cwd=output_dir)
    # --enable-unicode-properties: FRR 7.5's bundled YANG (ietf-inet-types)
    # regexes use \\p{...}, which is only compiled in with UCP support.
    sh(
        "./configure --prefix=/usr --enable-utf8 --enable-unicode-properties",
        f"make -j{os.cpu_count() or 1}",
        "make install",
        cwd=pcre_src,
    )
    sh("ldconfig")


def install_libyang(output_dir: str):
    if not _needs_rebuild("/usr/bin/yanglint"):
        print("IPMininet: libyang already installed; skipping build")
        return
    dist.install("git", "cmake")
    ensure_pcre1(dist, output_dir)

    sh(
        "rm -rf libyang",
        "git clone https://github.com/CESNET/libyang.git",
        cwd=output_dir,
    )
    cloned_repo = os.path.join(output_dir, "libyang")
    sh(f"git checkout {LibyangVersion}", "mkdir build", cwd=cloned_repo)
    # CMake 4.x removed compatibility with versions < 3.5, but libyang v1.0.x
    # still declares cmake_minimum_required(2.8.12); the policy-version escape
    # hatch lets it configure (and is ignored by older CMake).
    sh(
        "cmake -DENABLE_LYD_PRIV=ON -DCMAKE_INSTALL_PREFIX:PATH=/usr"
        " -DCMAKE_POLICY_VERSION_MINIMUM=3.5"
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
        "make",
        "bison",
        "flex",
        "gawk",
        "texinfo",
        "python3-pytest",
    )

    if dist.NAME == "Ubuntu" or dist.NAME == "Debian":
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
        )
    elif dist.NAME == "Fedora":
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
        )

    install_libyang(output_dir)

    frrouting_install = os.path.join(output_dir, "frr")
    if _needs_rebuild(os.path.join(frrouting_install, "sbin", "zebra")):
        frrouting_src = os.path.join(output_dir, f"frr-{FRRoutingVersion}")
        frrouting_tar = frrouting_src + ".tar.gz"
        sh(
            f"wget https://github.com/FRRouting/frr/releases/download/frr-{FRRoutingVersion}/"
            f"frr-{FRRoutingVersion}.tar.gz",
            f"tar -zxvf '{frrouting_tar}'",
            cwd=output_dir,
        )

        env = dict(os.environ)
        python_libdir = _python_lib_dir()
        if python_libdir:
            env["LD_LIBRARY_PATH"] = os.pathsep.join(
                filter(None, [python_libdir, env.get("LD_LIBRARY_PATH")])
            )
        sh(
            f"./configure '--prefix={frrouting_install}'",
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


def install_openr(output_dir: str, may_fail=False):
    # It's not possible to get a build script with pinned dependencies from the
    # OpenR github repository. The checked-in build script has the dependencies
    # pinned manually. Builds and installs OpenR release rc-20190419-11514.
    # https://github.com/facebook/openr/releases/tag/rc-20190419-11514
    script_name = "build_openr-rc-20190419-11514.sh"
    openr_buildscript = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), script_name
    )
    # Execute build script
    p = sh(
        openr_buildscript,
        cwd=output_dir,
        shell=True,
        executable="/bin/bash",
        may_fail=may_fail,
    )
    # We should end here only if may_fail is True
    if p.returncode != 0:
        print("WARNING: Ignoring failed OpenR installation.", file=sys.stderr)


def install_exabgp(output_dir: str, may_fail=False):
    git_url = "https://github.com/Exa-Networks/exabgp.git"
    exabgp_src_folder = f"exabgp-{ExaBGPVersion}-src"
    exabgp_path_src_dir = os.path.join(output_dir, exabgp_src_folder)
    exabgp_self_executable = os.path.join(output_dir, "exabgp")
    final_link = "/usr/sbin/exabgp"

    if not _needs_rebuild(exabgp_self_executable, final_link):
        print("IPMininet: ExaBGP already installed; skipping build")
        return

    sh(
        f"rm -rf {exabgp_src_folder}",
        f"git clone {git_url} {exabgp_src_folder}",
        cwd=output_dir,
        may_fail=may_fail,
    )

    sh(f"git checkout {ExaBGPVersion}", cwd=exabgp_path_src_dir, may_fail=may_fail)

    # create self-contained executable
    sh(
        f'python3 -m zipapp -o {exabgp_self_executable} -m exabgp.application:main  -p "/usr/bin/env python3" lib',
        cwd=exabgp_path_src_dir,
        may_fail=may_fail,
    )

    if os.path.lexists(final_link):
        os.remove(final_link)
    os.symlink(exabgp_self_executable, final_link)


def update_grub():
    if dist.NAME == "Fedora":
        cmd = "grub2-mkconfig --output=/boot/grub2/grub.cfg"
    elif dist.NAME == "Ubuntu" or dist.NAME == "Debian":
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
