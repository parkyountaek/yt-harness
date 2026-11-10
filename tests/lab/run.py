#!/usr/bin/env python3
"""Roadmap frameworks: improvement verdicts, eval records, route-miss candidates, case cards.

Runs against a throwaway local layer (YT_LOCAL); nothing touches the real data.
Usage: tests/lab/run.py      exit 0 when every check passes
"""
import json
import os
import sys
import tempfile
import time

LOCAL = tempfile.mkdtemp(prefix="ytlab")
os.environ.update(YT_LOCAL=LOCAL, YT_WORK=os.path.join(LOCAL, "work"))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "yt-core", "lib"))
from ytlib import core, lab, metrics, panel, watch  # noqa: E402

results = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))


def write_metrics(rows):
    os.makedirs(core.DATA, exist_ok=True)
    with open(metrics.METRICS, "w") as f:
        for i, (version, success, tokens, turns) in enumerate(rows):
            f.write(json.dumps({"taskId": f"t{i}", "harness": "h", "harnessVersion": version, "runtime": "claude",
                                "success": success, "state": "done" if success else "failed",
                                "tokens": {"input": tokens, "cacheRead": 0, "cacheWrite": 0, "output": 0},
                                "turns": turns, "toolCalls": 1}) + "\n")


def main():
    write_metrics([("0.1.0", True, 100, 3)] * 3 + [("0.2.0", True, 80, 3)] * 3)
    check("improve: cheaper with success held is better", lab.improve_report("h")[1].startswith("better"))
    write_metrics([("0.1.0", True, 100, 3)] * 3 + [("0.2.0", False, 50, 1)] + [("0.2.0", True, 50, 1)] * 2)
    check("improve: a success drop is worse even when cheaper", lab.improve_report("h")[1].startswith("worse"))
    write_metrics([("0.1.0", True, 100, 3)] * 3 + [("0.2.0", True, 50, 1)])
    check("improve: too few tasks is unclear", lab.improve_report("h")[1].startswith("unclear"))
    write_metrics([("0.9.0", True, 100, 3)] * 3 + [("0.10.0", True, 90, 3)] * 3)
    rows, _ = lab.improve_report("h")
    check("improve: versions sort numerically", [r["version"] for r in rows] == ["0.9.0", "0.10.0"])
    # an eval verdict overrides the final state
    write_metrics([("0.1.0", True, 100, 3)] * 3 + [("0.2.0", True, 80, 3)] * 3)
    e = {"harness": "h", "runtime": "claude"}
    lab.eval_record("t3", e, {"harnessVersion": "0.2.0"}, "fail", "human", human_fixed=True)
    check("improve: a human fail verdict counts against the version", lab.improve_report("h")[1].startswith("worse"))
    try:
        lab.eval_record("t3", e, {}, "great", "human")
        check("eval: free-form verdicts are refused", False)
    except ValueError:
        check("eval: free-form verdicts are refused", True)
    line = lab.latest_evals()["t3"]
    check("eval: only enumerations and ids are stored",
          set(line) == {"at", "taskId", "harness", "harnessVersion", "runtime", "verdict", "judge", "humanFixed"})
    # route misses become candidates at two
    lab.route_miss("summarise-logs")
    check("candidates: one miss is not a candidate", lab.candidates() == [])
    lab.route_miss("summarise-logs")
    check("candidates: two misses are", lab.candidates() == [("summarise-logs", 2)])
    # case card: counts and kinds, never names or text
    task = core.task_dir("card-1")
    os.makedirs(os.path.join(task, "in"))
    for name in ("customer-acme.csv", "notes.txt", "BRIEF.md"):
        open(os.path.join(task, "in", name), "w").write("secret content\n")
    card = lab.case_card("card-1", {"harness": "h", "runtime": "codex", "runner": "tmux"},
                         {"harnessVersion": "0.1.0", "state": "done"})
    text = json.dumps(card)
    check("card: input kinds by extension", card["inputKinds"] == {".csv": 1, ".txt": 1})
    check("card: no file names or content", "acme" not in text and "secret" not in text and "notes" not in text)
    # panel: what needs the human, and retirement hints
    for tid, state in (("p-wait", "waiting-human"), ("p-done", "done"), ("p-old", "done")):
        os.makedirs(os.path.join(core.task_dir(tid), "out"), exist_ok=True)
        core.write_status(core.task_dir(tid), {"state": state, "question": "Which file?"})
    core.save_sessions({"schema": 1, "sessions": {t: {"harness": "yt-ops", "runtime": "claude", "runner": "tmux",
                                                       "runnerHandle": None, "deadline": "2099-01-01T00:00:00+00:00"}
                                                   for t in ("p-wait", "p-done", "p-old")}})
    core.log_event("collect", taskId="p-old")
    needs, _ = panel.needs_and_running()
    text = "\n".join(needs)
    check("panel: a question needs the human", "p-wait: question" in text)
    check("panel: an uncollected result needs the human", "p-done: done, not collected" in text)
    check("panel: a collected result does not", "p-old" not in text)
    snap = panel.snapshot()
    by_id = {t["taskId"]: t for t in snap["tasks"]}
    check("snapshot: same needs as the text panel",
          by_id.get("p-wait", {}).get("need") == "question" and by_id.get("p-done", {}).get("need") == "collect"
          and "p-old" not in by_id, by_id)
    check("snapshot: counts match the tasks", snap["counts"]["question"] == 1 and snap["counts"]["collect"] == 1)
    check("snapshot: the question and its command are there",
          by_id["p-wait"]["question"] == "Which file?" and by_id["p-wait"]["command"].startswith("yt answer p-wait"))
    check("snapshot: each task has a time to tell repeats apart", all(t["since"] for t in snap["tasks"]))
    # yt watch: told once, shared file, same keys as the work-alerts mod
    sent = []
    first = watch.tell(snap, sent.append)
    check("watch: each need is told once", len(first) == 2 and watch.tell(snap, sent.append) == [] and len(sent) == 2,
          sent)
    check("watch: the question and its command are in the notice",
          any(t.startswith("yt p-wait asks: Which file? -> yt answer p-wait") for t in first), first)
    with open(watch.TOLD) as f:
        told = json.load(f)["told"]
    check("watch: told keys use the mod's format (task:need:since)",
          sorted(k.split(":")[:2] for k in told) == [["p-done", "collect"], ["p-wait", "question"]], told)
    time.sleep(1.1)   # status times have one-second resolution
    core.write_status(core.task_dir("p-wait"), {"state": "waiting-human", "question": "Which file?"})
    check("watch: asked again (new status time) is told again", len(watch.tell(panel.snapshot(), sent.append)) == 1)
    core.write_status(core.task_dir("p-wait"), {"state": "done"})
    core.log_event("collect", taskId="p-wait")
    watch.tell(panel.snapshot(), sent.append)
    with open(watch.TOLD) as f:
        check("watch: a task that no longer needs you is dropped from the file",
              not any(k.startswith("p-wait:") for k in json.load(f)["told"]))
    text = watch.screen(panel.snapshot())
    check("watch: the screen lists needs and running tasks", "p-done: done, not collected" in text
          and "== Running" in text and "1 to collect" in text, text)
    with open(core.EVENTS, "a") as f:
        f.write(json.dumps({"at": "2026-01-01T00:00:00+00:00", "event": "spawn", "ok": True, "harness": "yt-ops"}) + "\n")
    _, retire = panel.harness_rows()
    check("panel: a harness unused for 60 days is a retire hint", any(r.startswith("yt-ops:") for r in retire))
    # deterministic evals: scripts in the harness folder judge a finished task
    hdir = os.path.join(LOCAL, "fake-harness")
    os.makedirs(os.path.join(hdir, "evals"))
    scripts = {"evals/has-title.py": "import sys, pathlib\n"
                                     "t = pathlib.Path(sys.argv[1], 'out', 'result.md').read_text()\n"
                                     "print('noise'); print('pass' if 'title' in t else 'fail')\n",
               "evals/long.sh": 'wc -l < "$1/out/result.md" | awk \'{print ($1 >= 5 ? "pass" : "fail")}\'\n',
               "evals/crash.py": "raise SystemExit(3)\n"}
    for rel, body in scripts.items():
        with open(os.path.join(hdir, rel), "w") as f:
            f.write(body)
    tdir = core.task_dir("e-1")
    os.makedirs(os.path.join(tdir, "out"), exist_ok=True)
    with open(os.path.join(tdir, "out", "result.md"), "w") as f:
        f.write("title: x\nlines: 3\n")
    got = dict(lab.run_evals({"evals": ["evals/has-title.py", "evals/long.sh"]}, hdir, tdir))
    check("evals: a passing and a failing script", got == {"evals/has-title.py": "pass", "evals/long.sh": "fail"}, got)
    check("evals: any fail makes the task fail", lab.eval_verdict(list(got.items())) == "fail")
    got = lab.run_evals({"evals": ["evals/has-title.py"]}, hdir, tdir)
    check("evals: all pass makes the task pass", lab.eval_verdict(got) == "pass", got)
    got = dict(lab.run_evals({"evals": ["evals/crash.py", "../escape.py", "evals/missing.py"]}, hdir, tdir))
    check("evals: a crash, a path outside the harness, a missing script are errors",
          set(got.values()) == {"error"} and len(got) == 3, got)
    check("evals: an error records nothing", lab.eval_verdict(list(got.items())) is None)
    check("evals: no evals, no verdict", lab.run_evals({"evals": []}, hdir, tdir) == [] and lab.eval_verdict([]) is None)
    # the shipped harness evals: the common contract plus each harness's own pattern
    core.write_status(tdir, {"taskId": "e-1", "state": "running"})
    got = dict(lab.run_evals(core.load_harness("yt-ops"), core.harness_dir("yt-ops"), tdir))
    check("harness evals: yt-ops fails a task that is not done", got == {"evals/result.py": "fail"}, got)
    core.write_status(tdir, {"taskId": "e-1", "state": "done"})
    got = dict(lab.run_evals(core.load_harness("yt-ops"), core.harness_dir("yt-ops"), tdir))
    check("harness evals: yt-ops passes a done task with a result", got == {"evals/result.py": "pass"}, got)
    for name, without, good in (("yt-code", "title: x\n", "abc1234 Fix the title\n"),
                                ("yt-wiki", "title: x\n", "Sources\n- inbox/2026-01-01-x.md\n"),
                                ("yt-improve", "title: x\n", "Check after 3 tasks with yt improve yt-ops.\n")):
        verdicts = []
        for text in (without, good):
            with open(os.path.join(tdir, "out", "result.md"), "w") as f:
                f.write(text)
            verdicts.append(dict(lab.run_evals(core.load_harness(name), core.harness_dir(name), tdir)))
        check(f"harness evals: {name} needs its pattern", [list(v.values()) for v in verdicts] == [["fail"], ["pass"]],
              verdicts)
    with open(os.path.join(tdir, "out", "result.md"), "w") as f:
        f.write("key: AKIA" + "ABCDEFGHIJKLMNOP\n")
    got = dict(lab.run_evals(core.load_harness("yt-ops"), core.harness_dir("yt-ops"), tdir))
    check("harness evals: a result yt-mask would mask fails", got == {"evals/result.py": "fail"}, got)
    # improvement proposals: the brief carries numbers and shapes, never task content
    lab.eval_record("e-1", {"harness": "h", "runtime": "claude"}, {"harnessVersion": "0.2.0"}, "fail")
    brief = lab.improve_brief("h")
    check("brief: the per-version table", "| 0.1.0 | 3 |" in brief and "| 0.2.0 |" in brief, brief[:400])
    check("brief: the comparison verdict", "Comparison of the last two versions:" in brief)
    check("brief: eval counts by verdict and judge", "- fail by human: 1" in brief, brief)
    check("brief: the scope", "only `h/skills/` and the `version:` line of `h/harness.yaml`" in brief)
    check("brief: no task text", "title: x" not in brief and "Which file?" not in brief)
    check("scope: skills and the version line", lab.improve_scope("h") == ["h/skills/", "h/harness.yaml:version"])
    print(f"passed={results['pass']} failed={results['fail']}")
    return 0 if results["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
