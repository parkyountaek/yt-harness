#!/usr/bin/env python3
"""Harness hooks: the generated hooks.json, yt-hook (session-start, stop, prompt), and the
sub-session isolation flags that keep only the harness's hooks on.

Runs against a throwaway local layer (YT_LOCAL, YT_WORK); nothing touches the real data.
Usage: tests/hooks/run.py      exit 0 when every check passes
"""
import json
import os
import subprocess
import sys
import tempfile
import time

LOCAL = tempfile.mkdtemp(prefix="ythooks")
os.environ.update(YT_LOCAL=LOCAL, YT_WORK=os.path.join(LOCAL, "work"))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "yt-core", "lib"))
from ytlib import core, launch  # noqa: E402

HOOK = os.path.join(REPO, "yt-core", "bin", "yt-hook")
results = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))


def hook(cmd, event=None, task=None, shell_cmd=None):
    env = {k: v for k, v in os.environ.items() if k not in ("YT_TASK_DIR", "YT_CORE")}
    if task:
        env.update(YT_TASK_DIR=task, YT_CORE=core.CORE)
    argv = ["/bin/sh", "-c", shell_cmd] if shell_cmd else [sys.executable, HOOK, cmd]
    return subprocess.run(argv, input=json.dumps(event or {}), env=env, capture_output=True, text=True)


def make_task(task_id, harness="yt-ops", state="running"):
    task = core.task_dir(task_id)
    os.makedirs(os.path.join(task, "out"), exist_ok=True)
    with open(os.path.join(task, "TASK.md"), "w", encoding="utf-8") as f:
        f.write(f"# Work order: {task_id}\n\n- Harness: {harness} 0.1.0 (x)\n")
    core.write_status(task, {"taskId": task_id, "state": state})
    return task


def set_state(task, state, **extra):
    core.update_status(task, lambda s: s.update(state=state, **extra))


def test_generated():
    for name in core.harness_names():
        with open(os.path.join(core.harness_dir(name), "hooks", "hooks.json"), encoding="utf-8") as f:
            events = json.load(f)["hooks"]
        check(f"{name}: hooks.json has SessionStart, PreToolUse, Stop", set(events) == {"SessionStart", "PreToolUse", "Stop"},
              sorted(events))
    with open(os.path.join(core.CORE, "hooks", "hooks.json"), encoding="utf-8") as f:
        events = json.load(f)["hooks"]
    check("yt-core: hooks.json has PreToolUse and UserPromptSubmit", set(events) == {"PreToolUse", "UserPromptSubmit"})
    # Outside a sub-session ($YT_CORE unset) the harness hooks do nothing and exit 0.
    with open(os.path.join(core.harness_dir("yt-ops"), "hooks", "hooks.json"), encoding="utf-8") as f:
        stop_cmd = json.load(f)["hooks"]["Stop"][0]["hooks"][0]["command"]
    r = hook(None, shell_cmd=stop_cmd)
    check("harness hook outside a sub-session: no-op", r.returncode == 0 and not r.stdout, r)
    task = make_task("shell-stop")
    r = hook(None, task=task, shell_cmd=stop_cmd)
    check("harness hook in a sub-session: the stop gate runs through the generated command", r.returncode == 2, r)


def test_session_start():
    task = make_task("start")
    r = hook("session-start", {"source": "startup"}, task)
    check("session-start: names the work order", f"{task}/TASK.md" in r.stdout, r.stdout)
    check("session-start: names the harness skill", "`read-only-investigation`" in r.stdout, r.stdout)
    check("session-start: no reset note on startup", "re-read" not in r.stdout, r.stdout)
    r = hook("session-start", {"source": "compact"}, task)
    check("session-start: after compaction, re-read TASK.md and status", "re-read TASK.md" in r.stdout, r.stdout)
    r = hook("session-start", {"source": "startup"})
    check("session-start: nothing outside a sub-session", r.returncode == 0 and not r.stdout, r)


def test_stop():
    task = make_task("stop")
    r = hook("stop", {"stop_hook_active": False}, task)
    check("stop: running blocks (exit 2, reason on stderr)", r.returncode == 2 and "yt-status done" in r.stderr, r)
    r = hook("stop", {"stop_hook_active": True}, task)
    check("stop: second refusal", r.returncode == 2, r)
    r = hook("stop", {"stop_hook_active": True}, task)
    check("stop: after two refusals without a status change it lets go", r.returncode == 0, r)
    time.sleep(1.1)   # status times have one-second resolution
    set_state(task, "running")
    r = hook("stop", {}, task)
    check("stop: a status change restarts the count", r.returncode == 2, r)
    with open(core.result_path(task), "w", encoding="utf-8") as f:
        f.write("answer\n")
    time.sleep(1.1)
    set_state(task, "running")
    r = hook("stop", {}, task)
    check("stop: result written but not reported names yt-status done", "result.md is written" in r.stderr, r.stderr)
    for st in ("done", "failed", "waiting-human"):
        set_state(task, st)
        r = hook("stop", {}, task)
        check(f"stop: {st} may end", r.returncode == 0, r)
    r = hook("stop", {})
    check("stop: nothing outside a sub-session", r.returncode == 0, r)
    r = subprocess.run([sys.executable, HOOK, "stop"], input="not json", capture_output=True, text=True,
                       env={**os.environ, "YT_TASK_DIR": os.path.join(LOCAL, "missing")})
    check("stop: bad input or a missing task never blocks", r.returncode == 0, r)


