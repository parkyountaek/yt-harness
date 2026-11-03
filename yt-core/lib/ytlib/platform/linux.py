"""Linux and WSL2 backend: apt or dnf for packages, bubblewrap for the shared sandbox.

Not yet verified on a Linux machine. The sandbox backend is a stub until the
equivalence tests run on Linux.
"""
import os
import shutil
import subprocess

NAME = "linux"


def package_manager():
    for pm in ("apt-get", "dnf"):
        if shutil.which(pm):
            return "apt" if pm == "apt-get" else "dnf"
    return None


def install(packages):
    if not packages:
        return 0
    pm = package_manager()
    if pm is None:
        print("No supported package manager (apt or dnf) found. Install manually: " + " ".join(packages))
        return 1
    sudo = [] if os.geteuid() == 0 else ["sudo"]
    if pm == "apt":
        subprocess.call([*sudo, "apt-get", "update"])
        return subprocess.call([*sudo, "apt-get", "install", "-y", *packages])
    return subprocess.call([*sudo, "dnf", "install", "-y", *packages])


def sandbox_argv(policy, runtime, cmd, profile_dir=None, extra_read=()):
    raise NotImplementedError(
        "The bubblewrap sandbox backend is not implemented yet. "
        "Sub-sessions cannot be spawned on Linux or WSL2 until it is.")
