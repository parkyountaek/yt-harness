"""yt watch: a live view of the yt-harness tasks, with a desktop notice when one needs you.

Runs in any terminal, next to a Claude or a Codex session, so both runtimes get the
same view and the same alerts. It reads panel.snapshot(), the data the Claude mods
show. A need is told once: the told keys are kept in ~/yt-local/data/alerted.json,
shared with the work-alerts mod, so the two never announce the same thing twice.
"""
import json
import os
import shutil
import subprocess
import sys
import time

from . import core
from . import panel

TOLD = os.path.join(core.DATA, "alerted.json")
LABELS = (("question", "waiting"), ("deadline", "late"), ("ended", "ended"), ("collect", "to collect"),
          ("running", "running"))


def key(t):
    return f"{t['taskId']}:{t['need']}:{t.get('since') or ''}"


def alert_text(t):
    run = f" -> {t['command']}" if t.get("command") else ""
    if t["need"] == "question":
        return f"yt {t['taskId']} asks: {t.get('question', '')}{run}"
    if t["need"] == "collect":
        return f"yt {t['taskId']} {'failed' if t.get('state') == 'failed' else t.get('state') or 'done'}{run}"
    if t["need"] == "deadline":
        return f"yt {t['taskId']} is past its deadline{run}"
    return f"yt {t['taskId']} ended without reporting{run}"


def to_tell(snap, told):
    """(tasks to announce now, keys to keep): keys of tasks that no longer need you are dropped."""
    needing = [t for t in snap["tasks"] if t.get("need")]
    return [t for t in needing if key(t) not in told], [key(t) for t in needing]


def _read_told():
    try:
        with open(TOLD, encoding="utf-8") as f:
            return list(json.load(f).get("told") or [])
    except (OSError, ValueError, AttributeError):
        return []


def notify(text):
    """A desktop notice where the machine has one; nothing otherwise (the terminal still shows it)."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        quoted = text.replace("\\", "\\\\").replace('"', '\\"')
        cmd = ["osascript", "-e", f'display notification "{quoted}" with title "yt-harness"']
    elif shutil.which("notify-send"):
        cmd = ["notify-send", "yt-harness", text]
    else:
        return
    subprocess.run(cmd, capture_output=True, timeout=10, check=False)


def tell(snap, send=notify):
    """Announce each new need once; returns the texts announced."""
    told = _read_told()
    fresh, keep = to_tell(snap, told)
    if fresh or sorted(keep) != sorted(told):
        core.write_json_atomic(TOLD, {"told": keep})
    texts = [alert_text(t) for t in fresh]
    for text in texts:
        send(text)
    return texts


def summary(snap):
    parts = [f"{snap['counts'][k]} {label}" for k, label in LABELS if snap["counts"].get(k)]
    return " · ".join(parts) or "nothing"


def screen(snap, recent=()):
    out = [f"yt watch  {snap['at']}  {summary(snap)}", ""]
    needs = [t for t in snap["tasks"] if t.get("need")]
    running = [t for t in snap["tasks"] if not t.get("need")]
    out += ["== Needs you"] + ([f"  {t['harness']}/{t['runtime']}  {panel.need_line(t)}" for t in needs] or ["  nothing"])
    out += ["", "== Running"] + ([f"  {t['harness']}/{t['runtime']}  {t['taskId']} ({t['runner']}), deadline {t['deadline']}"
                                  for t in running] or ["  nothing"])
    if recent:
        out += ["", "== Told"] + [f"  {line}" for line in recent]
    return "\n".join(out)


def run(interval=15, once=False, send=notify):
    recent = []
    try:
        while True:
            snap = panel.snapshot()
            for text in tell(snap, send):
                recent = (recent + [f"{time.strftime('%H:%M:%S')}  {text}"])[-5:]
                if not once:
                    sys.stdout.write("\a")
            if not once and sys.stdout.isatty():
                sys.stdout.write("\033[H\033[2J")
            print(screen(snap, recent), flush=True)
            if once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
