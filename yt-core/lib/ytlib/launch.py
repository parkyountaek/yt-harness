"""Build and start the sandboxed runtime command. Shared by yt-spawn and yt resume."""
import glob
import json
import os
import sys
import time

from . import core
from . import platform as ytplatform
from . import runners

START_PROMPT = "Read {task_dir}/TASK.md and follow it exactly. Start now."
RESUME_PROMPT = ("You were stopped and resumed. Re-read {task_dir}/TASK.md and {task_dir}/out/status.json, "
                 "then continue from where you left off. Overwrite out/result.md; never append.")


def runtime_argv(runtime, harness, out_dir, session_id, prompt, resume=False):
    harness_path = core.harness_dir(harness)
    if runtime == "claude":
        sid = ["--resume", session_id] if resume else ["--session-id", session_id]
        return ["claude", "--plugin-dir", harness_path, *sid, "--dangerously-skip-permissions", prompt]
    # Codex: the shared sandbox is the enforcement layer, so Codex's own sandbox is off
    # (the two cannot be nested). The harness plugin is installed disabled and enabled per run.
    flags = ["-c", f"plugins.{harness}@yt-harness.enabled=true",
             "-c", f"projects.{out_dir}.trust_level=trusted",
             "--sandbox", "danger-full-access", "--ask-for-approval", "never"]
    if resume:
        return ["codex", "resume", *flags, session_id, prompt]
    return ["codex", *flags, prompt]


def find_codex_session(out_dir, since, timeout=30):
    """Codex cannot preset a session id; read it from the rollout file whose cwd is out_dir."""
    root = os.path.join(core.HOME, ".codex", "sessions")
    end = time.time() + timeout
    while time.time() < end:
        paths = sorted(glob.glob(os.path.join(root, "*", "*", "*", "*.jsonl")), key=os.path.getmtime, reverse=True)
        for path in paths[:20]:
            if os.path.getmtime(path) < since:
                break
            try:
                with open(path, encoding="utf-8") as f:
                    meta = json.loads(f.readline())
            except (OSError, ValueError):
                continue
            payload = meta.get("payload", {})
            if meta.get("type") == "session_meta" and payload.get("cwd") == out_dir:
                return payload.get("id")
        time.sleep(1)
    return None


def start(task_id, harness_name, harness, runtime, runner_name, session_id, resume=False):
    """Wrap the runtime in the shared sandbox and start it with the runner. Returns (handle, session_id)."""
    plat = ytplatform.load()
    runner = runners.load(runner_name)
    task_dir = core.task_dir(task_id)
    out_dir = os.path.join(task_dir, "out")
    prompt = (RESUME_PROMPT if resume else START_PROMPT).format(task_dir=task_dir)
    cmd = runtime_argv(runtime, harness_name, out_dir, session_id, prompt, resume)
    policy = core.resolve_policy(harness, task_dir)
    # The session also needs to read yt-core (for yt-status), the harness, and the Python install.
    extra_read = [core.CORE, core.harness_dir(harness_name), os.path.realpath(sys.base_prefix)]
    tmp_dir = os.path.join(task_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    wrapped = plat.sandbox_argv(policy, runtime, cmd, profile_dir=task_dir, extra_read=extra_read,
                                tmp_dir=tmp_dir, cwd=out_dir)
    py_bin = os.path.dirname(os.path.realpath(sys.executable))
    env = {"YT_TASK_DIR": task_dir, "TMPDIR": tmp_dir + "/",
           "PATH": os.pathsep.join([os.path.join(core.CORE, "bin"), py_bin, os.environ.get("PATH", "")])}
    since = time.time() - 1
    handle = runner.spawn(task_id, out_dir, wrapped, env)
    if runtime == "codex" and not resume:
        session_id = find_codex_session(out_dir, since)
    return handle, session_id
