#!/usr/bin/env python3
"""folderKind repo and worktree: the private clone, its summary, tamper checks, yt bring, and
the sandbox around it (the clone is writable, the source repository is not).

Uses throwaway repositories and a throwaway local layer under $HOME; nothing real is touched.
Usage: tests/repo/run.py      exit 0 when every check passes
"""
import os
import shutil
import subprocess
import sys
import tempfile

HOME = os.path.expanduser("~")
os.makedirs(os.path.join(HOME, "yt-work"), exist_ok=True)
ROOT = tempfile.mkdtemp(prefix="yt-repo-test-", dir=os.path.join(HOME, "yt-work"))
os.environ.update(YT_LOCAL=os.path.join(ROOT, "local"), YT_WORK=os.path.join(ROOT, "work"))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "yt-core", "lib"))
from ytlib import core, gitwork, launch  # noqa: E402
from ytlib import platform as ytplatform  # noqa: E402

results = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def make_source():
    src = os.path.join(ROOT, "source")
    os.makedirs(src)
    git("init", "-q", "-b", "main", cwd=src)
    git("config", "user.name", "Test", cwd=src)
    git("config", "user.email", "test@example.invalid", cwd=src)
    with open(os.path.join(src, "app.txt"), "w") as f:
        f.write("one\n")
    git("add", ".", cwd=src)
    git("commit", "-q", "-m", "first", cwd=src)
    return src


def commit_in(clone, text):
    with open(os.path.join(clone, "app.txt"), "a") as f:
        f.write(text)
    git("commit", "-q", "-am", "change", cwd=clone)


def unit(src):
    head = git("rev-parse", "HEAD", cwd=src)
    e = gitwork.prepare("w1", src, writable=True)
    clone = e["repoClone"]
    check("prepare: the clone sits in the task folder", clone == os.path.join(core.task_dir("w1"), "repo"))
    check("prepare: worktree is on branch yt/<task>", git("branch", "--show-current", cwd=clone) == "yt/w1")
    check("prepare: base is the source HEAD", e["repoBase"] == head)
    check("prepare: the clone shares the source's objects",
          os.path.isfile(os.path.join(clone, ".git", "objects", "info", "alternates")))
    check("prepare: no hooks in the clone", os.listdir(os.path.join(clone, ".git", "hooks")) == [])
    check("prepare: the human's identity is carried over", git("config", "user.name", cwd=clone) == "Test")
    commit_in(clone, "two\n")
    lines = gitwork.summary(e)
    check("summary: one commit on top of the base", lines and lines[0].startswith("branch yt/w1: 1 commit(s)"), lines)
    branch = gitwork.bring(e)
    check("bring: the source gets branch yt/w1", git("rev-parse", "yt/w1", cwd=src) == git("rev-parse", "HEAD", cwd=clone))
    check("bring: the source's checkout is untouched",
          git("branch", "--show-current", cwd=src) == "main" and open(os.path.join(src, "app.txt")).read() == "one\n"
          and branch == "yt/w1")
    try:
        gitwork.bring(e)
        check("bring: refuses to overwrite an existing branch", False)
    except RuntimeError:
        check("bring: refuses to overwrite an existing branch", True)

    e2 = gitwork.prepare("w2", src, writable=True)
    with open(os.path.join(e2["repoClone"], ".git", "config"), "a") as f:
        f.write("[core]\n\tfsmonitor = /bin/echo\n")
    check("tamper: a changed clone config is caught", gitwork.tampered(e2) is not None)
    for name, fn in (("summary", gitwork.summary), ("bring", gitwork.bring)):
        try:
            fn(e2)
            check(f"tamper: {name} refuses to run git there", False)
        except RuntimeError:
            check(f"tamper: {name} refuses to run git there", True)
    e3 = gitwork.prepare("w3", src, writable=True)
    with open(os.path.join(e3["repoClone"], ".git", "hooks", "post-checkout"), "w") as f:
        f.write("#!/bin/sh\n")
    check("tamper: an added hook is caught", gitwork.tampered(e3) is not None)

    r = gitwork.prepare("r1", src, writable=False)
    check("repo kind: no task branch", r["repoBranch"] is None and gitwork.summary(r) == [])
    try:
        gitwork.bring(r)
        check("repo kind: nothing to bring", False)
    except RuntimeError:
        check("repo kind: nothing to bring", True)
    try:
        gitwork.prepare("w1", src, writable=True)
        check("prepare: refuses an existing clone", False)
    except RuntimeError:
        check("prepare: refuses an existing clone", True)

    plain = os.path.join(ROOT, "plain")
    os.makedirs(plain)
    check("source: a folder without .git is refused", gitwork.source_problem(plain) is not None)
    check("source: outside $HOME is refused", gitwork.source_problem("/tmp") is not None)
    check("source: a task folder is refused", gitwork.source_problem(core.task_dir("w1")) is not None)
    check("source: the test repository is fine", gitwork.source_problem(src) is None)


