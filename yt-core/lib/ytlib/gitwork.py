"""Code folders for folderKind repo and worktree: a private clone per task.

The sub-session never gets the human's repository. yt-spawn clones it with
`git clone --shared` into <task folder>/repo: the clone keeps its own refs and new
objects and reads the source's objects through alternates, so the sandbox lets the
session read <source>/.git/objects and nothing else of the source.

  repo      read-only investigation: the clone is readable, only out/ is writable.
  worktree  code changes: the clone is writable, on branch yt/<task id> from the
            source's HEAD. `yt bring <task id>` fetches that branch into the source
            as a branch of the same name; it never merges, checks out, or overwrites.

Every git command run on the clone outside the sandbox reads the clone's own
config, which the session could have changed (core.fsmonitor, diff drivers, hook
paths). So the clone's config, hooks, and info/attributes are fingerprinted at
spawn, and yt refuses to run git there when the fingerprint changed.
"""
import hashlib
import os
import subprocess

from . import core

CLONE = "repo"
BRANCH = "yt/{task_id}"
SAFE_GIT = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]


SELF = "yt-harness"


def repos():
    """Named source repositories (~/yt-local/config.json "repos"), plus this checkout as yt-harness."""
    named = {k: os.path.realpath(os.path.expanduser(v))
             for k, v in ((core.read_json(core.CONFIG, {}) or {}).get("repos") or {}).items()}
    return {SELF: os.path.realpath(core.REPO), **named}


def source_problem(path):
    """Why a folder cannot be a source repository, or None."""
    if not os.path.isdir(os.path.join(path, ".git")):
        return f"{path} is not a git repository with a .git folder (worktrees and bare repos are not supported)"
    if not path.startswith(core.HOME + os.sep):
        return f"{path} must be inside $HOME"
    work = os.path.realpath(core.WORK)
    if path == work or path.startswith(work + os.sep):
        return f"{path} is inside the task folders"
    return None


