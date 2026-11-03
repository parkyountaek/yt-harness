#!/usr/bin/env python3
"""Repository guard for yt-harness.

Rejects commits and pushes that contain paths outside allowlist.txt or
content that must never reach GitHub (secrets, personal absolute paths,
locally configured blocked terms). Pre-commit also rejects runtime files
that are out of date with their neutral sources (yt-build --check).

Usage:
  repo_guard.py pre-commit          check staged files
  repo_guard.py pre-push <remote>   check commits about to be pushed (stdin from git)
  repo_guard.py scan <rev-range>    check every commit in a range (e.g. for the public switch)

Exit codes: 0 clean, 1 violations found, 2 usage error.
Standard library only.
"""
import os
import re
import shutil
import subprocess
import sys

ZERO_SHA = "0" * 40
NOREPLY = re.compile(r"^[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com$")

# Sensitive file names: rejected even inside an allowed directory.
# Matched against the last path component. Templates such as ".env.example" are allowed.
SENSITIVE_NAMES = re.compile(
    r"^(?:"
    r"\.env(?:\.(?!example$|sample$|template$)[^/]+)?"   # .env, .env.local, .env.production
    r"|\.envrc|\.netrc|_netrc|\.npmrc|\.pypirc|\.pgpass|\.git-credentials"
    r"|id_(?:rsa|dsa|ecdsa|ed25519)(?:_sk)?"              # SSH private keys
    r"|credentials(?:\.json|\.csv)?|service[-_]account.*\.json|client_secret.*\.json"
    r"|.*\.(?:pem|key|p12|pfx|jks|keystore|ppk|kdbx|tfstate|tfvars)"
    r"|.*\.tfstate\.backup|terraform\.tfvars\.json|kubeconfig|\.kube"
    r")$",
    re.IGNORECASE,
)

