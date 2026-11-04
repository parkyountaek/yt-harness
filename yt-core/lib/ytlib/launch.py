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
    if "." in out_dir:
        # Codex splits -c keys on dots, so the trust key would be misread.
        raise RuntimeError(f"task folder path must not contain '.': {out_dir}")
    flags = ["-c", f"plugins.{harness}@yt-harness.enabled=true",
             "-c", f"projects.{out_dir}.trust_level=trusted",
             "--sandbox", "danger-full-access", "--ask-for-approval", "never"]
    if resume:
        return ["codex", "resume", *flags, session_id, prompt]
    return ["codex", *flags, prompt]


# The only variables a sub-session inherits. Anything else (coordinator session ids,
# messaging sockets and tokens, terminal-app hook tokens) would leak the coordinator
# into the sub-session and make the two runtimes see different environments.
PASS_ENV = ("HOME", "USER", "LOGNAME", "SHELL", "LANG", "TZ", "CODEX_HOME")
PASS_ENV_PREFIX = ("LC_",)


def session_env(task_dir, tmp_dir):
    """The complete environment of a sub-session; identical for every runtime."""
    extra = (core.read_json(core.CONFIG, {}) or {}).get("envPassthrough", [])
    env = {k: v for k, v in os.environ.items()
           if k in PASS_ENV or k.startswith(PASS_ENV_PREFIX) or k in extra}
    py_bin = os.path.dirname(os.path.realpath(sys.executable))
    env.update({
        "YT_TASK_DIR": task_dir,
        "TMPDIR": tmp_dir + "/",
        "CLAUDE_CODE_TMPDIR": tmp_dir,   # Claude's Bash tool keeps its cwd file here, not in /tmp
        "PATH": os.pathsep.join([os.path.join(core.CORE, "bin"), py_bin, os.environ.get("PATH", "")]),
    })
    return env


STARTUP_GRACE = 4  # seconds a runtime must stay alive to count as started


def codex_plugin_problem(harness_name, version):
    """Codex runs an installed copy of the harness plugin; it must exist and match the source."""
    cache = os.path.join(core.HOME, ".codex", "plugins", "cache", "yt-harness", harness_name)
    if not os.path.isdir(cache):
        return f"Codex does not have {harness_name} installed; run yt-core/bin/yt-setup"
    if version and not os.path.isdir(os.path.join(cache, str(version))):
        return f"Codex has an old copy of {harness_name} (want {version}); run yt-core/bin/yt-setup"
    return None


def confirm_started(runner, handle):
    """A runner can start a terminal whose runtime exits at once; require it to stay up."""
    end = time.time() + STARTUP_GRACE
    while time.time() < end:
        if not runner.alive(handle):
            return False
        time.sleep(0.5)
    return runner.alive(handle)


def find_codex_session(out_dir, since, timeout=30, scan=20):
    """Codex cannot preset a session id; read it from the rollout file whose cwd is out_dir."""
    root = os.path.join(core.HOME, ".codex", "sessions")
    end = time.time() + timeout
    while time.time() < end:
        paths = sorted(glob.glob(os.path.join(root, "*", "*", "*", "*.jsonl")), key=os.path.getmtime, reverse=True)
        for path in paths[:scan]:
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
    env = session_env(task_dir, tmp_dir)
    since = time.time() - 1
    handle = runner.spawn(task_id, out_dir, wrapped, env)
    if not confirm_started(runner, handle):
        raise RuntimeError(f"{runtime} exited during startup (runner handle {handle})")
    if runtime == "codex" and not session_id:
        session_id = find_codex_session(out_dir, since)
    return handle, session_id