def scoped(src):
    os.makedirs(os.path.join(src, "h", "skills", "s"), exist_ok=True)
    with open(os.path.join(src, "h", "harness.yaml"), "w") as f:
        f.write("id: h\nversion: 0.1.0\nsandbox: x\n")
    with open(os.path.join(src, "h", "skills", "s", "SKILL.md"), "w") as f:
        f.write("step one\n")
    git("add", ".", cwd=src)
    git("commit", "-q", "-m", "harness", cwd=src)
    scope = ["h/skills/", "h/harness.yaml:version"]

    def attempt(name, edits):
        e = gitwork.prepare(f"sc-{name}", src, writable=True, scope=scope)
        for rel, old, new in edits:
            path = os.path.join(e["repoClone"], rel)
            text = open(path).read() if os.path.exists(path) else ""
            with open(path, "w") as f:
                f.write(text.replace(old, new) if old else text + new)
        git("add", "-A", cwd=e["repoClone"])
        git("commit", "-q", "-m", name, cwd=e["repoClone"])
        return e

    ok = attempt("ok", [("h/skills/s/SKILL.md", "step one", "step one, checked"),
                        ("h/harness.yaml", "version: 0.1.0", "version: 0.1.1")])
    check("scope: a skill change and a version bump are in scope", gitwork.scope_problems(ok) == [],
          gitwork.scope_problems(ok))
    bad = attempt("yaml", [("h/harness.yaml", "sandbox: x", "sandbox: y")])
    check("scope: another harness.yaml line is refused", any("version line" in p for p in gitwork.scope_problems(bad)))
    other = attempt("other", [("app.txt", None, "more\n")])
    check("scope: a file outside the scope is refused", any("app.txt" in p for p in gitwork.scope_problems(other)))
    check("scope: collect's summary names it", any("out of scope" in line for line in gitwork.summary(other)))
    try:
        gitwork.bring(other)
        check("scope: bring refuses an out-of-scope branch", False)
    except RuntimeError:
        check("scope: bring refuses an out-of-scope branch", True)
    check("scope: an in-scope branch can be brought", gitwork.bring(ok) == "yt/sc-ok")


def sandboxed(src):
    plat = ytplatform.load()
    if plat.sandbox_problem():
        print(f"skip sandbox cases: {plat.sandbox_problem()}")
        return
    e = gitwork.prepare("s1", src, writable=True)
    task = core.task_dir("s1")
    for d in ("out", "tmp"):
        os.makedirs(os.path.join(task, d), exist_ok=True)
    harness = core.load_harness("yt-code")
    policy = core.resolve_policy(harness, task, repo=e["repoClone"])
    extra = [core.CORE, core.harness_dir("yt-code"), os.path.realpath(sys.base_prefix), gitwork.objects_dir(src)]

    def run(command):
        argv = plat.sandbox_argv(policy, "claude", ["/bin/sh", "-c", command], profile_dir=task, extra_read=extra,
                                 tmp_dir=os.path.join(task, "tmp"), cwd=os.path.join(task, "out"))
        env = launch.session_env(task, os.path.join(task, "tmp"))
        return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=60)

    clone = e["repoClone"]
    r = run(f"cd {clone} && echo three >> app.txt && git commit -qam sandboxed && git log --oneline -1")
    check("sandbox: the session can commit in the clone", r.returncode == 0 and "sandboxed" in r.stdout, r.stderr[-300:])
    check("sandbox: git prints no warnings about hidden user config", "warning" not in r.stderr.lower(), r.stderr[-300:])
    out = os.path.join(task, "out")
    r = run(f"zsh -c 'cat > {out}/heredoc.txt <<EOF\nhello\nEOF'")
    check("sandbox: a zsh here-document can be written (TMPPREFIX)",
          r.returncode == 0 and open(os.path.join(out, "heredoc.txt")).read() == "hello\n", r.stderr[-200:])
    # On Linux the source's folders above .git/objects exist only in the session's throwaway
    # tmpfs view, so a write there can succeed without reaching the disk: judge the real files.
    run(f"echo x >> {src}/app.txt")
    check("sandbox: the source's files cannot be written", open(os.path.join(src, "app.txt")).read() == "one\n")
    r = run(f"cat {src}/app.txt")
    check("sandbox: the source's files cannot be read", "one" not in r.stdout)
    run(f"mkdir -p {src}/.git/hooks && touch {src}/.git/hooks/pre-commit")
    check("sandbox: the source's hooks cannot be written", not os.path.exists(os.path.join(src, ".git", "hooks", "pre-commit")))
    r = run(f"touch {src}/.git/objects/zz")
    check("sandbox: the source's objects are read-only", r.returncode != 0)
    check("sandbox: the source is unchanged", open(os.path.join(src, "app.txt")).read() == "one\n"
          and not os.path.exists(os.path.join(src, ".git", "hooks", "pre-commit")))
    check("sandbox: the clone stays untampered", gitwork.tampered(e) is None)


def main():
    try:
        src = make_source()
        unit(src)
        sandboxed(src)
        scoped(src)
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    print(f"passed={results['pass']} failed={results['fail']}")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
