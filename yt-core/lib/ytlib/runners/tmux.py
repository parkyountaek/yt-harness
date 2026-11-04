"""tmux runner adapter. The handle is the tmux session name."""
import os
import shlex
import subprocess
import time

NAME = "tmux"


def _exact(handle):
    """Exact-match target; a bare name would also match longer names by prefix."""
    return f"={handle}"


def _pane(handle):
    return f"={handle}:"


def _tmux(*args, **kw):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, **kw)


def spawn(name, cwd, argv, env):
    handle = f"yt-{name}"
    if alive(handle):
        raise RuntimeError(f"tmux session {handle} already exists")
    # Start from an empty environment. The tmux server keeps the environment of whoever
    # started it (e.g. a coordinator session's tokens and sockets, TMUX itself); none of
    # that may reach the sub-session. TERM is the pane's own value.
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    command = f'env -i TERM="$TERM" {exports} {shlex.join(argv)}'
    r = _tmux("new-session", "-d", "-s", handle, "-x", "200", "-y", "50", "-c", cwd, command)
    if r.returncode != 0:
        raise RuntimeError(f"tmux new-session failed: {r.stderr.strip()}")
    return handle


def send(handle, text):
    if _tmux("send-keys", "-t", _pane(handle), "-l", text).returncode != 0:
        return 1
    time.sleep(0.3)
    return _tmux("send-keys", "-t", _pane(handle), "Enter").returncode


def capture(handle, lines=40):
    return _tmux("capture-pane", "-p", "-t", _pane(handle), "-S", f"-{lines}").stdout


def attach(handle):
    if os.environ.get("TMUX"):
        return subprocess.call(["tmux", "switch-client", "-t", _exact(handle)])
    return subprocess.call(["tmux", "attach-session", "-t", _exact(handle)])


def stop(handle):
    if not alive(handle):
        return 0
    _tmux("kill-session", "-t", _exact(handle))
    for _ in range(20):
        if not alive(handle):
            return 0
        time.sleep(0.25)
    return 1


def alive(handle):
    return _tmux("has-session", "-t", _exact(handle)).returncode == 0
