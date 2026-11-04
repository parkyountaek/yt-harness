"""Orca runner adapter: the sandboxed runtime runs in an Orca terminal tab.

Orca creates terminals only inside a workspace it knows, so tabs open in the
workspace from ~/yt-local/config.json "orca": {"worktree": "<selector>"} (default:
this checkout, path:<repo>). The command first changes to the task's out/ folder.
It is typed into the login shell with `exec`, so the tab ends when the runtime ends,
and `env -i` drops everything the Orca terminal carries (hook tokens, sockets).

Handle = Orca terminal handle (term_...).
"""
import json
import shlex
import subprocess

from .. import core

NAME = "orca"
INTERACTIVE = True


def _orca(*args):
    r = subprocess.run(["orca", *args, "--json"], capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    return data


def _worktree():
    cfg = (core.read_json(core.CONFIG, {}) or {}).get("orca") or {}
    return cfg.get("worktree") or f"path:{core.REPO}"


def spawn(name, cwd, argv, env):
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    command = f'cd {shlex.quote(cwd)} && exec env -i TERM="$TERM" {exports} {shlex.join(argv)}'
    data = _orca("terminal", "create", "--worktree", _worktree(), "--title", f"yt-{name}", "--command", command)
    if not data.get("ok"):
        err = (data.get("error") or {}).get("message") or "orca terminal create failed"
        raise RuntimeError(f"{err} (worktree {_worktree()}; set orca.worktree in ~/yt-local/config.json)")
    return data["result"]["terminal"]["handle"]


def alive(handle):
    data = _orca("terminal", "read", "--terminal", handle)
    return bool(data.get("ok")) and (data.get("result") or {}).get("terminal", {}).get("status") == "running"


def send(handle, text):
    data = _orca("terminal", "send", "--terminal", handle, "--text", text, "--enter")
    return 0 if data.get("ok") else 1


def attach(handle):
    """Bring the tab to the front in Orca; the human types there."""
    data = _orca("terminal", "switch", "--terminal", handle)
    if data.get("ok"):
        print(f"yt: {handle} is in front in Orca; type there")
        return 0
    return 1


def stop(handle):
    if not alive(handle):
        return 0
    data = _orca("terminal", "close", "--terminal", handle, "--tab")
    return 0 if data.get("ok") and not alive(handle) else 1
