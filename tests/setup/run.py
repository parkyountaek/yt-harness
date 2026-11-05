#!/usr/bin/env python3
"""yt-setup's runtime status line step: what it changes in ~/.codex/config.toml and what it leaves.

Pure text in, text out; nothing on this machine is touched.
Usage: tests/setup/run.py      exit 0 when every check passes
"""
import os
import sys
import tomllib

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "yt-core", "lib"))
from ytlib import statusline  # noqa: E402

results = {"pass": 0, "fail": 0}
WANT = statusline.CODEX_ITEMS


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))


def line_of(text):
    return (tomllib.loads(text).get("tui") or {}).get("status_line")


def main():
    plugins = '[plugins."yt-core@yt-harness"]\nenabled = true\n'
    cases = {
        "empty file": "",
        "no [tui] table": 'model = "gpt"\n\n' + plugins,
        "only a [tui.x] subtable": plugins + "\n[tui.model_availability_nux]\nx = 1\n",
        "[tui] without status_line": "[tui]\nstatus_line_use_colors = true\n\n[tui.nux]\nx = 1\n" + plugins,
        "Codex default line": '[tui]\nstatus_line = ["model-with-reasoning", "current-dir"]\nstatus_line_use_colors = true\n'
                              "\n[tui.nux]\nx = 1\n",
    }
    for name, text in cases.items():
        new, state = statusline.codex_plan(text)
        ok = state == "set" and new is not None and line_of(new) == WANT
        check(f"sets the line: {name}", ok, (state, new))
        if ok:
            before, after = tomllib.loads(text) if text else {}, tomllib.loads(new)
            after.get("tui", {}).pop("status_line", None)
            before.get("tui", {}).pop("status_line", None)
            if not before.get("tui"):
                before.pop("tui", None)
                if after.get("tui") == {}:
                    after.pop("tui")
            check(f"changes nothing else: {name}", before == after, (before, after))
            check(f"a second run is a no-op: {name}", statusline.codex_plan(new) == (None, "ok"))
    custom = '[tui]\nstatus_line = ["model", "git-branch"]\n'
    check("leaves a line the human chose", statusline.codex_plan(custom) == (None, "custom"))
    multi = '[tui]\nstatus_line = [\n  "model-with-reasoning",\n  "current-dir",\n]\n'
    check("leaves a default written over several lines", statusline.codex_plan(multi) == (None, "custom"))
    dotted = 'tui.status_line = ["model-with-reasoning", "current-dir"]\n'
    check("leaves a dotted key outside a [tui] table", statusline.codex_plan(dotted) == (None, "custom"))
    check("refuses a file it cannot parse", statusline.codex_plan("[tui\nbroken") == (None, "unreadable"))
    print(f"passed={results['pass']} failed={results['fail']}")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
