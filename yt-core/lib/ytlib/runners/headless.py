"""Headless runner: no terminal, no tmux. The runtime runs in print/exec mode.

Each run is one background process. A run ends when the session finishes its turn,
for example after `yt-status waiting-human`; `yt answer` then starts the next run
on the same runtime session with the answer as its prompt. Nobody can type into a
headless session, so `attach` shows its output log instead.

Handle = task name. State per handle in ~/yt-local/data/runners/headless/<name>.json
(pid, process start time, log path, exit code file). Output goes to
<task folder>/headless.log, outside out/.
"""
import json
import os
import shlex
import signal
import subprocess
import time

from .. import core

NAME = "headless"
INTERACTIVE = False
STATE = os.path.join(core.DATA, "runners", "headless")


def _state_path(handle):
    return os.path.join(STATE, f"{handle}.json")


def _state(handle):
    return core.read_json(_state_path(handle), None) or {}


def _start_time(pid):
    r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip() or None


def spawn(name, cwd, argv, env):
    if alive(name):
        raise RuntimeError(f"headless run {name} is still going")
    task_dir = os.path.dirname(cwd.rstrip("/"))
    log = os.path.join(task_dir, "headless.log")
    exit_file = os.path.join(STATE, f"{name}.exit")
    os.makedirs(STATE, exist_ok=True)
    if os.path.exists(exit_file):
        os.remove(exit_file)
    # sh records the exit code; stdin is empty so nothing can wait for typed input.
    script = f'{shlex.join(argv)}; echo $? > {shlex.quote(exit_file)}'
    with open(log, "a", encoding="utf-8") as out:
        out.write(f"\n--- run started {core.iso(core.now())} ---\n")
        out.flush()
        proc = subprocess.Popen(["/bin/sh", "-c", script], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    core.write_json_atomic(_state_path(name), {"pid": proc.pid, "started": _start_time(proc.pid),
                                               "log": log, "exit": exit_file})
    return name


def alive(handle):
    st = _state(handle)
    pid = st.get("pid")
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    # Guard against pid reuse: the start time must still match.
    return _start_time(pid) == st.get("started")


def exit_code(handle):
    """Exit code of the last finished run, or None while running or unknown."""
    try:
        with open(_state(handle).get("exit", ""), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def send(handle, text):
    # Typing into a headless run is not possible; yt answer starts a resumed run instead.
    return 1


def attach(handle):
    """Show the run's output; follow it while the run is going. Ctrl-C to leave."""
    log = _state(handle).get("log")
    if not log or not os.path.exists(log):
        print(f"no output log for {handle}")
        return 1
    if not alive(handle):
        return subprocess.call(["tail", "-n", "200", log])
    try:
        return subprocess.call(["tail", "-n", "200", "-f", log])
    except KeyboardInterrupt:
        return 0


def stop(handle):
    st = _state(handle)
    if not alive(handle):
        return 0
    try:
        os.killpg(st["pid"], signal.SIGTERM)
    except ProcessLookupError:
        return 0
    for _ in range(50):
        if not alive(handle):
            return 0
        time.sleep(0.1)
    try:
        os.killpg(st["pid"], signal.SIGKILL)
    except ProcessLookupError:
        pass
    return 0 if not alive(handle) else 1
