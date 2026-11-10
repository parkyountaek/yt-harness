"""Shared checks for harness `evals:` scripts (see docs/roadmap.md, Run evaluation).

A harness eval is a short script in the harness folder that calls main() with the
patterns its result must show. Every eval also checks the common contract: the task
reported done, out/result.md is not empty, and yt-mask finds nothing in it.
"""
import os
import re
import sys

from . import core
from . import mask


def problems(task_dir, patterns=()):
    """Why the task's result fails the contract; empty when it passes."""
    out = []
    state = (core.read_status(task_dir) or {}).get("state")
    if state != "done":
        out.append(f"state is {state}, not done")
    try:
        with open(core.result_path(task_dir), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    if not text.strip():
        return out + ["out/result.md is missing or empty"]
    if mask.scan(text):
        out.append("result.md has something yt-mask would mask")
    for name, pattern in patterns:
        if not re.search(pattern, text, re.MULTILINE):
            out.append(f"result.md does not show {name}")
    return out


def main(patterns=()):
    """Entry point for an eval script: prints the problems, then pass or fail."""
    found = problems(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("YT_TASK_DIR", ""), patterns)
    for p in found:
        print(p)
    print("fail" if found else "pass")
    return 0
