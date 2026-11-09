"""Move the local layer (~/yt-local/) to another machine without GitHub.

An export is a tar.gz with a manifest. It holds the settings a human wrote (config,
routes, blocked lists) and, with --data, the numeric records (metrics, evals,
events). Run state (session list, runner state, locks) is never exported: it
belongs to the machine that ran the tasks. Paths under the home folder are written
as ~/..., so they resolve on the new machine. config.json "repo" is left out;
yt-setup sets it for the checkout on each machine.

Import merges, never replaces: settings from the archive are added or update the
same key, local entries the archive does not mention stay, record lines are
appended once. Every file that changes is backed up first.
"""
import hashlib
import io
import json
import os
import tarfile
import time

from . import core

SCHEMA = 1
KIND = "yt-local-export"
SETTINGS = ("config.json", "routes.json", "active.json", "blocked-terms.txt", "blocked-paths.txt", "mods-theme.json")
RECORDS = ("data/metrics.jsonl", "data/evals.jsonl", "data/events.jsonl")
MANIFEST = "manifest.json"
MAX_BYTES = 64 * 1024 * 1024


# ---------- export ----------

def _home_relative(value):
    home = core.HOME.rstrip("/") + "/"
    if isinstance(value, str):
        return "~/" + value[len(home):] if value.startswith(home) else ("~" if value == core.HOME else value)
    if isinstance(value, list):
        return [_home_relative(v) for v in value]
    if isinstance(value, dict):
        return {k: _home_relative(v) for k, v in value.items()}
    return value


def _export_bytes(name):
    path = os.path.join(core.LOCAL, name)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        raw = f.read()
    if name.endswith(".json"):
        data = json.loads(raw.decode("utf-8"))
        if name == "config.json":
            data.pop("repo", None)
        raw = (json.dumps(_home_relative(data), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return raw


def _inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def export(dest, with_data=False):
    """Write the archive to dest (mode 600). Returns the list of files in it."""
    dest = os.path.abspath(os.path.expanduser(dest))
    if _inside(dest, core.REPO):
        raise ValueError("the archive may hold blocked terms; write it outside the repository")
    if _inside(dest, core.LOCAL):
        raise ValueError("write the archive outside the local layer it exports")
    if os.path.exists(dest):
        raise ValueError(f"{dest} exists; choose another name")
    files = {}
    for name in SETTINGS + (RECORDS if with_data else ()):
        raw = _export_bytes(name)
        if raw is not None:
            files[name] = raw
    manifest = {"schema": SCHEMA, "kind": KIND, "createdAt": core.iso(core.now()),
                "files": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, raw in [(MANIFEST, json.dumps(manifest, indent=2).encode("utf-8"))] + sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(raw), 0o600, int(time.time())
            tar.addfile(info, io.BytesIO(raw))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(buf.getvalue())
    return sorted(files)


# ---------- import ----------

def read_archive(src):
    """Return {name: bytes}. Rejects the whole archive on anything unexpected."""
    allowed = set(SETTINGS) | set(RECORDS)
    found = {}
    try:
        with tarfile.open(os.path.expanduser(src), mode="r:gz") as tar:
            for m in tar.getmembers():
                if not m.isfile() or m.name not in allowed | {MANIFEST} or m.name in found:
                    raise ValueError(f"unexpected entry in the archive: {m.name!r}")
                if m.size > MAX_BYTES:
                    raise ValueError(f"{m.name} is larger than {MAX_BYTES} bytes")
                found[m.name] = tar.extractfile(m).read()
    except (tarfile.TarError, EOFError) as e:
        raise ValueError(f"not a readable yt-export archive ({e})") from None
    if MANIFEST not in found:
        raise ValueError("not a yt-export archive (no manifest)")
    manifest = json.loads(found.pop(MANIFEST).decode("utf-8"))
    if manifest.get("kind") != KIND or manifest.get("schema") != SCHEMA:
        raise ValueError("not a yt-export archive of schema 1")
    sums = manifest.get("files") or {}
    if set(sums) != set(found):
        raise ValueError("the archive does not match its manifest")
    for name, raw in found.items():
        if hashlib.sha256(raw).hexdigest() != sums[name]:
            raise ValueError(f"{name} does not match its manifest checksum")
    return found


def _read_local(name):
    path = os.path.join(core.LOCAL, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def _merge_json(name, local, incoming):
    if name == "config.json":
        incoming.pop("repo", None)
    if name == "routes.json":
        by_kind = {r.get("taskKind"): r for r in local.get("routes", [])}
        for r in incoming.get("routes", []):
            by_kind[r.get("taskKind")] = r
        merged = dict(local, **{k: v for k, v in incoming.items() if k != "routes"})
        merged["routes"] = list(by_kind.values())
        return merged
    merged = dict(local)
    for k, v in incoming.items():
        merged[k] = {**local[k], **v} if isinstance(v, dict) and isinstance(local.get(k), dict) else v
    return merged


def _merge_lines(local, incoming):
    lines = local.splitlines() if local else []
    seen = set(lines)
    for line in incoming.splitlines():
        if line not in seen:
            lines.append(line)
            seen.add(line)
    return "\n".join(lines) + ("\n" if lines else "")


def plan(files):
    """[(name, action, new_text)] with action add, update, or same."""
    out = []
    for name in sorted(files):
        incoming = files[name].decode("utf-8")
        local = _read_local(name)
        if name.endswith(".json"):
            merged = _merge_json(name, json.loads(local) if local else {}, json.loads(incoming))
            text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
            same = local is not None and json.loads(local) == merged
        else:
            text = _merge_lines(local, incoming)
            same = local is not None and local == text
        out.append((name, "same" if same else ("update" if local is not None else "add"), text))
    return out


def apply(changes):
    """Write the planned changes; back up each file that changes. Returns the backup folder or None."""
    backup = None
    for name, action, text in changes:
        if action == "same":
            continue
        path = os.path.join(core.LOCAL, name)
        if action == "update":
            if backup is None:
                backup = os.path.join(core.LOCAL, "backups", "import-" + time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(os.path.dirname(os.path.join(backup, name)), exist_ok=True)
            with open(path, "rb") as src, open(os.path.join(backup, name), "wb") as dst:
                dst.write(src.read())
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".import-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    return backup


def warnings():
    """Things to fix by hand after an import: vault folders or harnesses this machine lacks."""
    out = [f"vault {k}: {p} does not exist here; create it or fix vaults in config.json"
           for k, p in core.vaults().items() if not os.path.isdir(p)]
    names = set(core.harness_names())
    routes = (core.read_json(os.path.join(core.LOCAL, "routes.json"), {}) or {}).get("routes", [])
    out += [f"route {r.get('taskKind')}: harness {r.get('harness')} is not in this checkout"
            for r in routes if r.get("harness") not in names]
    return out
