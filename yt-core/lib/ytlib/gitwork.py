"""Code folders for folderKind repo and worktree: a private clone per task.

The sub-session never gets the human's repository. yt-spawn clones it with
`git clone --shared` into <task folder>/repo: the clone keeps its own refs and new
objects and reads the source's objects through alternates, so the sandbox lets the
session read <source>/.git/objects and nothing else of the source.

  repo      read-only investigation: the clone is readable, only out/ is writable.
  worktree  code changes: the clone is writable, on branch yt/<task id> from the
            source's HEAD. `yt bring <task id>` fetches that branch into the source
            as a branch of the same name; it never merges, checks out, or overwrites.
  vault     (folderKind vault, when the vault is a git repository) the same as worktree:
            notes are committed on yt/<task id> and brought back with `yt bring`.

The session can write anything in the clone, its .git included (config, commondir,
replacement refs, hooks), so yt never runs git on the clone outside the sandbox. Once
the session is stopped, yt exports the task branch as a git bundle by running git under
the task's own sandbox profile. Outside, it fetches that bundle (plain data) into a
quarantine repository it creates itself (<task folder>/branch.git: bare, no user or
system config, replacement refs off, objects borrowed from the source). Every check,
summary, and `yt bring` reads only the quarantine.
"""
import os
import re
import shlex
import shutil
import subprocess

from . import core

CLONE = "repo"
QUARANTINE = "branch.git"
BUNDLE = "branch.bundle"
BRANCH = "yt/{task_id}"
VERSION_LINE = re.compile(rb"version: [0-9][0-9A-Za-z.+-]*\n")
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


# Tool settings yt-vault reads; often git-ignored, so a clone would lack them.
VAULT_SETTINGS = (".obsidian/app.json", ".obsidian/templates.json", ".obsidian/daily-notes.json",
                  "logseq/config.edn", "dendron.yml", "mkdocs.yml")


def vault_problem(path):
    """(why a vault folder cannot be used, or None; True when it is a git repository root).

    A folder inside a repository would be written in place, so it is refused; a git
    vault with uncommitted notes (*.md) is refused because its clone would not see them;
    other changes (an editor's workspace file) do not count.
    """
    r = subprocess.run(["git", *SAFE_GIT, "rev-parse", "--show-toplevel"], cwd=path, capture_output=True,
                       timeout=60, env={**os.environ, **ISOLATED})
    if r.returncode != 0:
        if os.path.lexists(os.path.join(path, ".git")):
            return f"vault {path} has a .git that git cannot read; fix or remove it first", True
        return None, False
    top = os.path.realpath(r.stdout.decode("utf-8", "replace").strip())
    if not os.path.samefile(top, path):
        return (f"vault {path} is inside the git repository {top}; register the repository root as the vault "
                "(the session then works on a private clone)"), True
    problem = source_problem(path)
    if problem:
        return problem, True
    changed = _git("status", "--porcelain", "-z", "--untracked-files=all", cwd=path, raw=True).split(b"\0")
    if any(entry.lower().endswith(b".md") for entry in changed):
        return (f"vault {path} has uncommitted notes; commit them first so the session's clone sees "
                "every note"), True
    return None, True


def _no_links(root, rel):
    """True when no part of root/rel is a symlink (so nothing leads outside root)."""
    parts = rel.split("/")
    return not any(os.path.islink(os.path.join(root, *parts[:i + 1])) for i in range(len(parts)))


def copy_vault_settings(source, clone):
    """Copy the tool settings yt-vault reads into the clone when git did not bring them."""
    for rel in (".obsidian",) + VAULT_SETTINGS:
        src, dst = os.path.join(source, rel), os.path.join(clone, rel)
        if os.path.lexists(dst) or not (_no_links(source, rel) and _no_links(clone, os.path.dirname(rel) or ".")):
            continue
        try:
            if rel == ".obsidian":
                if os.path.isdir(src):
                    os.mkdir(dst)   # the folder alone marks the kind
            elif os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
        except OSError:
            pass   # a setting that cannot be copied only weakens yt-vault's guess


# Git that yt runs itself loads no user or system config and ignores replacement refs.
ISOLATED = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1"}


