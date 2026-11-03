"""macOS backend: Homebrew for packages, sandbox-exec for the shared sandbox."""
import os
import re
import shutil
import subprocess
import tempfile

NAME = "macos"
HOME = os.path.expanduser("~")
UID = os.getuid()

# What each runtime must read and write to start (verified with real runs).
RUNTIME_RW = {
    "claude": [("subpath", f"{HOME}/.claude"), ("regex", rf"^{re.escape(HOME)}/\.claude\.json"),
               ("subpath", f"{HOME}/Library/Keychains")],
    "codex": [("subpath", f"{HOME}/.codex")],
}

# Files inside the runtime dirs that change behaviour of later sessions (hooks, config,
# instructions, plugins). Writing them would let a sandboxed session run code outside
# the sandbox next time, so they stay read-only.
RUNTIME_PROTECTED = {
    "claude": [("regex", rf"^{re.escape(HOME)}/\.claude/settings[^/]*\.json$"),
               ("literal", f"{HOME}/.claude/CLAUDE.md"),
               ("literal", f"{HOME}/.claude/keybindings.json"),
               *[("subpath", f"{HOME}/.claude/{d}") for d in
                 ("hooks", "skills", "agents", "commands", "plugins", "mods", "dev-mods", "output-styles")]],
    "codex": [*[("literal", f"{HOME}/.codex/{f}") for f in
                ("config.toml", "hooks.json", "AGENTS.md", "AGENTS.override.md")],
              *[("subpath", f"{HOME}/.codex/{d}") for d in
                ("rules", "skills", "plugins", "packages", "prompts", ".tmp")]],
}

# Other sessions' transcripts and history: unreadable, so a sub-session cannot see the
# coordinator's conversation. The session's own transcript folder is re-allowed.
RUNTIME_PRIVATE = {
    "claude": [("subpath", f"{HOME}/.claude/projects"), ("literal", f"{HOME}/.claude/history.jsonl"),
               ("subpath", f"{HOME}/.claude/file-history"), ("subpath", f"{HOME}/.claude/backups")],
    "codex": [("literal", f"{HOME}/.codex/history.jsonl"), ("subpath", f"{HOME}/.codex/backups")],
}

# Programs that ask a process outside the sandbox to run something for us.
ESCAPE_EXECUTABLES = ["/usr/bin/open", "/usr/bin/osascript", "/bin/launchctl", "/usr/bin/crontab",
                      "/usr/bin/at", "/usr/bin/batch", "/usr/bin/screen", "/usr/bin/ssh"]

# Device files every runtime needs.
DEVICES = [("literal", "/dev/null"), ("literal", "/dev/zero"), ("literal", "/dev/ptmx"),
           ("literal", "/dev/dtracehelper"), ("regex", r"^/dev/tty"), ("regex", r"^/dev/fd/"),
           ("regex", r"^/dev/ttys[0-9]+$")]


def package_manager():
    return "brew" if shutil.which("brew") else None


def install(packages):
    if not packages:
        return 0
    if not package_manager():
        print("Homebrew is missing. Install it from https://brew.sh, then rerun yt-setup.")
        return 1
    return subprocess.call(["brew", "install", *packages])


def upgrade(packages):
    """Upgrade only what Homebrew manages (Apple's git and python are left alone)."""
    if not packages or not package_manager():
        return 0
    managed = set(subprocess.run(["brew", "list", "--formula", "-1"],
                                 capture_output=True, text=True).stdout.split())
    skipped = [p for p in packages if p not in managed]
    if skipped:
        print("not managed by Homebrew, skipped: " + ", ".join(skipped))
    packages = [p for p in packages if p in managed]
    return subprocess.call(["brew", "upgrade", *packages]) if packages else 0


def sandbox_problem():
    return None if shutil.which("sandbox-exec") else "sandbox-exec is missing from this macOS install"


def _filter(kind, value):
    if kind == "regex":
        return f'(regex #"{value}")'
    return f'({kind} "{value}")'


def _rule(action, op, filters):
    return f"({action} {op} " + " ".join(_filter(k, v) for k, v in filters) + ")" if filters else ""


def claude_project_dir(cwd):
    """Claude keeps a session's transcript in ~/.claude/projects/<cwd with non-alphanumerics as '-'>."""
    return f"{HOME}/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))


