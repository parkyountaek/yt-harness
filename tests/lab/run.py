#!/usr/bin/env python3
"""Roadmap frameworks: improvement verdicts, eval records, route-miss candidates, case cards.

Runs against a throwaway local layer (YT_LOCAL); nothing touches the real data.
Usage: tests/lab/run.py      exit 0 when every check passes
"""
import json
import os
import sys
import tempfile

LOCAL = tempfile.mkdtemp(prefix="ytlab")
os.environ.update(YT_LOCAL=LOCAL, YT_WORK=os.path.join(LOCAL, "work"))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "yt-core", "lib"))
from ytlib import core, lab, metrics  # noqa: E402

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
    print(f"passed={results['pass']} failed={results['fail']}")
    return 0 if results["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
