#!/usr/bin/env python3
"""Repository guard for yt-harness.

Rejects commits and pushes that contain paths outside allowlist.txt or
content that must never reach GitHub (secrets, personal absolute paths,
locally configured blocked terms).

Usage:
  repo_guard.py pre-commit          check staged files
  repo_guard.py pre-push            check commits about to be pushed (stdin from git)
  repo_guard.py scan <rev-range>    check every commit in a range (e.g. for the public switch)

Exit codes: 0 clean, 1 violations found, 2 usage error.
Standard library only.
"""
import os
import re
import subprocess
import sys

ZERO_SHA = "0" * 40
NOREPLY = re.compile(r"^[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com$")

# Built-in content patterns. Each is assembled so this file never matches itself.
PATTERNS = [
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api-secret-key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b")),
    ("private-key", re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY-----")),
    ("personal-path", re.compile(r"/(?:Users|home)/(?!<)[A-Za-z0-9._-]+/")),
]


def git(*args, binary=False):
    out = subprocess.run(["git", *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def repo_root():
    return git("rev-parse", "--show-toplevel").strip()


def load_allowlist(root):
    entries = []
    with open(os.path.join(root, "allowlist.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                entries.append(line)
    return entries


def load_blocked_terms():
    """Company-specific terms live outside the repo, in the local layer."""
    path = os.path.expanduser(os.environ.get("YT_BLOCKED_TERMS", "~/yt-local/blocked-terms.txt"))
    if not os.path.exists(path):
        return []
    terms = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line.lower())
    return terms


def path_allowed(path, allowlist):
    for entry in allowlist:
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry:
            return True
    return False


def check_content(path, data, blocked_terms):
    problems = []
    if b"\0" in data[:8192]:
        return problems  # binary file: path check only
    text = data.decode("utf-8", "replace")
    for name, pattern in PATTERNS:
        m = pattern.search(text)
        if m:
            line_no = text.count("\n", 0, m.start()) + 1
            problems.append(f"{path}:{line_no}: {name}")
    lower = text.lower()
    for term in blocked_terms:
        idx = lower.find(term)
        if idx >= 0:
            line_no = lower.count("\n", 0, idx) + 1
            problems.append(f"{path}:{line_no}: blocked term from local list")
    return problems


def check_files(files, read_blob, allowlist, blocked_terms):
    problems = []
    for path in files:
        if not path_allowed(path, allowlist):
            problems.append(f"{path}: not in allowlist.txt")
            continue
        problems.extend(check_content(path, read_blob(path), blocked_terms))
    return problems


def staged_problems(allowlist, blocked_terms):
    files = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0") if p]
    return check_files(files, lambda p: git("show", f":{p}", binary=True), allowlist, blocked_terms)


def commit_problems(sha, allowlist, blocked_terms):
    problems = []
    email = git("log", "-1", "--format=%ae", sha).strip()
    if not NOREPLY.match(email):
        problems.append(f"{sha[:10]}: author email is not a GitHub noreply address")
    files = [p for p in git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root",
                            "--diff-filter=ACMR", "-z", sha).split("\0") if p]
    problems.extend(f"{sha[:10]} {p}" for p in
                    check_files(files, lambda p: git("show", f"{sha}:{p}", binary=True),
                                allowlist, blocked_terms))
    return problems


def push_commits(stdin_lines):
    commits = []
    for line in stdin_lines:
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if local_sha == ZERO_SHA:
            continue  # branch deletion: nothing to scan
        if remote_sha == ZERO_SHA:
            revs = git("rev-list", local_sha, "--not", "--remotes")
        else:
            revs = git("rev-list", f"{remote_sha}..{local_sha}")
        commits.extend(r for r in revs.split() if r not in commits)
    return commits


def report(problems):
    if not problems:
        return 0
    print("yt-harness repo guard: rejected", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    print("Fix the files above, or add the path to allowlist.txt if it belongs in the shared skeleton.",
          file=sys.stderr)
    return 1


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = repo_root()
    os.chdir(root)
    allowlist = load_allowlist(root)
    blocked_terms = load_blocked_terms()
    mode = argv[1]
    if mode == "pre-commit":
        return report(staged_problems(allowlist, blocked_terms))
    if mode == "pre-push":
        problems = []
        for sha in push_commits(sys.stdin.read().splitlines()):
            problems.extend(commit_problems(sha, allowlist, blocked_terms))
        return report(problems)
    if mode == "scan" and len(argv) == 3:
        problems = []
        for sha in git("rev-list", argv[2]).split():
            problems.extend(commit_problems(sha, allowlist, blocked_terms))
        return report(problems)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