def test_prompt():
    core.write_json_atomic(core.SESSIONS, {"sessions": {"ask": {"harness": "yt-ops", "runtime": "codex",
                                                                "runner": "tmux", "runnerHandle": None}}})
    make_task("ask", state="waiting-human")
    set_state(core.task_dir("ask"), "waiting-human", question="Which year?")
    r = hook("prompt", {"prompt": "hi"})
    check("prompt: a new question is put in context", "yt ask asks: Which year?" in r.stdout, r.stdout)
    r = hook("prompt", {"prompt": "hi"})
    check("prompt: told once", r.stdout == "", r.stdout)
    r = hook("prompt", {}, task=core.task_dir("ask"))
    check("prompt: never inside a sub-session", r.stdout == "", r.stdout)


def fake_home(user_settings=None, codex_hooks=None, codex_toml=""):
    home = tempfile.mkdtemp(prefix="ythome", dir=LOCAL)
    os.makedirs(os.path.join(home, ".claude"))
    os.makedirs(os.path.join(home, ".codex"))
    if user_settings is not None:
        core.write_json_atomic(os.path.join(home, ".claude", "settings.json"), user_settings)
    if codex_hooks is not None:
        core.write_json_atomic(os.path.join(home, ".codex", "hooks.json"), {"hooks": codex_hooks})
    with open(os.path.join(home, ".codex", "config.toml"), "w", encoding="utf-8") as f:
        f.write(codex_toml)
    return home


def test_isolation():
    cmd = [{"hooks": [{"type": "command", "command": "x"}, {"type": "command", "command": "y"}]}]
    home = fake_home({"model": "opus", "hooks": {"Stop": cmd}, "enabledPlugins": {"p@m": True},
                      "env": {"CLAUDE_CODE_PLUGIN_DIRS": "/x/yt-core:/x/mods/a", "CLAUDE_MODS_THEME_FILE": "/t",
                              "HTTPS_PROXY": "http://proxy"}},
                     {"PreToolUse": cmd, "Stop": cmd[:1]},
                     '[hooks]\n[[hooks.SessionStart]]\nhooks = [{type = "command", command = "z"}]\n'
                     '[plugins."yt-ops@yt-harness"]\nenabled = false\n[plugins."other@m"]\nenabled = true\n')
    argv = launch.claude_isolation(home)
    settings = json.loads(argv[argv.index("--settings") + 1])
    check("claude: user settings are not loaded", argv[:2] == ["--setting-sources", "project,local"], argv)
    check("claude: hooks, plugins, and the plugin dirs stay behind; model and env carry",
          settings == {"model": "opus", "env": {"HTTPS_PROXY": "http://proxy"}, "skipDangerousModePermissionPrompt": True},
          settings)
    flags = launch.codex_isolation("yt-ops", home)
    check("codex: hooks run without the trust prompt", flags[0] == "--dangerously-bypass-hook-trust", flags)
    state = next(f for f in flags if f.startswith("hooks.state="))
    keys = [f"{home}/.codex/hooks.json:pre_tool_use:0:0", f"{home}/.codex/hooks.json:pre_tool_use:0:1",
            f"{home}/.codex/hooks.json:stop:0:0", f"{home}/.codex/hooks.json:stop:0:1",
            f"{home}/.codex/config.toml:session_start:0:0"]
    check("codex: every user hook is turned off by its key",
          all(f'"{k}"={{enabled=false}}' in state for k in keys) and state.count("enabled=false") == 5, state)
    plugins = next(f for f in flags if f.startswith("plugins="))
    check("codex: only the harness plugin is on",
          plugins == 'plugins={"other@m"={enabled=false},"yt-ops@yt-harness"={enabled=true}}', plugins)
    check("codex: no user hooks means no state override",
          not any(f.startswith("hooks.state=") for f in launch.codex_isolation("yt-ops", fake_home())))
    check("codex: features.hooks stays on", "features.hooks=false" not in flags)


def main():
    test_generated()
    test_session_start()
    test_stop()
    test_prompt()
    test_isolation()
    print(f"\n{results['pass']} passed, {results['fail']} failed")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
