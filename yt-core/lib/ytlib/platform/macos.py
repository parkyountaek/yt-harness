"""macOS backend: Homebrew for packages, sandbox-exec for the shared sandbox."""
import os
import shutil
import subprocess
import tempfile

NAME = "macos"
HOME = os.path.expanduser("~")

# What each runtime needs to start inside the sandbox (verified in plan step 1).
RUNTIME_READ_WRITE = {
    "claude": [("subpath", f"{HOME}/.claude"), ("regex", rf"^{HOME}/\.claude\.json"),
               ("subpath", f"{HOME}/Library/Keychains")],
    "codex": [("subpath", f"{HOME}/.codex")],
}


def package_manager():
    return "brew" if shutil.which("brew") else None


def install(packages):
    if not packages:
        return 0
    if not package_manager():
        print("Homebrew is missing. Install it from https://brew.sh, then rerun yt-setup.")
        return 1
    return subprocess.call(["brew", "install", *packages])


def _filter(kind, value):
    if kind == "regex":
        return f'(regex #"{value}")'
    return f'({kind} "{value}")'


def sandbox_profile(policy, runtime, extra_read=()):
    """Build a sandbox-exec profile.

    policy: {"read": [paths], "write": [paths]} with placeholders already resolved.
    Everything under $HOME is denied except the listed paths and what the
    runtime itself needs. Metadata reads stay allowed so path vetting works.
    """
    runtime_rules = RUNTIME_READ_WRITE.get(runtime, [])
    reads = [("literal", HOME)] + [("subpath", p.rstrip("/")) for p in policy.get("read", [])]
    reads += [("subpath", p) for p in extra_read] + runtime_rules
    writes = [("subpath", p.rstrip("/")) for p in policy.get("write", [])] + runtime_rules
    lines = [
        "(version 1)",
        "(allow default)",
        f'(deny file-read-data (subpath "{HOME}"))',
        "(allow file-read-data " + " ".join(_filter(k, v) for k, v in reads) + ")",
        f'(deny file-write* (subpath "{HOME}"))',
        "(allow file-write* " + " ".join(_filter(k, v) for k, v in writes) + ")",
    ]
    return "\n".join(lines) + "\n"


def sandbox_argv(policy, runtime, cmd, profile_dir=None, extra_read=()):
    """Write the profile next to the task and return the wrapped argv."""
    profile = sandbox_profile(policy, runtime, extra_read)
    fd, path = tempfile.mkstemp(prefix=f"yt-{runtime}-", suffix=".sb.generated", dir=profile_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(profile)
    return ["sandbox-exec", "-f", path, *cmd]
