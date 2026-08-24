import argparse
import glob
import os
import re
import shutil
import sys

# For imports to work during setup and afterwards
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import identify_distribution, sh, supported_distributions

MininetVersion = "2.3.0"
FRRoutingVersion = "7.5"
LibyangVersion = "v1.0.215"
ExaBGPVersion = "4.2.11"

# XXX: We need the explicit script until the following issue is fixed:
#      https://github.com/mininet/mininet/issues/1120
MininetInstallCommit = "c3ba039a9781c6c5f475b7c88ff577185747a1da"

os.environ["PATH"] = "{}:/sbin:/usr/sbin/:/usr/local/sbin".format(os.environ["PATH"])


def parse_args():
    parser = argparse.ArgumentParser(description="Install IPMininet with"
                                                 " its dependencies")
    parser.add_argument("-o", "--output-dir",
                        help="Path to the directory that will store the"
                             " dependencies", default=os.environ["HOME"])
    parser.add_argument("-i", "--install-ipmininet", help="Install IPMininet",
                        action="store_true")
    parser.add_argument("-m", "--install-mininet",
                        help="Install the last version of mininet"
                             " and its dependencies",
                        action="store_true")
    parser.add_argument("-a", "--all", help="Install all daemons",
                        action="store_true")
    parser.add_argument("-q", "--install-frrouting",
                        help=f"Install FRRouting (version {FRRoutingVersion}) daemons",
                        action="store_true")
    parser.add_argument("--install-frrouting-compile",
                        help="Install FRRouting to /opt/compiled-frr for multi-stage builds",
                        action="store_true")
    parser.add_argument("-e", "--install-exabgp",
                        help=f"Install ExaBGP (version {ExaBGPVersion}) daemon",
                        action="store_true")
    parser.add_argument("-r", "--install-radvd",
                        help="Install the RADVD daemon", action="store_true")
    parser.add_argument("-s", "--install-sshd",
                        help="Install the OpenSSH server", action="store_true")
    parser.add_argument("-n", "--install-named",
                        help="Install the Named daemon", action="store_true")
    parser.add_argument("-6", "--enable-ipv6", help="Enable IPv6",
                        action="store_true")
    parser.add_argument("-f", "--install-openr",
                        help="Install OpenR. OpenR is not installed with '-a'"
                             " option since the build takes quite long. We"
                             " also experienced that the build requires a"
                             " substantial amount of memory (~4GB).",
                        action="store_true")
    return parser.parse_args()


def install_mininet(output_dir: str, pip_install=True):
    dist.install("git")

    mininet_dir = os.path.join(output_dir, "mininet")
    if not os.path.isdir(mininet_dir):
        sh("git clone https://github.com/mininet/mininet.git", cwd=output_dir)

    if pip_install:
        # Full install: use a pinned install.sh, then pip-install
        if dist.NAME == "Fedora":
            mininet_opts = "-fnp"
            dist.install("openvswitch", "openvswitch-devel", "openvswitch-test")
            sh("systemctl enable openvswitch")
            sh("systemctl start openvswitch")
        else:
            mininet_opts = "-a"

        sh(f"git checkout {MininetInstallCommit}",
           cwd=os.path.join(mininet_dir, "util"))
        sh("cp install.sh install.tmp.sh",
           cwd=os.path.join(mininet_dir, "util"))
        sh(f"git checkout {MininetVersion}",
           cwd=os.path.join(mininet_dir, "util"))
        sh("mv install.tmp.sh install.sh",
           cwd=os.path.join(mininet_dir, "util"))
        sh(f"./install.sh {mininet_opts} -s .",
           cwd=os.path.join(mininet_dir, "util"))
        dist.pip_install("mininet/", cwd=output_dir)
    else:
        # Minimal: checkout version, build only mnexec binary
        sh(f"git checkout {MininetVersion}",
           cwd=mininet_dir)
        sh("make mnexec", cwd=mininet_dir)
        sh("cp mnexec /usr/local/bin/",
           cwd=mininet_dir)


def make_cmd() -> str:
    """Build with all available cores by default (single machine)."""
    try:
        nproc = len(os.sched_getaffinity(0)) - 1 or 1
    except OSError:
        nproc = 1
    return f"make -j{nproc}"


def install_libyang(output_dir: str, install_prefix: str = "/usr"):
    dist.install("git", "cmake")
    if dist.NAME in {"Ubuntu", "Debian"}:
        dist.install("libpcre3-dev")
    elif dist.NAME == "Fedora":
        dist.install("pcre-devel")

    libyang_dir = os.path.join(output_dir, "libyang")

    installed = glob.glob(os.path.join(install_prefix, "lib", "**", "libyang.so"), recursive=True)
    if installed:
        print(f"libyang already installed to {install_prefix}, skipping")
        return

    cache = "/opt/ipmininet-archives/libyang.tar.gz"
    if os.path.exists(cache):
        sh(f"tar -xzf {cache} -C {output_dir}")
        src = os.path.join(output_dir, "libyang-1.0.215")
        if os.path.isdir(src) and not os.path.isdir(libyang_dir):
            os.rename(src, libyang_dir)
    else:
        sh("git clone https://github.com/CESNET/libyang.git", cwd=output_dir)
        sh(f"git checkout {LibyangVersion}", cwd=libyang_dir)

    sh("mkdir -p build", cwd=libyang_dir)
    sh(f'cmake -DENABLE_LYD_PRIV=ON -DCMAKE_INSTALL_PREFIX:PATH={install_prefix} -D CMAKE_BUILD_TYPE:String="Release" ..',
       make_cmd(), f"{make_cmd()} install", cwd=os.path.join(libyang_dir, "build"))