# Built-in content patterns. Each is assembled so this file never matches itself.
PATTERNS = [
    # Version-control hosts and package registries
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("gitlab-token", re.compile(r"\bgl(?:pat|dt|rt|ptt|cbt)-[A-Za-z0-9_-]{20,}\b")),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("pypi-token", re.compile(r"\bpypi-AgE[A-Za-z0-9_-]{50,}")),
    # Cloud providers
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b")),
    ("aws-secret-key", re.compile(r"(?i)aws_?secret_?access_?key\s*[:=]\s*['\"]?[A-Za-z0-9/+]{40}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("gcp-service-account", re.compile(r"\"type\"\s*:\s*\"service_account\"")),
    ("azure-storage-key", re.compile(r"(?i)AccountKey=[A-Za-z0-9+/=]{40,}")),
    # AI and SaaS APIs
    ("api-secret-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("slack-webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}")),
    ("discord-webhook", re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{20,}")),
    ("telegram-bot-token", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b")),
    ("stripe-key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}\b")),
    ("sendgrid-key", re.compile(r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b")),
    ("twilio-key", re.compile(r"\bSK[0-9a-f]{32}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    # Generic shapes
    ("private-key", re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY( BLOCK)?-----")),
    ("url-with-password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@<>]+:[^\s/@<>]{3,}@[^\s/]+")),
    ("secret-assignment", re.compile(
        r"(?i)\b[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY)[A-Z0-9_]*"
        r"\s*[:=]\s*['\"]?(?!<|\$\{|\$\(|\{\{)[A-Za-z0-9/+_=.-]{16,}")),
    ("personal-path", re.compile(r"/(?:Users|home)/(?!<|Shared\b)[A-Za-z0-9._-]+(?:/|\b)")),
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


LOCAL = os.path.expanduser(os.environ.get("YT_LOCAL", "~/yt-local"))


def load_blocked_terms():
    """Company-specific terms live outside the repo, in the local layer."""
    path = os.path.expanduser(os.environ.get("YT_BLOCKED_TERMS", os.path.join(LOCAL, "blocked-terms.txt")))
    if not os.path.exists(path):
        return []
    terms = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line.lower())
    return terms


def load_blocked_paths():
    """Machine-local paths that must never be committed, even if inside an allowed directory."""
    path = os.path.expanduser(os.environ.get("YT_BLOCKED_PATHS", os.path.join(LOCAL, "blocked-paths.txt")))
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


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
    blocked_paths = load_blocked_paths()
    for path in files:
        if path_allowed(path, blocked_paths):
            problems.append(f"{path}: blocked by the local blocked-paths list (never committed)")
            continue
        if any(SENSITIVE_NAMES.match(part) for part in path.split("/")):
            problems.append(f"{path}: sensitive file name (never committed)")
            continue
        if not path_allowed(path, allowlist):
            problems.append(f"{path}: not in allowlist.txt")
            continue
        problems.extend(check_content(path, read_blob(path), blocked_terms))
    return problems


def staged_problems(allowlist, blocked_terms):
    files = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z").split("\0") if p]
    return check_files(files, lambda p: git("show", f":{p}", binary=True), allowlist, blocked_terms)


def commit_problems(sha, allowlist, blocked_terms):
    problems = []
    author, committer = git("log", "-1", "--format=%ae%n%ce", sha).split("\n")[:2]
    for role, email in (("author", author), ("committer", committer)):
        if not NOREPLY.match(email.strip()):
            problems.append(f"{sha[:10]}: {role} email is not a GitHub noreply address")
    # -m compares a merge with each parent, so files introduced while resolving a merge are seen.
    files = sorted({p for p in git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "-m",
                                   "--diff-filter=ACMRT", "-z", sha).split("\0") if p})
    problems.extend(f"{sha[:10]} {p}" for p in
                    check_files(files, lambda p: git("show", f"{sha}:{p}", binary=True),
                                allowlist, blocked_terms))
    return problems


def gitleaks(log_opts=None):
    """Run gitleaks as the primary secret scanner. Our own PATTERNS are the fallback.

    Returns a list of problems. A missing gitleaks is a warning, not a rejection;
    yt-setup installs it and yt-doctor reports when it is absent.
    """
    if os.environ.get("YT_GUARD_NO_GITLEAKS") == "1":
        return []
    exe = shutil.which("gitleaks")
    if not exe:
        print("yt-harness repo guard: warning: gitleaks not installed, using built-in patterns only."
              " Run yt-core/bin/yt-setup.", file=sys.stderr)
        return []
    cmd = [exe, "git", "--no-banner", "--no-color", "--redact", "--verbose", "--exit-code", "1"]
    cmd += ["--pre-commit", "--staged"] if log_opts is None else [f"--log-opts={log_opts}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return []
    keep = ("RuleID:", "File:", "Line:", "Commit:", "leaks found", "ERR", "error")
    detail = [line.strip() for line in (result.stdout + result.stderr).splitlines()
              if any(k in line for k in keep)]
    return ["gitleaks: " + line for line in detail][:40] or ["gitleaks: leak found"]


def push_ranges(stdin_lines, remote):
    ranges = []
    for line in stdin_lines:
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO_SHA:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        ranges.append(f"{local_sha} --not --remotes={remote}" if remote_sha == ZERO_SHA
                      else f"{remote_sha}..{local_sha}")
    return ranges


def push_commits(stdin_lines, remote):
    commits = []
    for line in stdin_lines:
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if local_sha == ZERO_SHA:
            continue  # branch deletion: nothing to scan
        if remote_sha == ZERO_SHA:
            revs = git("rev-list", local_sha, "--not", f"--remotes={remote}")
        else:
            revs = git("rev-list", f"{remote_sha}..{local_sha}")
        commits.extend(r for r in revs.split() if r not in commits)
    return commits


def generated_problems(root):
    """Runtime-specific files must match what yt-build generates from the neutral sources."""
    build = os.path.join(root, "yt-core", "bin", "yt-build")
    if not os.path.isfile(build):
        return []
    r = subprocess.run([sys.executable, build, "--check"], capture_output=True, text=True)
    return [] if r.returncode == 0 else [(r.stderr or r.stdout).strip()]


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
        return report(staged_problems(allowlist, blocked_terms) + generated_problems(root) + gitleaks())
    if mode == "pre-push":
        remote = argv[2] if len(argv) > 2 else "origin"
        lines = sys.stdin.read().splitlines()
        problems = []
        for sha in push_commits(lines, remote):
            problems.extend(commit_problems(sha, allowlist, blocked_terms))
        for rev_range in push_ranges(lines, remote):
            problems.extend(gitleaks(rev_range))
        return report(problems)
    if mode == "scan" and len(argv) == 3:
        problems = []
        for sha in git("rev-list", argv[2]).split():
            problems.extend(commit_problems(sha, allowlist, blocked_terms))
        return report(problems + gitleaks(argv[2]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
