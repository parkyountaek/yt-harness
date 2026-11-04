"""Per-task metrics from each runtime's own session log. Numbers only, never content.

One line per finished task in ~/yt-local/data/metrics.jsonl, in the same shape for
both runtimes:

  tokens        input (not cached), cacheRead, cacheWrite, output
  turns         prompts the session handled (start, resume, human answers)
  toolCalls     tool invocations
  bigOutputs    tool outputs over BIG_OUTPUT bytes, and their total bytes
  rereads       reads of a file already read in the same session
  compactions   context compactions
  subagents     subagents started
  success       final state was done

Sources: Claude ~/.claude/projects/<cwd>/<session>.jsonl (usage per message, deduped by
message id); Codex ~/.codex/sessions/**/rollout-*-<session>.jsonl (last cumulative
token_count). Main session only; subagent tokens are not included on either side.
"""
import glob
import json
import os
import re
import shlex

from . import core

METRICS = os.path.join(core.DATA, "metrics.jsonl")
BIG_OUTPUT = 10_000
READ_COMMANDS = {"cat", "head", "tail", "sed", "less", "more", "bat", "nl", "wc"}
SUBAGENT_TOOLS = re.compile(r"^(agent|task|spawn_agent|.*subagent.*)$", re.I)


def _lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def read_targets(command):
    """Files a shell command reads with a plain read tool (cat, sed -n, head, ...)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    if not tokens or os.path.basename(tokens[0]) not in READ_COMMANDS:
        return []
    files = []
    for tok in tokens[1:]:
        if tok in ("|", "&&", ";", ">", ">>"):
            break
        if not tok.startswith("-") and ("/" in tok or "." in tok) and not re.fullmatch(r"[\d,$p]+", tok):
            files.append(tok)
    return files


class Tally:
    def __init__(self):
        self.tokens = {"input": 0, "cacheRead": 0, "cacheWrite": 0, "output": 0}
        self.turns = self.tool_calls = self.compactions = self.subagents = 0
        self.big_outputs = self.big_bytes = self.rereads = 0
        self.read_seen = set()

    def read(self, path):
        if not path:
            return
        if path in self.read_seen:
            self.rereads += 1
        self.read_seen.add(path)

    def output(self, size):
        if size > BIG_OUTPUT:
            self.big_outputs += 1
            self.big_bytes += size

    def tool(self, name, command=None, path=None):
        self.tool_calls += 1
        if SUBAGENT_TOOLS.match(name or ""):
            self.subagents += 1
        self.read(path)
        for target in read_targets(command) if command else []:
            self.read(target)

    def result(self, task_id, runtime, harness, version, state, session_id):
        return {"at": core.iso(core.now()), "taskId": task_id, "runtime": runtime, "harness": harness,
                "harnessVersion": version, "sessionId": session_id, "success": state == "done",
                "state": state, "tokens": self.tokens, "turns": self.turns, "toolCalls": self.tool_calls,
                "bigOutputs": {"count": self.big_outputs, "bytes": self.big_bytes},
                "rereads": self.rereads, "compactions": self.compactions, "subagents": self.subagents}


def _size(content):
    if isinstance(content, str):
        return len(content.encode("utf-8", "replace"))
    if isinstance(content, list):
        return sum(_size(c.get("text", "")) if isinstance(c, dict) else _size(c) for c in content)
    return 0


def claude_log(out_dir, session_id):
    encoded = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(out_dir))
    path = os.path.join(core.HOME, ".claude", "projects", encoded, f"{session_id}.jsonl")
    return path if os.path.isfile(path) else None


def claude_tally(path):
    t, usage = Tally(), {}
    for d in _lines(path):
        kind = d.get("type")
        if kind == "assistant":
            m = d.get("message") or {}
            if m.get("id") and m.get("usage"):
                usage[m["id"]] = m["usage"]   # streamed chunks repeat the id; keep the last
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    t.tool(c.get("name"), inp.get("command"), inp.get("file_path") if c.get("name") == "Read" else None)
        elif kind == "user":
            for c in (d.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    t.output(_size(c.get("content")))
        elif kind == "system":
            sub = str(d.get("subtype", ""))
            if sub == "turn_duration":
                t.turns += 1
            elif "compact" in sub:
                t.compactions += 1
    for u in usage.values():
        t.tokens["input"] += u.get("input_tokens", 0)
        t.tokens["cacheRead"] += u.get("cache_read_input_tokens", 0)
        t.tokens["cacheWrite"] += u.get("cache_creation_input_tokens", 0)
        t.tokens["output"] += u.get("output_tokens", 0)
    return t


def codex_log(session_id):
    root = os.environ.get("CODEX_HOME") or os.path.join(core.HOME, ".codex")
    found = glob.glob(os.path.join(root, "sessions", "*", "*", "*", f"rollout-*-{session_id}.jsonl"))
    return max(found, key=os.path.getmtime) if found else None


def codex_tally(path):
    t, last = Tally(), None
    for d in _lines(path):
        p = d.get("payload") or {}
        kind = p.get("type")
        if d.get("type") == "compacted" or kind in ("context_compacted", "compacted"):
            t.compactions += 1
        if kind == "token_count" and p.get("info"):
            last = p["info"].get("total_token_usage") or last
        elif kind == "task_started":
            t.turns += 1
        elif kind in ("function_call", "custom_tool_call"):
            args = p.get("arguments") or p.get("input") or ""
            command = None
            if isinstance(args, str):
                try:
                    parsed = json.loads(args)
                    command = parsed.get("cmd") or parsed.get("command") if isinstance(parsed, dict) else None
                except ValueError:
                    command = args
            if isinstance(command, list):
                command = shlex.join(str(c) for c in command)
            t.tool(p.get("name"), command)
        elif kind in ("function_call_output", "custom_tool_call_output"):
            out = p.get("output")
            t.output(_size(out if isinstance(out, str) else json.dumps(out)))
    if last:
        cached = last.get("cached_input_tokens", 0)
        t.tokens.update(input=max(last.get("input_tokens", 0) - cached, 0), cacheRead=cached,
                        cacheWrite=last.get("cache_write_input_tokens", 0), output=last.get("output_tokens", 0))
    return t


def measure(task_id, entry, status):
    """Metrics for a task, or None when its session log cannot be found."""
    sid = entry.get("runtimeSessionId")
    if not sid:
        return None
    out_dir = os.path.join(core.task_dir(task_id), "out")
    if entry["runtime"] == "claude":
        path = claude_log(out_dir, sid)
        tally = claude_tally(path) if path else None
    else:
        path = codex_log(sid)
        tally = codex_tally(path) if path else None
    if tally is None:
        return None
    return tally.result(task_id, entry["runtime"], entry["harness"], status.get("harnessVersion"),
                        status.get("state"), sid)


def recorded(task_id, session_id):
    try:
        for d in _lines(METRICS):
            if d.get("taskId") == task_id and d.get("sessionId") == session_id:
                return True
    except OSError:
        pass
    return False


def record(task_id, entry, status):
    """Append once per (task, session) when the task is final. Returns the line or None."""
    if status.get("state") not in core.FINAL or recorded(task_id, entry.get("runtimeSessionId")):
        return None
    line = measure(task_id, entry, status)
    if line:
        os.makedirs(core.DATA, exist_ok=True)
        with open(METRICS, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line
