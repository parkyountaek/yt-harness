"""Native Windows backend: winget or Scoop for packages. No shared sandbox yet.

yt-setup works here (tools, git hooks, local layer, runtime plugin registration),
so a Windows machine can edit and commit the skeleton. Spawning sub-sessions does
not: there is no sandbox backend and no tmux. Run the harness inside WSL2 instead,
where the Linux backend applies. Not yet verified on a Windows machine.
"""
import shutil
import subprocess

NAME = "windows"

# winget exits with APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE when nothing is newer.
WINGET_NO_UPDATE = (0x8A15002B, 0x8A15002B - 2**32)
WINGET_FLAGS = ["--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements"]


def package_manager():
    for pm in ("winget", "scoop"):
        if shutil.which(pm):
            return pm
    return None


def _run(verb, packages):
    if not packages:
        return 0
    pm = package_manager()
    if pm is None:
        print("Neither winget nor Scoop was found. Install App Installer from the Microsoft Store "
              "(winget) or Scoop (https://scoop.sh), then rerun yt-setup.")
        return 1
    if pm == "scoop":
        return subprocess.call(["scoop", "update" if verb == "upgrade" else "install", *packages], shell=True)
    rc = 0
    for pkg in packages:  # winget takes one --id per call
        r = subprocess.call(["winget", verb, "--id", pkg, *WINGET_FLAGS])
        if r != 0 and not (verb == "upgrade" and r in WINGET_NO_UPDATE):
            rc = r
    return rc


def install(packages):
    return _run("install", packages)


def upgrade(packages):
    return _run("upgrade", packages)


def sandbox_problem():
    return ("Native Windows has no shared sandbox backend. Install WSL2 (wsl --install), "
            "clone the repo inside it, and run yt-setup and yt-spawn from the WSL2 shell.")


def sandbox_argv(policy, runtime, cmd, profile_dir=None, extra_read=(), tmp_dir=None, cwd=None):
    raise NotImplementedError(sandbox_problem())
