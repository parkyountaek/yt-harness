#!/usr/bin/env python3
"""Metrics parity: the same synthetic session, written as a Claude log and as a Codex
log, must give the same metrics (tokens, turns, tool calls, rereads, big outputs,
subagents, compactions).

Usage: tests/metrics/run.py      exit 0 when every check passes
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "yt-core", "lib"))
from ytlib import metrics  # noqa: E402

BIG = "x" * 12_000


def claude_log(path):
    rows = [
        {"type": "user", "message": {"content": "start"}},
        {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 1, "output_tokens": 1}, "content": []}},
        {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 10, "cache_read_input_tokens": 100,
                                                                "cache_creation_input_tokens": 5, "output_tokens": 7},
                                          "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "in/a.txt"}},
                                                      {"type": "tool_use", "name": "Bash", "input": {"command": "cat in/a.txt"}},
                                                      {"type": "tool_use", "name": "Agent", "input": {"prompt": "p"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": BIG}]}},
        {"type": "system", "subtype": "turn_duration"},
        {"type": "system", "subtype": "compact_boundary"},
        {"type": "user", "isMeta": True, "message": {"content": "skill text, not a prompt"}},
        {"type": "user", "message": {"content": "the human's answer"}},
        {"type": "assistant", "message": {"id": "m2", "usage": {"input_tokens": 0, "output_tokens": 3}, "content": []}},
        {"type": "system", "subtype": "turn_duration"},
    ]
    with open(path, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def codex_log(path):
    ev = lambda p: {"type": "event_msg", "payload": p}  # noqa: E731
    item = lambda p: {"type": "response_item", "payload": p}  # noqa: E731
    rows = [
        {"type": "session_meta", "payload": {"id": "s"}},
        ev({"type": "task_started"}),
        item({"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "sed -n 1,5p in/a.txt"})}),
        item({"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "cat in/a.txt"})}),
        item({"type": "function_call", "name": "spawn_agent", "arguments": json.dumps({"message": "p"})}),
        item({"type": "function_call_output", "output": BIG}),
        {"type": "compacted", "payload": {}},
        ev({"type": "token_count", "info": {"total_token_usage": {"input_tokens": 110, "cached_input_tokens": 100,
                                                                  "cache_write_input_tokens": 5, "output_tokens": 7}}}),
        ev({"type": "task_started"}),
        ev({"type": "token_count", "info": {"total_token_usage": {"input_tokens": 110, "cached_input_tokens": 100,
                                                                  "cache_write_input_tokens": 5, "output_tokens": 10}}}),
    ]
    with open(path, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def main():
    d = tempfile.mkdtemp(prefix="ytmetrics")
    claude_log(os.path.join(d, "c.jsonl"))
    codex_log(os.path.join(d, "x.jsonl"))
    keep = lambda r: {k: v for k, v in r.items() if k not in ("at", "runtime")}  # noqa: E731
    c = keep(metrics.claude_tally(os.path.join(d, "c.jsonl")).result("t", "claude", "h", "1", "done", "s"))
    x = keep(metrics.codex_tally(os.path.join(d, "x.jsonl")).result("t", "codex", "h", "1", "done", "s"))
    want = {"tokens": {"input": 10, "cacheRead": 100, "cacheWrite": 5, "output": 10}, "turns": 2, "toolCalls": 3,
            "rereads": 1, "compactions": 1, "subagents": 1, "bigOutputs": {"count": 1, "bytes": 12_000}}
    passed = failed = 0
    for key, value in want.items():
        for name, got in (("claude", c), ("codex", x)):
            ok = got[key] == value
            passed += ok
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'} [{name}] {key}" + ("" if ok else f": want {value}, got {got[key]}"))
    ok = c == x
    passed += ok
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'} equivalent: whole metrics line")
    print(f"passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