def user_temp_root():
    """/private/var/folders/<a>/<b>: the per-user temp and cache area shared by every process."""
    try:
        t = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return None
    return os.path.dirname(os.path.realpath(t.rstrip("/"))) if t else None


def private_read_roots():
    """Places outside $HOME that hold other people's or other sessions' data."""
    roots = ["/Users", "/Volumes", f"/private/tmp/claude-{UID}"]
    temp = user_temp_root()
    if temp:
        roots.append(temp)
    return roots


def tmux_socket_dirs():
    dirs = {f"/private/tmp/tmux-{UID}"}
    if os.environ.get("TMUX_TMPDIR"):
        dirs.add(os.path.realpath(os.environ["TMUX_TMPDIR"]))
    return sorted(dirs)


def escape_executables():
    paths = set(ESCAPE_EXECUTABLES)
    for name in ("tmux", "screen", "ssh"):
        found = shutil.which(name)
        if found:
            paths.update({found, os.path.realpath(found)})
    return sorted(paths)


def sandbox_profile(policy, runtime, extra_read=(), tmp_dir=None, cwd=None):
    """Build a sandbox-exec profile. Later rules win over earlier ones.

    policy: {"read": [paths], "write": [paths]} with placeholders resolved.
    Reads: everything under $HOME is denied except the policy, extra_read, and what the
    runtime needs. Writes: denied everywhere except the policy, the runtime dirs, a
    per-task temp dir, and devices. Runtime config files stay read-only.
    """
    rw = RUNTIME_RW.get(runtime, [])
    reads = [("literal", HOME)] + [("subpath", p.rstrip("/")) for p in policy.get("read", [])]
    reads += [("subpath", p) for p in extra_read] + rw
    writes = [("subpath", p.rstrip("/")) for p in policy.get("write", [])] + rw + DEVICES
    if tmp_dir:
        writes.append(("subpath", tmp_dir))
    private = RUNTIME_PRIVATE.get(runtime, [])
    own, own_read_only = [], []
    if runtime == "claude" and cwd:
        # The session's own transcript folder and Claude's per-cwd temp folder for the Bash tool.
        # The rest of /private/tmp/claude-<uid> (other sessions' temp files) stays unwritable.
        encoded = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))
        own = [("subpath", claude_project_dir(cwd)), ("subpath", f"/private/tmp/claude-{UID}/{encoded}")]
        # Interactive Claude opens the temp root itself at startup. Only the directory entry is
        # readable (other sessions' folder names); their contents stay denied.
        own_read_only = [("literal", f"/private/tmp/claude-{UID}")]
    sockets = [("subpath", d) for d in tmux_socket_dirs()]
    lines = [
        "(version 1)",
        "(allow default)",
        # reads
        f'(deny file-read-data (subpath "{HOME}"))',
        _rule("deny", "file-read-data", [("subpath", r) for r in private_read_roots()]),
        _rule("allow", "file-read-data", reads),
        _rule("deny", "file-read-data", private),
        _rule("allow", "file-read-data", own + own_read_only),
        # writes
        "(deny file-write*)",
        _rule("allow", "file-write*", writes),
        _rule("deny", "file-write*", RUNTIME_PROTECTED.get(runtime, [])),
        _rule("deny", "file-write*", private),
        _rule("allow", "file-write*", own),
        # channels that run commands outside the sandbox
        _rule("deny", "file-read* file-write*", sockets),
        "(deny network-outbound " + " ".join(f'(remote unix-socket (subpath "{d}"))'
                                             for d in tmux_socket_dirs()) + ")",
        "(deny appleevent-send)",
        _rule("deny", "process-exec", [("literal", p) for p in escape_executables()]),
    ]
    return "\n".join(line for line in lines if line) + "\n"


def sandbox_argv(policy, runtime, cmd, profile_dir=None, extra_read=(), tmp_dir=None, cwd=None):
    """Write the profile next to the task and return the wrapped argv."""
    profile = sandbox_profile(policy, runtime, extra_read, tmp_dir, cwd)
    path = os.path.join(profile_dir, f"sandbox-{runtime}.sb.generated") if profile_dir else \
        tempfile.mkstemp(prefix=f"yt-{runtime}-", suffix=".sb.generated")[1]
    with open(path, "w", encoding="utf-8") as f:
        f.write(profile)
    return ["sandbox-exec", "-f", path, *cmd]
