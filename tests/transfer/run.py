#!/usr/bin/env python3
"""yt-export / yt-import: what is packed, path rewriting, merging, backups, rejection.

Runs against throwaway local layers (YT_LOCAL); nothing touches the real data.
Usage: tests/transfer/run.py      exit 0 when every check passes
"""
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile

ROOT = tempfile.mkdtemp(prefix="yttransfer")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
BIN = os.path.join(REPO, "yt-core", "bin")
HOME = os.path.expanduser("~")
results = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))


def run(cmd, local, *args):
    env = dict(os.environ, YT_LOCAL=local, YT_REPO=REPO)
    return subprocess.run([sys.executable, os.path.join(BIN, cmd), *args], capture_output=True, text=True, env=env)


def write(local, name, text):
    path = os.path.join(local, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(local, name):
    with open(os.path.join(local, name), encoding="utf-8") as f:
        return f.read()


def members(path):
    with tarfile.open(path) as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}


def main():
    src, dst = os.path.join(ROOT, "src"), os.path.join(ROOT, "dst")
    write(src, "config.json", json.dumps({"repo": "/elsewhere/yt-harness",
                                          "vaults": {"notes": os.path.join(HOME, "notes", "work")}}))
    write(src, "routes.json", json.dumps({"schema": 1, "routes": [
        {"taskKind": "read-check", "harness": "yt-ops", "folderKind": "neutral", "repo": None},
        {"taskKind": "log-triage", "harness": "no-such-harness", "folderKind": "neutral", "repo": None}]}))
    write(src, "blocked-terms.txt", "# terms\nexample-corp\n")
    write(src, "blocked-paths.txt", "# paths\n")
    write(src, "active.json", '{ "schema": 1, "projects": {} }\n')
    write(src, "data/metrics.jsonl", '{"taskId": "a"}\n')
    write(src, "data/sessions.json", '{"sessions": {}}\n')

    plain, full = os.path.join(ROOT, "plain.tar.gz"), os.path.join(ROOT, "full.tar.gz")
    r = run("yt-export", src, plain)
    check("export: writes the archive", r.returncode == 0 and os.path.isfile(plain), r.stderr)
    check("export: archive is private (mode 600)", oct(os.stat(plain).st_mode & 0o777) == "0o600")
    got = members(plain)
    check("export: settings only without --data",
          set(got) == {"manifest.json", "config.json", "routes.json", "blocked-terms.txt",
                       "blocked-paths.txt", "active.json"}, sorted(got))
    cfg = json.loads(got["config.json"])
    check("export: repo is left out", "repo" not in cfg, cfg)
    check("export: home paths become ~/", cfg["vaults"]["notes"] == "~/notes/work", cfg)
    r = run("yt-export", src, full, "--data")
    got = members(full)
    check("export: --data adds records, never the session list",
          "data/metrics.jsonl" in got and "data/sessions.json" not in got, sorted(got))
    check("export: refuses to overwrite", run("yt-export", src, plain).returncode == 1)
    check("export: refuses a path inside the repo",
          run("yt-export", src, os.path.join(REPO, "x.tar.gz")).returncode == 1
          and not os.path.exists(os.path.join(REPO, "x.tar.gz")))
    check("export: refuses a path inside the local layer",
          run("yt-export", src, os.path.join(src, "x.tar.gz")).returncode == 1)

    write(dst, "config.json", json.dumps({"repo": REPO, "vaults": {"home": "~/home-notes"}}))
    write(dst, "routes.json", json.dumps({"schema": 1, "routes": [
        {"taskKind": "read-check", "harness": "yt-wiki", "folderKind": "neutral", "repo": None},
        {"taskKind": "local-only", "harness": "yt-ops", "folderKind": "neutral", "repo": None}]}))
    write(dst, "blocked-terms.txt", "# terms\nlocal-term\n")
    write(dst, "data/metrics.jsonl", '{"taskId": "a"}\n{"taskId": "b"}\n')

    r = run("yt-import", dst, full, "--dry-run")
    check("import: dry run changes nothing", r.returncode == 0 and "local-term" in read(dst, "blocked-terms.txt")
          and "example-corp" not in read(dst, "blocked-terms.txt"), r.stdout + r.stderr)
    r = run("yt-import", dst, full)
    check("import: succeeds", r.returncode == 0, r.stdout + r.stderr)
    cfg = json.loads(read(dst, "config.json"))
    check("import: keeps this machine's repo", cfg["repo"] == REPO, cfg)
    check("import: merges vaults by name", cfg["vaults"] == {"home": "~/home-notes", "notes": "~/notes/work"}, cfg)
    routes = {x["taskKind"]: x["harness"] for x in json.loads(read(dst, "routes.json"))["routes"]}
    check("import: archive route wins, local-only route stays",
          routes == {"read-check": "yt-ops", "local-only": "yt-ops", "log-triage": "no-such-harness"}, routes)
    terms = read(dst, "blocked-terms.txt").splitlines()
    check("import: blocked terms are a union", "local-term" in terms and "example-corp" in terms, terms)
    check("import: records appended once", read(dst, "data/metrics.jsonl").count('"a"') == 1
          and '"b"' in read(dst, "data/metrics.jsonl"))
    backups = os.path.join(dst, "backups")
    check("import: previous files backed up", os.path.isdir(backups) and any(
        "local-term" in open(os.path.join(d, f)).read() for d, _, fs in os.walk(backups) for f in fs
        if f == "blocked-terms.txt"))
    check("import: notes a missing vault and a missing harness",
          "vault notes" in r.stdout and "no-such-harness" in r.stdout, r.stdout)
    r = run("yt-import", dst, full)
    check("import: second run finds nothing new", r.returncode == 0 and "[  update]" not in r.stdout
          and "[   add]" not in r.stdout and "backed up" not in r.stdout, r.stdout)

    def bad_archive(path, extra=None, tamper=False):
        data = members(full)
        if extra:
            data[extra] = b"x"
        if tamper:
            data["blocked-terms.txt"] = b"changed\n"
        with tarfile.open(path, "w:gz") as tar:
            for name, raw in data.items():
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
        return path

    before = read(dst, "blocked-terms.txt")
    for label, path in [("an unexpected file", bad_archive(os.path.join(ROOT, "b1.tar.gz"), extra="../escape")),
                        ("a path outside the layer", bad_archive(os.path.join(ROOT, "b2.tar.gz"), extra="data/sessions.json")),
                        ("a checksum mismatch", bad_archive(os.path.join(ROOT, "b3.tar.gz"), tamper=True))]:
        r = run("yt-import", dst, path)
        check(f"import: rejects {label}", r.returncode == 1 and read(dst, "blocked-terms.txt") == before,
              r.stdout + r.stderr)
    r = run("yt-import", dst, os.path.join(dst, "config.json"))
    check("import: rejects a file that is not an archive, without a traceback",
          r.returncode == 1 and "Traceback" not in r.stderr and "not a readable" in r.stderr, r.stderr[-300:])

    print(f"\n{results['pass']} passed, {results['fail']} failed")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
