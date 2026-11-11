#!/usr/bin/env python3
"""Instruction files stay under 200 lines (rule in AGENTS.md).

Checks AGENTS.md, every SKILL.md, plugin agents (agents/*.md), and the work order
template in yt-spawn, as git tracks them.

Usage: tests/instructions/run.py [--staged]
  --staged   check the index (what is about to be committed); used by .githooks/pre-commit
Exit 0 when every file is under the limit; 1 otherwise, or when the check cannot run.
"""
import re
import subprocess
import sys

LIMIT = 200
TEMPLATE = "yt-core/bin/yt-spawn"


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def main():
    staged = "--staged" in sys.argv[1:]
    root = git("rev-parse", "--show-toplevel").decode().strip()

    def read(path):
        if staged:
            return git("-C", root, "show", f":{path}").decode("utf-8", "replace")
        with open(f"{root}/{path}", encoding="utf-8", errors="replace") as f:
            return f.read()

    paths = [p for p in git("-C", root, "ls-files", "-z").decode().split("\0") if p]
    targets = [p for p in paths if p == "AGENTS.md" or p.endswith("/SKILL.md")
               or re.search(r"(^|/)agents/[^/]+\.md$", p)]
    fail = []
    for path in targets:
        n = len(read(path).splitlines())
        if n >= LIMIT:
            fail.append(f"{path}: {n} lines")
    m = re.search(r'TASK_TEMPLATE = """(.*?)"""', read(TEMPLATE), re.S)
    if not m:
        fail.append(f"{TEMPLATE}: TASK_TEMPLATE not found")
    elif len(m.group(1).splitlines()) >= LIMIT:
        fail.append(f"TASK.md template: {len(m.group(1).splitlines())} lines")
    for line in fail:
        print(f"FAIL {line} (limit {LIMIT})")
    if not fail:
        print(f"instruction files ok ({len(targets) + 1} checked, limit {LIMIT} lines)")
    return 1 if fail else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001  a check that cannot run must block, not pass
        print(f"FAIL the instruction check could not run: {e}")
        sys.exit(1)