def _git(*args, cwd=None, check=True, human_config=False, raw=False):
    env = dict(os.environ) if human_config else {**os.environ, **ISOLATED}
    r = subprocess.run(["git", *SAFE_GIT, *args], cwd=cwd, capture_output=True, timeout=300, env=env)
    if check and r.returncode != 0:
        err = (r.stderr or r.stdout).decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {err[:300]}")
    return r.stdout if raw else r.stdout.decode("utf-8", "replace").strip()


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
            **({"repoScope": list(scope)} if scope else {})}


def objects_dir(source):
    return os.path.join(source, ".git", "objects")


def export(entry):
    """Bundle the task branch by running git inside the task's sandbox. Returns the bundle or None.

    None means the branch has no commits on top of its base. The clone's own git config
    can run code here, but only inside the same sandbox the session had.
    """
    from . import launch
    from . import platform as ytplatform
    task = core.task_dir(entry["taskId"])
    tmp = os.path.join(task, "tmp")
    os.makedirs(tmp, exist_ok=True)
    bundle = os.path.join(tmp, BUNDLE)
    dirty = os.path.join(tmp, "branch.dirty")
    for p in (bundle, dirty):
        if os.path.exists(p):
            os.remove(p)
    harness = core.load_harness(entry["harness"])
    policy = core.resolve_policy(harness, task, entry.get("vaultPath"), entry["repoClone"])
    rng = f"{entry['repoBase']}..refs/heads/{entry['repoBranch']}"
    script = (f"git status --porcelain > {shlex.quote(dirty)}; "
              f"if [ -n \"$(git rev-list -n 1 {shlex.quote(rng)})\" ]; then "
              f"git bundle create -q {shlex.quote(bundle)} {shlex.quote(rng)}; fi")
    plat = ytplatform.load()
    argv = plat.sandbox_argv(policy, entry["runtime"], ["/bin/sh", "-c", script], profile_dir=tmp,
                             extra_read=[objects_dir(entry["repoSource"])], tmp_dir=tmp, cwd=entry["repoClone"])
    code, output = _run_contained(argv, entry["repoClone"], launch.session_env(task, tmp))
    if code != 0:
        raise RuntimeError(f"could not export the task branch: {output.strip()[:300]}")
    # tmp/ is the session's: what it leaves there must be a plain file (not a FIFO or a link).
    return bundle if _regular(bundle) else None


EXPORT_TIMEOUT = 300


def _run_contained(argv, cwd, env, timeout=EXPORT_TIMEOUT):
    """Run code the session controls: output goes to a file, not a pipe a child could hold
    open, and on timeout the whole process group is killed. Returns (exit code, output)."""
    import signal
    import tempfile
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        try:
            os.killpg(proc.pid, signal.SIGKILL)   # leftovers of the run, finished or not
        except (ProcessLookupError, PermissionError):
            pass
        if code is None:
            proc.wait()
            return 1, f"timed out after {timeout}s"
        log.seek(0)
        return code, log.read(4096).decode("utf-8", "replace")


