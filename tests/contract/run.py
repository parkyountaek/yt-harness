#!/usr/bin/env python3
"""Runtime equivalence contract tests.

Default mode (no model, a few seconds): runs the same scenarios for Claude and Codex
with a fake runner, checks each expected outcome, then checks that the two runtimes'
observations are identical after replacing the runtime name. Covers the work order,
the sandbox wrapper, state transitions, coordinator judgments, stop and resume,
refusals, the concurrency limit, generated manifests, and global setup drift.

--live: also runs one real read-only task on both runtimes (tmux, real sandbox,
~/yt-work) and compares result.md and the final state. Uses model calls.

Usage: tests/contract/run.py [--live]      exit 0 when every case passes
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
BIN = os.path.join(REPO, "yt-core", "bin")
RUNTIMES = ("claude", "codex")
FIXED_DEADLINE = "2099-01-01T00:00:00+00:00"

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="ytcontract"))
REAL_ENV = dict(os.environ)
os.environ.update(YT_LOCAL=os.path.join(ROOT, "local"), YT_WORK=os.path.join(ROOT, "work"), YT_REPO=REPO)
os.environ.pop("CODEX_HOME", None)
# Pretend to run inside a coordinator session: none of this may reach a sub-session.
os.environ.update(CLAUDECODE="1", CLAUDE_CODE_CHILD_SESSION="1", CLAUDE_CODE_MESSAGING_TOKEN="t",
                  ORCA_AGENT_HOOK_TOKEN="t", AI_AGENT="x", TMUX="/tmp/x,1,0", SSH_AUTH_SOCK="/tmp/s")
sys.path.insert(0, os.path.join(REPO, "yt-core", "lib"))
from ytlib import core, launch, parity, runners  # noqa: E402
from ytlib import platform as ytplatform  # noqa: E402

results = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))


# ---------- fakes ----------

fake = types.ModuleType("ytlib.runners.fake")
fake.sessions = {}


def _spawn(name, cwd, argv, env):
    handle = f"fake-{name}-{len(fake.sessions)}"
    fake.sessions[handle] = {"name": name, "cwd": cwd, "argv": argv, "env": env, "alive": True}
    return handle


fake.spawn = _spawn
fake.alive = lambda h: fake.sessions.get(h, {}).get("alive", False)
fake.stop = lambda h: fake.sessions.get(h, {}).update(alive=False) or 0
fake.attach = fake.send = lambda h, *a: 0
sys.modules[fake.__name__] = fake
runners.fake = fake
launch.STARTUP_GRACE = 0
launch.find_codex_session = lambda *a, **k: "codex-session-1"
launch.codex_plugin_problem = lambda *a, **k: None
parity.problems = lambda *a, **k: []   # global drift is tested separately below


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), os.path.join(BIN, name))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


spawn_mod, yt_mod = load_script("yt-spawn"), load_script("yt")
spawn_mod.shutil = types.SimpleNamespace(which=lambda n: f"/usr/bin/{n}")


def quiet(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(*args)
    return rc, out.getvalue() + err.getvalue()


def spawn(task_id, runtime, deadline=FIXED_DEADLINE):
    return quiet(spawn_mod.main, [task_id, "yt-ops", "--runtime", runtime, "--runner", "fake",
                                  "--deadline", deadline, "--brief", os.path.join(ROOT, "brief.md")])[0]


def yt(*args):
    return quiet(yt_mod.main, list(args))[0]


def yt_status(task_id, *args):
    env = dict(os.environ, YT_TASK_DIR=core.task_dir(task_id))
    return subprocess.run([sys.executable, os.path.join(BIN, "yt-status"), *args], env=env,
                          capture_output=True, text=True).returncode


def state(task_id):
    return (core.read_status(core.task_dir(task_id)) or {}).get("state")


def entry(task_id):
    return core.load_sessions()["sessions"].get(task_id, {})


def last_session(task_id):
    return [s for s in fake.sessions.values() if s["name"] == task_id][-1]


def stop_all():
    for s in fake.sessions.values():
        s["alive"] = False


def write_result(task_id):
    with open(core.result_path(core.task_dir(task_id)), "w", encoding="utf-8") as f:
        f.write("answer\n")


# ---------- scenarios (same for every runtime) ----------

def scenario(rt):
    obs = {}
    stop_all()
    a, b, c, d, e, f = (f"{x}-{rt}" for x in ("life", "fail", "stale", "tamper", "invalid", "dirty"))
    # spawn and the work order
    obs["spawn"] = spawn(a, rt)
    task = core.task_dir(a)
    with open(os.path.join(task, "TASK.md"), encoding="utf-8") as fh:
        obs["TASK.md"] = fh.read()
    s = last_session(a)
    obs["wrapper"] = s["argv"][0]
    obs["MCP and connectors off"] = (("--strict-mcp-config" in s["argv"]) if rt == "claude"
                                     else ("features.apps=false" in s["argv"])) \
        and s["env"].get("ENABLE_CLAUDEAI_MCP_SERVERS") == "false"
    # Web search and fetch must stay available in sub-sessions (subagents use them).
    obs["web tools on"] = not any("WebSearch" in a or "WebFetch" in a or "web_search" in a for a in s["argv"])
    obs["user hooks off"] = ('{"disableAllHooks": true}' in s["argv"]) if rt == "claude" \
        else ("features.hooks=false" in s["argv"])
    obs["prompt"] = s["argv"][-1]
    obs["env"] = sorted(s["env"])
    obs["env leaks nothing"] = sorted(k for k in s["env"] if k.startswith(("CLAUDE", "CODEX_SESSION", "ORCA_", "TMUX"))
                                      or k in ("AI_AGENT", "SSH_AUTH_SOCK")) == ["CLAUDE_CODE_TMPDIR"]
    obs["env.YT_TASK_DIR"] = s["env"]["YT_TASK_DIR"]
    obs["env.TMPDIR"] = s["env"]["TMPDIR"]
    obs["cwd"] = s["cwd"]
    with open(os.path.join(task, f"sandbox-{rt}.sb.generated"), encoding="utf-8") as fh:
        profile = fh.read()
    obs["profile writes out/"] = f'(subpath "{task}/out")' in profile
    obs["profile reads task"] = f'(subpath "{task}")' in profile
    obs["profile denies escapes"] = "(deny process-exec" in profile and "(deny appleevent-send)" in profile
    obs["initial state"] = state(a)
    obs["has session id"] = bool(entry(a).get("runtimeSessionId"))
    obs["duplicate spawn"] = spawn(a, rt)
    # session-side transitions
    obs["waiting without question"] = yt_status(a, "waiting-human")
    obs["waiting"] = (yt_status(a, "waiting-human", "--question", "Which file?"), state(a))
    obs["question kept"] = (core.read_status(task) or {}).get("question")
    obs["back to running"] = (yt_status(a, "running"), state(a), "question" in core.read_status(task))
    obs["done without result"] = (yt_status(a, "done"), state(a))
    write_result(a)
    obs["done"] = (yt_status(a, "done"), state(a))
    obs["change after done"] = (yt_status(a, "running"), state(a))
    obs["bad state"] = yt_status(a, "finished")
    # failed path
    spawn(b, rt)
    obs["failed without reason"] = yt_status(b, "failed")
    obs["failed"] = (yt_status(b, "failed", "--reason", "input missing"), state(b))
    obs["change after failed"] = (yt_status(b, "done"), state(b))
    # deadline -> stale -> stop -> resume
    spawn(c, rt)
    yt_status(c, "waiting-human", "--question", "Proceed?")
    with core.locked(core.REGISTRY_LOCK):
        reg = core.load_sessions()
        reg["sessions"][c]["deadline"] = "2000-01-01T00:00:00+00:00"
        core.save_sessions(reg)
    yt("status")
    st = core.read_status(core.task_dir(c))
    obs["stale"] = (st.get("state"), st.get("staleFrom"))
    obs["resume while alive"] = yt("resume", c)
    obs["stop"] = (yt("stop", c), fake.alive(entry(c)["runnerHandle"]))
    obs["resume"] = yt("resume", c, "--deadline", "1h")
    st = core.read_status(core.task_dir(c))
    obs["state after resume"] = (st.get("state"), "staleSince" in st, "staleFrom" in st)
    obs["deadline extended"] = core.parse_time(entry(c)["deadline"]) > core.now()
    r = last_session(c)
    sid = entry(c)["runtimeSessionId"]
    obs["resume prompt"] = r["argv"][-1]
    obs["resume keeps hooks off"] = ('{"disableAllHooks": true}' in r["argv"]) if rt == "claude" \
        else ("features.hooks=false" in r["argv"])
    obs["resume uses same session"] = sid in r["argv"] and (
        "--resume" in r["argv"] if rt == "claude" else "resume" in r["argv"])
    obs["forget while alive"] = yt("forget", c)
    # coordinator judgments on what the session wrote
    yt("stop", a), yt("stop", b), yt("stop", c)
    spawn(d, rt)
    st = core.read_status(core.task_dir(d))
    st["state"] = "done"
    core.write_status(core.task_dir(d), st)
    yt("status")
    obs["done without result.md"] = state(d)
    spawn(e, rt)
    with open(core.status_path(core.task_dir(e)), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    yt("status")
    obs["unreadable status"] = state(e)
    # refusals and limits
    os.makedirs(os.path.join(core.task_dir(f), "out"), exist_ok=True)
    with open(os.path.join(core.task_dir(f), "out", "old.md"), "w", encoding="utf-8") as fh:
        fh.write("old\n")
    obs["dirty out/"] = (spawn(f, rt), bool(entry(f)))
    stop_all()
    obs["concurrency"] = [spawn(f"slot{i}-{rt}", rt) for i in range(4)]
    stop_all()
    obs["forget stopped"] = (yt("forget", a), bool(entry(a)))
    return obs


EXPECTED = {
    "spawn": 0, "env leaks nothing": True, "user hooks off": True, "web tools on": True, "MCP and connectors off": True, "wrapper": "sandbox-exec", "initial state": "running", "has session id": True,
    "duplicate spawn": 1, "waiting without question": 1, "waiting": (0, "waiting-human"),
    "question kept": "Which file?", "back to running": (0, "running", False),
    "done without result": (1, "running"), "done": (0, "done"), "change after done": (1, "done"),
    "bad state": 1, "failed without reason": 1, "failed": (0, "failed"), "change after failed": (1, "failed"),
    "stale": ("stale", "waiting-human"), "resume while alive": 1, "stop": (0, False), "resume": 0,
    "state after resume": ("waiting-human", False, False), "deadline extended": True,
    "resume uses same session": True, "resume keeps hooks off": True, "forget while alive": 1, "done without result.md": "failed",
    "unreadable status": "failed", "dirty out/": (1, False), "concurrency": [0, 0, 0, 2],
    "forget stopped": (0, False), "profile writes out/": True, "profile reads task": True,
    "profile denies escapes": True,
}


def normalize(value, rt):
    text = json.dumps(value, sort_keys=True)
    return json.loads(text.replace(rt, "<runtime>"))


def test_scenarios():
    with open(os.path.join(ROOT, "brief.md"), "w", encoding="utf-8") as fh:
        fh.write("Count the lines of in/sample.txt.\n")
    observed = {rt: scenario(rt) for rt in RUNTIMES}
    for rt, obs in observed.items():
        for key, want in EXPECTED.items():
            got = obs[key]
            check(f"{rt}: {key}", normalize(got, rt) == normalize(want, rt), f"want {want!r}, got {got!r}")
    a, b = (normalize(observed[rt], rt) for rt in RUNTIMES)
    for key in sorted(a):
        check(f"equivalent: {key}", a[key] == b[key], f"claude {a[key]!r} vs codex {b[key]!r}")


# ---------- generated manifests ----------

def test_build():
    r = subprocess.run([sys.executable, os.path.join(BIN, "yt-build"), "--check"], capture_output=True, text=True)
    check("yt-build --check: runtime manifests match neutral sources", r.returncode == 0, r.stderr.strip())
    for plugin in ("yt-core", "yt-ops"):
        with open(os.path.join(REPO, plugin, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            cl = json.load(fh)
        with open(os.path.join(REPO, plugin, ".codex-plugin", "plugin.json"), encoding="utf-8") as fh:
            cx = json.load(fh)
        same = all(cl[k] == cx[k] for k in ("name", "version", "description"))
        check(f"{plugin}: same name, version, description for both runtimes", same, f"{cl} vs {cx}")


# ---------- global setup drift ----------

def fake_home(claude_md, codex_md, claude_settings=None, codex_hooks=None, codex_toml=""):
    home = tempfile.mkdtemp(dir=ROOT, prefix="home")
    os.makedirs(os.path.join(home, ".claude"))
    os.makedirs(os.path.join(home, ".codex"))
    files = {".claude/CLAUDE.md": claude_md, ".codex/AGENTS.md": codex_md,
             ".claude/settings.json": json.dumps(claude_settings or {}),
             ".codex/hooks.json": json.dumps({"hooks": codex_hooks or {}}), ".codex/config.toml": codex_toml}
    for rel, text in files.items():
        with open(os.path.join(home, rel), "w", encoding="utf-8") as fh:
            fh.write(text)
    return home


def test_parity():
    real = importlib.reload(parity)   # undo the stub used by the scenarios
    md = "# Global\n- Respond in Korean.\n"
    linked = {"env": {"CLAUDE_CODE_PLUGIN_DIRS": "/x/yt-core"}}
    toml = '[plugins."yt-core@yt-harness"]\nenabled = true\n'
    cases = [
        ("same instructions and plugins", fake_home(md, md + "\n", linked, None, toml), 0),
        ("instructions differ", fake_home(md, "# Global\n- Respond in English.\n", linked, None, toml), 1),
        ("hooks are not drift (disabled per run)", fake_home(md, md, dict(linked, hooks={"Stop": []}),
                                                             {"Stop": []}, toml), 0),
        ("plugin enabled in Codex only", fake_home(md, md, linked, None,
                                                   toml + '[plugins."extra@m"]\nenabled = true\n'), 1),
        ("Codex instruction key", fake_home(md, md, linked, None, 'developer_instructions = "x"\n' + toml), 1),
    ]
    for name, home, want in cases:
        got = real.problems(home, require_both=False)
        check(f"parity: {name}", len(got) == want, f"want {want} problems, got {got}")
    override = fake_home(md, "# old\n", linked, None, toml)
    with open(os.path.join(override, ".codex", "AGENTS.override.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    check("parity: AGENTS.override.md wins over AGENTS.md", real.problems(override, require_both=False) == [])


# ---------- live ----------

def test_live():
    work = os.path.expanduser("~/yt-work")
    env = REAL_ENV   # the machine's real environment, without the fakes set for the scenarios
    run = lambda *a: subprocess.run([os.path.join(BIN, a[0]), *a[1:]], env=env, capture_output=True, text=True)  # noqa: E731
    results_md, states = {}, {}
    for rt in RUNTIMES:
        tid = f"contract-live-{rt}"
        task = os.path.join(work, tid)
        shutil.rmtree(task, ignore_errors=True)
        run("yt", "forget", tid)
        os.makedirs(os.path.join(task, "in"))
        with open(os.path.join(task, "in", "sample.txt"), "w", encoding="utf-8") as fh:
            fh.write("Hello title\nsecond\nthird\n")
        with open(os.path.join(task, "in", "BRIEF.md"), "w", encoding="utf-8") as fh:
            fh.write("Read in/sample.txt. Write out/result.md with exactly two lines and nothing else:\n"
                     "`title: <first line of the file>` and `lines: <number of lines>`.\n")
        r = run("yt-spawn", tid, "yt-ops", "--runtime", rt, "--deadline", "15m")
        check(f"live {rt}: spawn", r.returncode == 0, r.stderr.strip())
        end = time.time() + 600
        while time.time() < end and (json.load(open(os.path.join(task, "out", "status.json")))
                                     .get("state") not in core.FINAL):
            time.sleep(5)
        states[rt] = json.load(open(os.path.join(task, "out", "status.json"))).get("state")
        try:
            results_md[rt] = open(os.path.join(task, "out", "result.md"), encoding="utf-8").read().strip()
        except OSError:
            results_md[rt] = None
        run("yt", "stop", tid)
        run("yt", "forget", tid)
        check(f"live {rt}: done", states[rt] == "done", f"state {states[rt]}")
    check("live: same result.md", results_md["claude"] == results_md["codex"] is not None, repr(results_md))
    for rt in RUNTIMES:
        shutil.rmtree(os.path.join(work, f"contract-live-{rt}"), ignore_errors=True)


def main(argv):
    plat = ytplatform.load()
    if plat.sandbox_problem():
        print(f"skip: {plat.sandbox_problem()}")
        return 0
    try:
        test_scenarios()
        test_build()
        test_parity()
        if "--live" in argv:
            test_live()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    print(f"passed={results['pass']} failed={results['fail']}")
    return 0 if results["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
