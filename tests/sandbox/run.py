#!/usr/bin/env python3
"""Deterministic tests for the shared sandbox profile (no model involved).

Runs shell commands inside the profile generated for each runtime and checks that
each is allowed or denied. Commands never change file contents: writes use
`: >> file` (open for append, write nothing) on files that already exist, or create
files in throwaway places that are removed afterwards.

Usage: tests/sandbox/run.py      exit 0 when every case passes
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "yt-core", "lib"))
from ytlib import platform as ytplatform  # noqa: E402

HOME = os.path.expanduser("~")
SHARED = "/Users/Shared"


def main():
    plat = ytplatform.load()
    if plat.OS_ID != "macos":
        print(f"skip: sandbox backend for {plat.OS_ID} is not implemented")
        return 0
    work = os.path.join(HOME, "yt-work", f"sandbox-test-{os.getpid()}")
    task_tmp = os.path.join(work, "tmp")
    for d in ("in", "out", "tmp"):
        os.makedirs(os.path.join(work, d), exist_ok=True)
    with open(os.path.join(work, "in", "input.txt"), "w") as f:
        f.write("input\n")
    outside = tempfile.mkdtemp(prefix="yt-sandbox-outside-", dir=HOME)
    with open(os.path.join(outside, "secret.txt"), "w") as f:
        f.write("secret\n")
    # Probes outside $HOME that the session must not read.
    probes = {"/Users/Shared": os.path.join(SHARED, f"yt-sandbox-read-{os.getpid()}"),
              "coordinator temp dir": os.path.join(tempfile.gettempdir(), f"yt-sandbox-read-{os.getpid()}"),
              "other Claude temp dir": f"/private/tmp/claude-{os.getuid()}/yt-sandbox-read-{os.getpid()}"}
    for path in probes.values():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("private\n")
    host = f"yt-sandbox-host-{os.getpid()}"
    subprocess.run(["tmux", "new-session", "-d", "-s", host, "sleep 120"], check=False)
    marker = os.path.join(SHARED, f"yt-sandbox-escape-{os.getpid()}")
    own_claude = plat.claude_project_dir(os.path.join(work, "out"))
    import re
    own_tmp = f"/private/tmp/claude-{os.getuid()}/" + re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.path.join(work, "out")))

    # Peer messaging: a listening socket where other Claude sessions keep theirs, and one
    # in the task's own tmp dir (where the sub-session keeps its own).
    import socket
    peer_sock = f"/private/tmp/cc-socks/yt-sandbox-peer-{os.getpid()}.sock"
    own_sock = os.path.join(task_tmp, "cc-socks", "own.sock")
    listeners = []
    for path in (peer_sock, own_sock):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(path)
        srv.listen(64)
        listeners.append(srv)
    connect = ("cd {out} && TMPDIR={tmp}/ /usr/bin/python3 -I -c "
               "'import socket,sys; socket.socket(socket.AF_UNIX).connect(sys.argv[1])' ").format(
        out=os.path.join(work, "out"), tmp=task_tmp)

    common = [
        ("deny", "connect to another session's messaging socket", connect + peer_sock),
        ("allow", "connect to own messaging socket (task tmp)", connect + own_sock),
        ("deny", "list the session registry ~/.claude/sessions", f"ls {HOME}/.claude/sessions"),
        ("allow", "system python3 runs without xcrun cache errors",
         f"cd {work}/out && /usr/bin/python3 -I -c 'print(1)' 2>&1 | (! grep -q xcrun_db)"),
        # (expect, name, shell command)
        ("allow", "read input", f"cat {work}/in/input.txt"),
        ("allow", "write out/", f"echo ok > {work}/out/result.md"),
        ("allow", "write task tmp", f"echo ok > {task_tmp}/x"),
        ("allow", "write /dev/null", "echo ok > /dev/null"),
        ("deny", "read outside task", f"cat {outside}/secret.txt"),
        ("deny", "list ~/.ssh", "ls ~/.ssh"),
        *[("deny", f"read {name}", f"cat {path}") for name, path in probes.items()],
        ("deny", "list /Volumes", "ls /Volumes"),
        ("deny", "write in/", f": >> {work}/in/input.txt"),
        ("deny", "write outside $HOME (/Users/Shared)", f"touch {marker}"),
        ("deny", "write /private/tmp", f"touch /private/tmp/yt-sandbox-escape-{os.getpid()}"),
        ("deny", "tmux server runs a command", f"tmux new-window -d -t ={host}: 'touch {marker}'"),
        # exec-denied: the program must not even start (judged by the kernel's EPERM message,
        # because some of these exit non-zero on their own).
        ("exec-denied", "osascript", "osascript -e 'return 1'"),
        ("exec-denied", "open (LaunchServices)", "/usr/bin/open -h"),
        ("exec-denied", "launchctl", "launchctl list"),
        ("exec-denied", "crontab", "crontab -l"),
        ("exec-denied", "ssh", "ssh -V"),
    ]
    per_runtime = {
        "claude": [
            ("deny", "write ~/.claude/settings.json", f": >> {HOME}/.claude/settings.json"),
            ("deny", "write ~/.claude/CLAUDE.md", f": >> {HOME}/.claude/CLAUDE.md"),
            ("deny", "create ~/.claude/hooks/x", f"mkdir -p {HOME}/.claude/hooks && : > {HOME}/.claude/hooks/x"),
            ("deny", "read other transcripts", f"ls {HOME}/.claude/projects"),
            ("deny", "read ~/.claude/history.jsonl", f"cat {HOME}/.claude/history.jsonl"),
            ("allow", "write own transcript dir", f"mkdir -p {own_claude} && : > {own_claude}/probe"),
            ("allow", "write ~/.claude.json", f": >> {HOME}/.claude.json"),
            ("allow", "write own Claude temp dir", f"mkdir -p {own_tmp} && : > {own_tmp}/probe"),
            ("deny", "write another session's Claude temp dir", f"mkdir -p /private/tmp/claude-{os.getuid()}/yt-other-probe"),
        ],
        "codex": [
            ("deny", "write ~/.codex/config.toml", f": >> {HOME}/.codex/config.toml"),
            ("deny", "write ~/.codex/hooks.json", f": >> {HOME}/.codex/hooks.json"),
            ("deny", "write ~/.codex/AGENTS.md", f": >> {HOME}/.codex/AGENTS.md"),
            ("deny", "write ~/.codex/plugins", f": > {HOME}/.codex/plugins/yt-probe"),
            ("deny", "read ~/.codex/history.jsonl", f"cat {HOME}/.codex/history.jsonl"),
            ("allow", "write ~/.codex/sessions", f"mkdir -p {HOME}/.codex/sessions && : > {HOME}/.codex/sessions/.yt-probe"),
        ],
    }

    passed = failed = 0
    try:
        for runtime, extra in per_runtime.items():
            policy = {"read": [work], "write": [f"{work}/out/"]}
            for expect, name, command in common + extra:
                argv = plat.sandbox_argv(policy, runtime, ["/bin/sh", "-c", command], profile_dir=work,
                                         tmp_dir=task_tmp, cwd=os.path.join(work, "out"))
                env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
                r = subprocess.run(argv, capture_output=True, text=True, env=env)
                got = "allow" if r.returncode == 0 else "deny"
                if expect == "exec-denied":
                    got = "exec-denied" if "Operation not permitted" in r.stderr else f"ran (rc={r.returncode})"
                if name.startswith("tmux"):
                    subprocess.run(["sleep", "1"])
                    got = "allow" if os.path.exists(marker) else "deny"
                ok = got == expect
                passed += ok
                failed += not ok
                print(f"{'PASS' if ok else 'FAIL'} [{runtime}] {name}" + ("" if ok else f" (want {expect}, got {got})"))
                if os.path.exists(marker):
                    os.remove(marker)
    finally:
        for srv in listeners:
            srv.close()
        if os.path.exists(peer_sock):
            os.remove(peer_sock)
        subprocess.run(["tmux", "kill-session", "-t", f"={host}"], capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)
        shutil.rmtree(own_claude, ignore_errors=True)
        shutil.rmtree(own_tmp, ignore_errors=True)
        shutil.rmtree(f"/private/tmp/claude-{os.getuid()}/yt-other-probe", ignore_errors=True)
        for p in (*probes.values(), marker, f"/private/tmp/yt-sandbox-escape-{os.getpid()}", f"{HOME}/.codex/sessions/.yt-probe",
                  f"{HOME}/.codex/plugins/yt-probe"):
            if os.path.exists(p):
                os.remove(p)
        hooks_probe = f"{HOME}/.claude/hooks/x"
        if os.path.exists(hooks_probe):
            os.remove(hooks_probe)
    print(f"passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