def link_to_standard_dir(base_dir: str, standard_dir: str):
    for root, _, files in os.walk(base_dir):
        for f in files:
            link = os.path.join(standard_dir, os.path.basename(f))
            if os.path.exists(link):
                os.remove(link)
            os.symlink(os.path.join(root, f), link)
        break


def install_frrouting(output_dir: str, compile_prefix: str | None = None):
    dist.install("autoconf", "automake", "libtool", "make", "gcc", "groff",
                 "patch", "make", "bison", "flex", "gawk", "texinfo",
                 "python3-pytest")

    if dist.NAME in {"Ubuntu", "Debian"}:
        dist.install("libreadline-dev", "libc-ares-dev", "libjson-c-dev",
                     "perl", "python3-dev", "libpam0g-dev", "libsystemd-dev",
                     "libsnmp-dev", "pkg-config", "libcap-dev")
    elif dist.NAME == "Fedora":
        dist.install("readline-devel", "c-ares-devel", "json-c-devel",
                     "perl-core", "python3-devel", "pam-devel", "systemd-devel",
                     "net-snmp-devel", "pkgconfig", "libcap-devel")

    # Always install libyang to /usr/ so FRRouting can find it via pkg-config
    install_libyang(output_dir, install_prefix="/usr")

    frrouting_install = compile_prefix or os.path.join(output_dir, "frr")
    sentinel = os.path.join(frrouting_install, "sbin", "zebra")
    if not os.path.isfile(sentinel) and not compile_prefix:
        sentinel = "/usr/sbin/zebra"
    if os.path.isfile(sentinel):
        print("FRRouting already installed, skipping")
        return

    frrouting_src = os.path.join(output_dir, f"frr-{FRRoutingVersion}")
    frrouting_tar = frrouting_src + ".tar.gz"
    cache = "/opt/ipmininet-archives/frr.tar.gz"
    if os.path.exists(cache):
        sh(f"cp {cache} {frrouting_tar}")
    else:
        sh(f"wget https://github.com/FRRouting/frr/releases/download/frr-{FRRoutingVersion}/"
           f"frr-{FRRoutingVersion}.tar.gz -O {frrouting_tar}",
           cwd=output_dir)
    sh(f"tar -zxvf '{frrouting_tar}'", cwd=output_dir)

    sh(f"./configure '--prefix={frrouting_install}'",
       make_cmd(),
       f"{make_cmd()} install",
       cwd=frrouting_src)

    if not compile_prefix:
        # In normal mode (not multi-stage compile), set up groups and symlinks
        sh("groupadd frr", may_fail=True)
        sh("groupadd frrvty", may_fail=True)
        sh("usermod -a -G frr root", may_fail=True)
        sh("usermod -a -G frrvty root", may_fail=True)

        for curr_dir in ("sbin", "bin"):
            link_to_standard_dir(os.path.join(frrouting_install, curr_dir), f"/usr/{curr_dir}")


def install_openr(output_dir: str, may_fail=False):
    # It's not possible to get a build script with pinned dependencies from the
    # OpenR github repository. The checked-in build script has the dependencies
    # pinned manually. Builds and installs OpenR release rc-20190419-11514.
    # https://github.com/facebook/openr/releases/tag/rc-20190419-11514
    script_name = "build_openr-rc-20190419-11514.sh"
    openr_buildscript = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     script_name)
    # Execute build script
    p = sh(openr_buildscript,
           cwd=output_dir,
           shell=True,
           executable="/bin/bash",
           may_fail=may_fail)
    # We should end here only if may_fail is True
    if p.returncode != 0:
        print("WARNING: Ignoring failed OpenR installation.", file=sys.stderr)


def install_exabgp(output_dir: str, may_fail=False):
    git_url = "https://github.com/Exa-Networks/exabgp.git"
    exabgp_src_folder = f"exabgp-{ExaBGPVersion}-src"
    exabgp_path_src_dir = os.path.join(output_dir, exabgp_src_folder)
    exabgp_self_executable = os.path.join(output_dir, "exabgp")
    final_link = "/usr/sbin/exabgp"

    sh(f"git clone {git_url} {exabgp_src_folder}",
       cwd=output_dir, may_fail=may_fail)

    sh(f"git checkout {ExaBGPVersion}", cwd=exabgp_path_src_dir, may_fail=may_fail)

    # create self-contained executable
    sh(f'python3 -m zipapp -o {exabgp_self_executable} -m exabgp.application:main  -p "/usr/bin/env python3" lib'
       , cwd=exabgp_path_src_dir, may_fail=may_fail)

    if os.path.exists(final_link):
        os.remove(final_link)
    os.symlink(exabgp_self_executable, final_link)


def update_grub():
    if dist.NAME == "Fedora":
        cmd = "grub2-mkconfig --output=/boot/grub2/grub.cfg"
    elif dist.NAME in {"Ubuntu", "Debian"}:
        cmd = "update-grub"
    else:
        return
    # Split cmd to get the executable name for the existence check
    executable = cmd.split()[0]
    if not shutil.which(executable):
        print(f"{executable} not found, skipping grub update", file=sys.stderr)
        return
    sh(cmd, may_fail=True)


def enable_ipv6():
    if dist.NAME == "Debian":
        dist.install("grub-common")

    grub_cfg = "/etc/default/grub"
    if not os.path.exists(grub_cfg):
        print(f"Skipping IPv6 grub configuration: {grub_cfg} not present"
              " (e.g. inside a container)", file=sys.stderr)
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
    sh("sysctl -p", may_fail=True)


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