def _regular(path):
    import stat
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _count_lines(path, limit=1 << 20):
    """Non-empty lines of a file the session could have replaced; never blocks or follows links."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return 0
    with os.fdopen(fd, "rb") as f:
        import stat
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return 0
        return sum(1 for line in f.read(limit).splitlines() if line.strip())


def quarantine(entry):
    """Fetch the exported branch into a fresh quarantine repository. Returns its path."""
    task = core.task_dir(entry["taskId"])
    q = os.path.join(task, QUARANTINE)
    shutil.rmtree(q, ignore_errors=True)
    _git("init", "--bare", "--quiet", q)
    with open(os.path.join(q, "objects", "info", "alternates"), "w", encoding="utf-8") as f:
        f.write(objects_dir(entry["repoSource"]) + "\n")
    _git("update-ref", f"refs/heads/{entry['repoBranch']}", entry["repoBase"], cwd=q)
    bundle = export(entry)
    if bundle:
        branch = entry["repoBranch"]
        _git("fetch", "--quiet", "--no-tags", "--force", bundle, f"refs/heads/{branch}:refs/heads/{branch}", cwd=q)
    return q


def _version_only(q, base, branch, path):
    """True when the file differs from base only in one `version: x` line (compared as bytes)."""
    old = _git("cat-file", "blob", f"{base}:{path}", cwd=q, raw=True, check=False).splitlines(keepends=True)
    new = _git("cat-file", "blob", f"{branch}:{path}", cwd=q, raw=True, check=False).splitlines(keepends=True)
    if len(old) != len(new) or not old:
        return False
    changed = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
    return len(changed) == 1 and all(VERSION_LINE.fullmatch(x[changed[0]]) for x in (old, new))


REGULAR = ("100644", "100755")


def _changes(q, a, b):
    """[(old mode, new mode, path)] between two commits, renames split into delete and add."""
    raw = _git("diff", "--raw", "-z", "--no-renames", "--no-abbrev", a, b, cwd=q, raw=True).split(b"\0")
    out = []
    for meta, path in zip(raw[0::2], raw[1::2]):
        modes = meta.decode("ascii", "replace").lstrip(":").split()
        if len(modes) >= 2:
            out.append((modes[0], modes[1], path.decode("utf-8", "replace")))
    return out


def scope_problems(entry, q):
    """Changes on the task branch outside its scope (empty when it has no scope).

    Every commit is checked against its parent, not only the branch tip against the
    base: bring fetches the whole history, so content added and removed again on the
    way would still reach the human's repository. Merges and new roots are refused.
    """
    scope = entry.get("repoScope")
    if not scope or not entry.get("repoBranch"):
        return []
    base, branch = entry["repoBase"], f"refs/heads/{entry['repoBranch']}"
    version_only = {s[:-len(":version")] for s in scope if s.endswith(":version")}
    allowed = [s for s in scope if not s.endswith(":version")]
    out = []
    for line in _git("rev-list", "--parents", f"{base}..{branch}", cwd=q).splitlines():
        commit, *parents = line.split()
        if len(parents) != 1:
            out.append(f"{commit[:12]}: merge or root commits are never in scope")
            continue
        for old_mode, new_mode, path in _changes(q, parents[0], commit):
            if path in version_only:
                if old_mode != "100644" or new_mode != "100644" or not _version_only(q, parents[0], commit, path):
                    out.append(f"{path}: only its version line may change")
            elif any(part.startswith(".") for part in path.split("/")):
                out.append(f"{path}: dotfiles (.gitattributes, .gitignore, ...) are never in scope")
            elif not any(path == a or (a.endswith("/") and path.startswith(a)) for a in allowed):
                out.append(f"{path}: outside the task's scope")
            elif new_mode not in REGULAR + ("000000",):
                out.append(f"{path}: symlinks and submodules are never in scope")
    return list(dict.fromkeys(out))


def summary(entry):
    """Commits on the task branch and uncommitted files, for yt collect (from the quarantine)."""
    base, branch = entry["repoBase"], entry.get("repoBranch")
    if not branch:
        return []
    q = quarantine(entry)
    ref = f"refs/heads/{branch}"
    log = _git("log", "--oneline", "--no-decorate", f"{base}..{ref}", cwd=q).splitlines()
    stat = _git("diff", "--stat", base, ref, cwd=q).splitlines()
    out = [f"branch {branch}: {len(log)} commit(s) on top of {base[:12]}"]
    out += [f"  {line}" for line in log[:20]]
    out += [f"  {stat[-1].strip()}"] if stat else []
    dirty = _count_lines(os.path.join(core.task_dir(entry["taskId"]), "tmp", "branch.dirty"))
    if dirty:
        out.append(f"  {dirty} uncommitted change(s) in the clone are not part of the branch")
    out += [f"  out of scope: {p}" for p in scope_problems(entry, q)]
    return out


def bring(entry):
    """Fetch the task branch into the source repository as a new branch. Returns the branch name."""
    branch, source = entry.get("repoBranch"), entry["repoSource"]
    if not branch:
        raise RuntimeError("this task was read-only (folderKind repo); there is nothing to bring")
    q = quarantine(entry)
    outside = scope_problems(entry, q)
    if outside:
        raise RuntimeError("the branch changes files outside the task's scope: " + "; ".join(outside))
    if _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=source, check=False):
        raise RuntimeError(f"{source} already has a branch {branch}; rename or delete it first")
    _git("fetch", "--quiet", "--no-tags", q, f"refs/heads/{branch}:refs/heads/{branch}", cwd=source)
    return branch
