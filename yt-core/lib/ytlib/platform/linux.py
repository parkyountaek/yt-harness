"""Linux and WSL2 backend: apt or dnf for packages, bubblewrap for the shared sandbox.

The sandbox mirrors the macOS profile by building the filesystem view instead of
denying paths: the root is read-only, $HOME, /home, /tmp, /run and similar are empty
tmpfs mounts, and only the task folder, yt-core, the harness, and the runtime dirs are
mounted back. Verified with tests/sandbox in a Linux container; the Claude and Codex
runtimes themselves have not been run on Linux yet.
"""
import os
import re
import shutil
import subprocess

NAME = "linux"
HOME = os.path.expanduser("~")

RUNTIME_RW = {"claude": [f"{HOME}/.claude", f"{HOME}/.claude.json"], "codex": [f"{HOME}/.codex"]}
RUNTIME_PROTECTED = {
    "claude": [f"{HOME}/.claude/{n}" for n in ("settings.json", "settings.local.json", "CLAUDE.md",
                                                 "keybindings.json", "hooks", "skills", "agents", "commands",
                                                 "plugins", "output-styles")],
    "codex": [f"{HOME}/.codex/{n}" for n in ("config.toml", "hooks.json", "AGENTS.md", "AGENTS.override.md",
                                               "rules", "skills", "plugins", "packages", "prompts", ".tmp")],
}
# Hidden: other sessions' transcripts, history, and the session registry (peer messaging).
RUNTIME_PRIVATE_DIRS = {
    "claude": [f"{HOME}/.claude/{n}" for n in ("projects", "file-history", "backups", "sessions")],
    "codex": [f"{HOME}/.codex/backups"],
}
RUNTIME_PRIVATE_FILES = {"claude": [f"{HOME}/.claude/history.jsonl"], "codex": [f"{HOME}/.codex/history.jsonl"]}
EMPTY_DIRS = ["/home", "/root", "/tmp", "/var/tmp", "/run", "/mnt", "/media", "/srv"]
# Kept inside /run so DNS still resolves.
RUN_KEEP = ["/run/systemd/resolve", "/run/resolvconf", "/run/NetworkManager"]
# Programs that ask something outside the sandbox to run a command for us.
ESCAPE_NAMES = ["ssh", "tmux", "screen", "crontab", "at", "batch", "systemd-run", "xdg-open", "gio",
                "dbus-send", "busctl", "loginctl", "machinectl", "pkexec", "sudo", "su"]


def package_manager():
    for pm in ("apt-get", "dnf"):
        if shutil.which(pm):
            return "apt" if pm == "apt-get" else "dnf"
    return None


def _sudo():
    return [] if os.geteuid() == 0 else ["sudo"]


def _manager_or_none(packages):
    pm = package_manager()
    if pm is None:
        print("No supported package manager (apt or dnf) found. Install manually: " + " ".join(packages))
    return pm


def install(packages):
    if not packages:
        return 0
    pm = _manager_or_none(packages)
    if pm is None:
        return 1
    if pm == "apt":
        subprocess.call([*_sudo(), "apt-get", "update"])
        return subprocess.call([*_sudo(), "apt-get", "install", "-y", *packages])
    return subprocess.call([*_sudo(), "dnf", "install", "-y", *packages])


def upgrade(packages):
    if not packages:
        return 0
    pm = _manager_or_none(packages)
    if pm is None:
        return 1
    if pm == "apt":
        subprocess.call([*_sudo(), "apt-get", "update"])
        return subprocess.call([*_sudo(), "apt-get", "install", "-y", "--only-upgrade", *packages])
    return subprocess.call([*_sudo(), "dnf", "upgrade", "-y", *packages])


def sandbox_problem():
    if not shutil.which("bwrap"):
        return "bubblewrap (bwrap) is missing; run yt-setup"
    r = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--unshare-pid", "--proc", "/proc", "true"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return ("bwrap cannot create a sandbox here (" + (r.stderr.strip().splitlines() or ["?"])[-1] + "). "
                "Unprivileged user namespaces are probably restricted; on Ubuntu 23.10+ allow bwrap through "
                "AppArmor or set kernel.apparmor_restrict_unprivileged_userns=0.")
    return None


def claude_project_dir(cwd):
    return f"{HOME}/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))


def escape_executables():
    found = set()
    for name in ESCAPE_NAMES:
        for d in ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin"):
            p = os.path.join(d, name)
            if os.path.isfile(p) and not os.path.islink(os.path.dirname(p)):
                found.add(os.path.realpath(p))
    return sorted(found)


def sandbox_args(policy, runtime, extra_read=(), tmp_dir=None, cwd=None):
    """bwrap options. Later mounts cover earlier ones."""
    a = ["--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
         "--unshare-cgroup-try", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    for d in EMPTY_DIRS:
        if os.path.isdir(d) and not os.path.islink(d):
            a += ["--tmpfs", d]
    for d in RUN_KEEP:
        a += ["--ro-bind-try", d, d]
    if not any(HOME == d or HOME.startswith(d + "/") for d in EMPTY_DIRS):
        a += ["--tmpfs", HOME]
    a += ["--dir", HOME]
    for p in [*policy.get("read", []), *extra_read]:
        a += ["--ro-bind-try", p.rstrip("/"), p.rstrip("/")]
    for p in RUNTIME_RW.get(runtime, []):
        a += ["--bind-try", p, p]
    for p in [*policy.get("write", []), *([tmp_dir] if tmp_dir else [])]:
        os.makedirs(p, exist_ok=True)
        a += ["--bind", p.rstrip("/"), p.rstrip("/")]
    for p in RUNTIME_PROTECTED.get(runtime, []):
        if os.path.exists(p):
            a += ["--ro-bind", p, p]
    for p in RUNTIME_PRIVATE_DIRS.get(runtime, []):
        if os.path.isdir(p):
            a += ["--tmpfs", p]
    for p in RUNTIME_PRIVATE_FILES.get(runtime, []):
        if os.path.isfile(p):
            a += ["--ro-bind", "/dev/null", p]
    if runtime == "claude" and cwd:
        own = claude_project_dir(cwd)
        os.makedirs(own, exist_ok=True)
        a += ["--bind", own, own]   # the session's own transcript, inside the hidden projects dir
    for p in escape_executables():
        a += ["--ro-bind", "/dev/null", p]
    if cwd:
        a += ["--chdir", cwd]
    return a


def sandbox_argv(policy, runtime, cmd, profile_dir=None, extra_read=(), tmp_dir=None, cwd=None):
    """Return the wrapped argv; the options are also written next to the task for inspection."""
    args = sandbox_args(policy, runtime, extra_read, tmp_dir, cwd)
    if profile_dir:
        with open(os.path.join(profile_dir, f"sandbox-{runtime}.bwrap.generated"), "w", encoding="utf-8") as f:
            f.write("\n".join(args) + "\n")
    return ["bwrap", *args, "--", *cmd]
