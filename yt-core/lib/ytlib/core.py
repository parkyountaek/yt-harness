"""Paths, harness.yaml parsing, status files, session registry, events. Standard library only."""
import datetime as _dt
import json
import os
import re
import tempfile

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
REPO = os.path.dirname(CORE)
HOME = os.path.expanduser("~")
LOCAL = os.environ.get("YT_LOCAL", os.path.join(HOME, "yt-local"))
WORK = os.environ.get("YT_WORK", os.path.join(HOME, "yt-work"))
DATA = os.path.join(LOCAL, "data")
SESSIONS = os.path.join(DATA, "sessions.json")
EVENTS = os.path.join(DATA, "events.jsonl")

STATES = ("running", "waiting-human", "done", "failed", "stale")
FINAL = ("done", "failed")
MAX_CONCURRENT = 3
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


# ---------- time ----------

def now():
    return _dt.datetime.now().astimezone().replace(microsecond=0)


def iso(t):
    return t.isoformat()


def parse_time(text):
    return _dt.datetime.fromisoformat(text)


def parse_deadline(text, start=None):
    """Accept '30m', '2h', '1d', '90s', or an ISO 8601 timestamp."""
    start = start or now()
    m = re.fullmatch(r"(\d+)([smhd])", text.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[unit]
        return start + _dt.timedelta(**{delta: n})
    t = parse_time(text)
    return t if t.tzinfo else t.astimezone()


# ---------- files ----------

def write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def log_event(kind, **fields):
    """Metadata only, never content."""
    os.makedirs(DATA, exist_ok=True)
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": iso(now()), "event": kind, **fields}, ensure_ascii=False) + "\n")


# ---------- harness.yaml (small YAML subset: scalars, inline lists, one nesting level) ----------

def _scalar(text):
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [] if not inner else [_scalar(x) for x in _split_list(inner)]
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def _split_list(inner):
    items, buf, quote = [], "", None
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            items.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(buf)
    return items


def _strip_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def parse_harness_yaml(text):
    root, current = {}, None
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, sep, value = line.strip().partition(":")
        if not sep:
            raise ValueError(f"cannot parse line: {raw!r}")
        if indent == 0:
            if value.strip() == "":
                current = root[key] = {}
            else:
                root[key] = _scalar(value)
                current = None
        elif current is not None:
            current[key] = _scalar(value)
        else:
            raise ValueError(f"unexpected indentation: {raw!r}")
    return root


def harness_dir(name):
    return os.path.join(REPO, name)


def load_harness(name):
    path = os.path.join(harness_dir(name), "harness.yaml")
    with open(path, encoding="utf-8") as f:
        data = parse_harness_yaml(f.read())
    if data.get("schema") != 1:
        raise ValueError(f"{path}: unsupported schema {data.get('schema')!r}")
    if data.get("id") != name:
        raise ValueError(f"{path}: id {data.get('id')!r} does not match folder {name!r}")
    return data


def resolve_policy(harness, task_dir):
    sandbox = harness.get("sandbox") or {}
    sub = lambda paths: [p.replace("<task-folder>", task_dir) for p in (paths or [])]  # noqa: E731
    return {"read": sub(sandbox.get("read")), "write": sub(sandbox.get("write"))}


# ---------- task folder and status ----------

def task_dir(task_id):
    return os.path.join(WORK, task_id)


def status_path(task_dir_):
    return os.path.join(task_dir_, "out", "status.json")


def result_path(task_dir_):
    return os.path.join(task_dir_, "out", "result.md")


def read_status(task_dir_):
    return read_json(status_path(task_dir_))


def write_status(task_dir_, status):
    status["updatedAt"] = iso(now())
    write_json_atomic(status_path(task_dir_), status)


# ---------- session registry ----------

def load_sessions():
    return read_json(SESSIONS, {"schema": 1, "sessions": {}})


def save_sessions(reg):
    write_json_atomic(SESSIONS, reg)