# Git that yt runs on a clone loads no user or system config either: a .gitattributes the
# session planted could otherwise call drivers the human configured (lfs, textconv, ...).
ISOLATED = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def _git(*args, cwd=None, check=True, human_config=False):
    env = dict(os.environ) if human_config else {**os.environ, **ISOLATED}
    r = subprocess.run(["git", *SAFE_GIT, *args], cwd=cwd, capture_output=True, text=True, timeout=300, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def fingerprint(clone):
    """Hash of what makes git run code or change behaviour in the clone."""
    h = hashlib.sha256()
    gitdir = os.path.join(clone, ".git")
    for rel in ("config", os.path.join("info", "attributes")):
        path = os.path.join(gitdir, rel)
        h.update(rel.encode() + b"\0")
        if os.path.isfile(path):
            with open(path, "rb") as f:
                h.update(f.read())
        h.update(b"\0")
    hooks = os.path.join(gitdir, "hooks")
    for name in sorted(os.listdir(hooks)) if os.path.isdir(hooks) else []:
        h.update(b"hook:" + name.encode() + b"\0")
    return h.hexdigest()


def prepare(task_id, source, writable, scope=None):
    """Clone source into the task folder; return the session-list fields for it.

    scope: paths the task branch may change (a trailing / means a folder). A file
    named in scope as "<path>:version" may change only its `version:` line.
    """
    clone = os.path.join(core.task_dir(task_id), CLONE)
    if os.path.exists(clone):
        raise RuntimeError(f"{clone} exists; move or delete it first")
    os.makedirs(os.path.dirname(clone), exist_ok=True)
    _git("clone", "--shared", "--quiet", source, clone)
    hooks = os.path.join(clone, ".git", "hooks")
    for name in os.listdir(hooks) if os.path.isdir(hooks) else []:
        os.remove(os.path.join(hooks, name))
    # The sandbox hides ~/.config/git: point the per-user ignore and attributes files away.
    _git("config", "core.excludesFile", os.devnull, cwd=clone)
    _git("config", "core.attributesFile", os.devnull, cwd=clone)
    # Commits in the sandbox cannot read ~/.gitconfig: carry the human's identity over.
    for key in ("user.name", "user.email"):
        value = _git("config", "--get", key, cwd=source, check=False, human_config=True)
        if value:
            _git("config", key, value, cwd=clone)
    base = _git("rev-parse", "HEAD", cwd=clone)
    branch = None
    if writable:
        branch = BRANCH.format(task_id=task_id)
        _git("switch", "--quiet", "-c", branch, cwd=clone)
    return {"repoSource": source, "repoClone": clone, "repoBase": base, "repoBranch": branch,
            "repoFingerprint": fingerprint(clone), **({"repoScope": list(scope)} if scope else {})}


def objects_dir(source):
    return os.path.join(source, ".git", "objects")


def tampered(entry):
    """Why yt must not run git in this task's clone, or None."""
    clone = entry.get("repoClone")
    if not clone or not os.path.isdir(os.path.join(clone, ".git")):
        return "the task has no clone"
    if fingerprint(clone) != entry.get("repoFingerprint"):
        return ("the clone's git config, hooks, or info/attributes changed during the task; "
                f"inspect {clone} by hand before using it")
    return None


def scope_problems(entry):
    """Changes on the task branch outside its scope (empty when it has no scope)."""
    scope = entry.get("repoScope")
    if not scope or not entry.get("repoBranch"):
        return []
    clone, base, branch = entry["repoClone"], entry["repoBase"], entry["repoBranch"]
    version_only = {s[:-len(":version")] for s in scope if s.endswith(":version")}
    allowed = [s for s in scope if not s.endswith(":version")]
    out = []
    for path in _git("diff", "--name-only", "--no-renames", f"{base}..{branch}", cwd=clone).splitlines():
        if path in version_only:
            diff = _git("diff", "-U0", f"{base}..{branch}", "--", path, cwd=clone).splitlines()
            changed = [d for d in diff if d[:1] in "+-" and not d.startswith(("+++", "---"))]
            if any(not d[1:].startswith("version:") for d in changed):
                out.append(f"{path}: only its version line may change")
        elif any(part.startswith(".") for part in path.split("/")):
            out.append(f"{path}: dotfiles (.gitattributes, .gitignore, ...) are never in scope")
        elif not any(path == a or (a.endswith("/") and path.startswith(a)) for a in allowed):
            out.append(f"{path}: outside the task's scope")
    return out


def summary(entry):
    """Commits on the task branch and uncommitted files, for yt collect."""
    problem = tampered(entry)
    if problem:
        raise RuntimeError(problem)
    clone, base, branch = entry["repoClone"], entry["repoBase"], entry.get("repoBranch")
    if not branch:
        return []
    log = _git("log", "--oneline", f"{base}..{branch}", cwd=clone).splitlines()
    stat = _git("diff", "--stat", f"{base}..{branch}", cwd=clone).splitlines()
    dirty = [line for line in _git("status", "--porcelain", cwd=clone).splitlines() if line.strip()]
    out = [f"branch {branch}: {len(log)} commit(s) on top of {base[:12]}"]
    out += [f"  {line}" for line in log[:20]]
    out += [f"  {stat[-1].strip()}"] if stat else []
    if dirty:
        out.append(f"  {len(dirty)} uncommitted change(s) in the clone are not part of the branch")
    out += [f"  out of scope: {p}" for p in scope_problems(entry)]
    return out


def bring(entry):
    """Fetch the task branch into the source repository as a new branch. Returns the branch name."""
    problem = tampered(entry)
    if problem:
        raise RuntimeError(problem)
    branch, source = entry.get("repoBranch"), entry["repoSource"]
    if not branch:
        raise RuntimeError("this task was read-only (folderKind repo); there is nothing to bring")
    outside = scope_problems(entry)
    if outside:
        raise RuntimeError("the branch changes files outside the task's scope: " + "; ".join(outside))
    if _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=source, check=False):
        raise RuntimeError(f"{source} already has a branch {branch}; rename or delete it first")
    _git("fetch", "--quiet", "--no-tags", entry["repoClone"], f"refs/heads/{branch}:refs/heads/{branch}", cwd=source)
    return branch
