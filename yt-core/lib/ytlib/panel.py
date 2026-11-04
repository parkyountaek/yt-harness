"""The control panel: one text view of what needs the human, what runs, and harness health.

Built only from the coordinator's own data (session list, status files, events,
metrics), so it reads the same for Claude and Codex and needs no runtime UI.
"""
import datetime as _dt
import os
import subprocess
import sys

from . import core
from . import lab
from . import metrics
from . import runners

RETIRE_DAYS = 60


def _events():
    return lab._lines(core.EVENTS)


def needs_and_running():
    needs, running = [], []
    collected = {d.get("taskId") for d in _events() if d.get("event") == "collect"}
    for task_id, e in sorted(core.load_sessions()["sessions"].items()):
        status = core.read_status(core.task_dir(task_id)) or {}
        state = status.get("state")
        deadline = core.safe_deadline(e.get("deadline"))
        try:
            alive = bool(e.get("runnerHandle")) and runners.load(e["runner"]).alive(e["runnerHandle"])
        except Exception:  # noqa: BLE001  a broken runner must not break the panel
            alive = False
        if state == "waiting-human":
            needs.append(f"{task_id}: question: {str(status.get('question', ''))[:100]}  ->  yt answer {task_id} \"...\"")
        elif state == "stale" or (state == "running" and deadline and core.now() > deadline):
            needs.append(f"{task_id}: past its deadline  ->  yt attach {task_id}, yt resume or yt stop")
        elif state in core.FINAL and task_id not in collected:
            needs.append(f"{task_id}: {state}, not collected  ->  yt collect {task_id}")
        elif state == "running" and not alive:
            needs.append(f"{task_id}: run ended without reporting  ->  yt attach {task_id}, then yt resume")
        elif state == "running":
            running.append(f"{task_id}: {e['harness']} on {e['runtime']} ({e['runner']}), deadline {e.get('deadline')}")
    return needs, running


def harness_rows(days=30):
    now = core.now()
    since = now - _dt.timedelta(days=days)
    last_used, created = {}, {}
    for d in _events():
        t = core.safe_deadline(d.get("at"))
        if d.get("event") == "spawn" and d.get("ok") and t:
            last_used[d.get("harness")] = max(t, last_used.get(d.get("harness"), t))
        if d.get("event") == "harness-new" and t:
            created[d.get("harness")] = t
    recent = {}
    for d in lab._lines(metrics.METRICS):
        t = core.safe_deadline(d.get("at"))
        if t and t >= since:
            recent.setdefault(d["harness"], []).append(d["success"])
    off = core.disabled_harnesses()
    rows, retire = [], []
    for name in core.harness_names():
        h = core.load_harness(name)
        used = last_used.get(name)
        results = recent.get(name, [])
        rows.append((name, str(h.get("version")), "off" if name in off else "on",
                     "yes" if h.get("experimental") else "no", used.date().isoformat() if used else "never",
                     str(len(results)), f"{100 * sum(results) / len(results):.0f}%" if results else "-"))
        reference = used or created.get(name)
        if reference and (now - reference).days >= RETIRE_DAYS and name not in off:
            retire.append(f"{name}: not used for {(now - reference).days} days  ->  yt harness off {name}, "
                          "or delete its folder")
    return rows, retire


def doctor_problems():
    r = subprocess.run([sys.executable, os.path.join(core.CORE, "bin", "yt-doctor"), "--quiet"],
                       capture_output=True, text=True)
    return [line for line in r.stdout.splitlines() if line.startswith(("[problem]", "[note]"))]


def render(with_doctor=True):
    needs, running = needs_and_running()
    rows, retire = harness_rows()
    out = ["== Needs you"] + (needs or ["nothing"])
    out += ["", "== Running"] + (running or ["nothing"])
    head = ("HARNESS", "VERSION", "STATE", "EXPERIMENTAL", "LAST USED", "TASKS 30D", "SUCCESS 30D")
    widths = [max(len(r[i]) for r in rows + [head]) for i in range(len(head))]
    out += ["", "== Harnesses"] + ["  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in [head] + rows]
    if retire:
        out += ["", "== Retire?"] + retire
    found = lab.candidates()
    if found:
        out += ["", "== Harness candidates"] + [f"{k}: no route, came up {n} times  ->  yt harness new" for k, n in found]
    if with_doctor:
        out += ["", "== Health"] + (doctor_problems() or ["yt-doctor: ok"])
    return "\n".join(out)
