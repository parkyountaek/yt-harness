"""Frameworks for the roadmap: new harnesses, evaluations, improvement reports, case cards.

Every record here is metadata: ids, versions, enumerations, and counts. Free text
from a task (inputs, results, reasons, human notes) is never stored, so the data
may leave the machine after a human check (see docs/roadmap.md).
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys

from . import core
from . import metrics

EVALS = os.path.join(core.DATA, "evals.jsonl")
VERDICTS = ("pass", "fail")
JUDGES = ("human", "model", "deterministic")
NAME = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def _lines(path):
    return list(metrics._lines(path)) if os.path.exists(path) else []


# ---------- new harness ----------

SKILL_TEMPLATE = """---
name: {name}-procedure
description: How to carry out a {name} work order. Use when a work order (TASK.md) names the {name} harness. Do not use outside a yt-harness sub-session.
---

# {name}

1. Read the work order (`TASK.md`) and every file it names under `in/`.
2. <the steps this harness adds>
3. Write `out/result.md`, answer first. Overwrite, never append.
4. Run `yt-status done`, or `yt-status failed --reason "<one sentence>"`.
"""


def harness_new(name, purpose):
    """Scaffold <name>/ from templates/harness.yaml, generate manifests, allowlist it."""
    if not NAME.match(name):
        raise ValueError("harness names are lowercase letters, digits, and dashes")
    target = os.path.join(core.REPO, name)
    if os.path.exists(target):
        raise ValueError(f"{name}/ already exists")
    with open(os.path.join(core.REPO, "templates", "harness.yaml"), encoding="utf-8") as f:
        text = f.read()
    text = text.replace("<harness-id>", name).replace("<one line for the marketplace listing>", purpose)
    text = text.replace("<one line>", purpose)
    os.makedirs(os.path.join(target, "skills", f"{name}-procedure"))
    with open(os.path.join(target, "harness.yaml"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(target, "skills", f"{name}-procedure", "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(SKILL_TEMPLATE.format(name=name))
    build = subprocess.run([sys.executable, os.path.join(core.CORE, "bin", "yt-build")], capture_output=True, text=True)
    if build.returncode != 0:
        shutil.rmtree(target)
        raise ValueError("yt-build failed: " + build.stderr.strip())
    allow = os.path.join(core.REPO, "allowlist.txt")
    with open(allow, encoding="utf-8") as f:
        lines = f.read().splitlines()
    if f"{name}/" not in lines:
        with open(allow, "a", encoding="utf-8") as f:
            f.write(f"{name}/\n")
    core.log_event("harness-new", harness=name)
    return target


def route_miss(kind):
    core.log_event("route-miss", taskKind=kind)


def candidates(threshold=2):
    """Task kinds with no route that came up `threshold` times or more."""
    routes = {r.get("taskKind") for r in (core.read_json(os.path.join(core.LOCAL, "routes.json"), {}) or {})
              .get("routes", [])}
    misses = collections.Counter(d.get("taskKind") for d in _lines(core.EVENTS) if d.get("event") == "route-miss")
    return [(k, n) for k, n in misses.most_common() if n >= threshold and k not in routes]


# ---------- evaluations ----------

def eval_record(task_id, entry, status, verdict, judge="human", human_fixed=False):
    if verdict not in VERDICTS or judge not in JUDGES:
        raise ValueError(f"verdict is one of {VERDICTS}, judge one of {JUDGES}")
    line = {"at": core.iso(core.now()), "taskId": task_id, "harness": entry["harness"],
            "harnessVersion": status.get("harnessVersion"), "runtime": entry["runtime"],
            "verdict": verdict, "judge": judge, "humanFixed": bool(human_fixed)}
    os.makedirs(core.DATA, exist_ok=True)
    with open(EVALS, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return line


def latest_evals():
    """The last verdict per task (a later judgement replaces an earlier one)."""
    return {d["taskId"]: d for d in _lines(EVALS)}


# ---------- improvement report ----------

def version_key(v):
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[.-]", str(v)))


def improve_report(harness):
    """Per version: tasks, success (eval verdict wins over the final state), avg tokens and turns."""
    evals = latest_evals()
    by_version = collections.defaultdict(list)
    for d in _lines(metrics.METRICS):
        if d.get("harness") == harness:
            ok = evals[d["taskId"]]["verdict"] == "pass" if d["taskId"] in evals else d.get("success")
            by_version[str(d.get("harnessVersion"))].append((ok, sum(d["tokens"].values()), d["turns"]))
    rows = []
    for v in sorted(by_version, key=version_key):
        xs = by_version[v]
        n = len(xs)
        rows.append({"version": v, "tasks": n, "success": sum(x[0] for x in xs) / n,
                     "tokens": sum(x[1] for x in xs) / n, "turns": sum(x[2] for x in xs) / n})
    verdict = None
    if len(rows) >= 2:
        old, new = rows[-2], rows[-1]
        if new["tasks"] < 3 or old["tasks"] < 3:
            verdict = "unclear: fewer than 3 tasks on a version"
        elif new["success"] < old["success"]:
            verdict = f"worse: success dropped ({old['success']:.0%} -> {new['success']:.0%})"
        elif new["tokens"] < old["tokens"] or new["turns"] < old["turns"]:
            verdict = "better: success held and tokens or turns dropped"
        else:
            verdict = "no gain: success held but tokens and turns did not drop"
    return rows, verdict


# ---------- case cards ----------

def case_card(task_id, entry, status):
    """Shape of a task without its content: what may leave the machine after a human check."""
    task = core.task_dir(task_id)
    kinds = collections.Counter()
    for root, _, files in os.walk(os.path.join(task, "in")):
        for name in files:
            if name != "BRIEF.md":
                kinds[os.path.splitext(name)[1].lower() or "(none)"] += 1
    events = [d for d in _lines(core.EVENTS) if d.get("taskId") == task_id]
    m = metrics.measure(task_id, entry, status) or {}
    evals = latest_evals().get(task_id, {})
    return {"schema": 1, "harness": entry["harness"], "harnessVersion": status.get("harnessVersion"),
            "runtime": entry["runtime"], "runner": entry.get("runner"), "finalState": status.get("state"),
            "inputKinds": dict(kinds), "humanAnswers": sum(d.get("event") == "answer" for d in events),
            "resumes": sum(d.get("event") == "resume" for d in events),
            "steps": m.get("toolCalls"), "turns": m.get("turns"), "tokens": m.get("tokens"),
            "verdict": evals.get("verdict"), "judge": evals.get("judge"), "humanFixed": evals.get("humanFixed")}
