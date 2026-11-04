#!/usr/bin/env python3
"""Linux (bubblewrap) sandbox cases, the counterpart of the macOS cases in run.py.

Run on Linux; tests/sandbox/run.py calls it there. Verdicts:
  allow      the command succeeds
  deny       the command fails
  contained  the command may succeed, but nothing it wrote is visible outside
  hidden     the command's output does not contain the probe marker
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "yt-core", "lib"))
from ytlib import platform as ytplatform  # noqa: E402

HOME = os.path.expanduser("~")
MARK = "YT-LINUX-PROBE-7c1"


def main():
    plat = ytplatform.load()
    work = os.path.join(HOME, "yt-work", f"sandbox-test-{os.getpid()}")
    for d in ("in", "out", "tmp"):
        os.makedirs(os.path.join(work, d), exist_ok=True)
    with open(os.path.join(work, "in", "input.txt"), "w") as f:
        f.write("input\n")
    outside = tempfile.mkdtemp(prefix="yt-outside-", dir=HOME)
    files = {os.path.join(outside, "secret.txt"): MARK, os.path.join(HOME, ".ssh", "id_test"): MARK,
             os.path.join(HOME, ".claude", "projects", "-other", "t.jsonl"): MARK,
             os.path.join(HOME, ".claude", "history.jsonl"): MARK, os.path.join(HOME, ".claude", "sessions", "1.json"): MARK,
             os.path.join(HOME, ".codex", "history.jsonl"): MARK, os.path.join(HOME, ".claude", "settings.json"): "{}",
             os.path.join(HOME, ".codex", "config.toml"): "", os.path.join("/tmp", "yt-other-session", "x"): MARK}
    for path, text in files.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text + "\n")
    listeners = []
    # Local services: one under /run (system daemons), one under $HOME (e.g. Docker Desktop's docker.sock).
    sockets = {"service": "/run/yt/service.sock", "home-service": os.path.join(outside, "svc.sock"),
               "peer": "/tmp/cc-socks/1.sock",
               "own": os.path.join(work, "tmp", "cc-socks", "own.sock")}
    for path in sockets.values():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            os.remove(path)
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        s.listen(64)
        listeners.append(s)
    sleeper = subprocess.Popen(["sleep", "60"])
    connect = "python3 -I -c 'import socket,sys; socket.socket(socket.AF_UNIX).connect(sys.argv[1])' "
    escape_marker = os.path.join(HOME, f"yt-escape-{os.getpid()}")
    common = [
        ("allow", "read input", f"cat {work}/in/input.txt"),
        ("allow", "write out/", f"echo ok > {work}/out/result.md"),
        ("allow", "write task tmp", f"echo ok > {work}/tmp/x"),
        ("allow", "write /dev/null", "echo ok > /dev/null"),
        ("deny", "write in/", f"echo x >> {work}/in/input.txt"),
        ("deny", "read outside task", f"cat {outside}/secret.txt"),
        ("deny", "read ~/.ssh", f"cat {HOME}/.ssh/id_test"),
        ("hidden", "other sessions' temp files", "cat /tmp/yt-other-session/x 2>&1; ls -R /tmp 2>&1"),
        ("contained", "write outside the task folder", f"touch {escape_marker}"),
        ("deny", "connect to a local service socket (/run)", connect + sockets["service"]),
        ("deny", "connect to a service socket under $HOME", connect + sockets["home-service"]),
        ("deny", "connect to another session's messaging socket", connect + sockets["peer"]),
        ("allow", "connect to own messaging socket (task tmp)", connect + sockets["own"]),
        ("deny", "see a process outside the sandbox", f"kill -0 {sleeper.pid}"),
        ("deny", "ssh", "ssh -V"),
        ("deny", "tmux", "tmux -V"),
        ("allow", "DNS lookup", "getent hosts example.com"),
    ]
    per_runtime = {
        "claude": [
            ("deny", "write ~/.claude/settings.json", f"echo x >> {HOME}/.claude/settings.json"),
            ("hidden", "read other transcripts", f"cat {HOME}/.claude/projects/-other/t.jsonl 2>&1"),
            ("hidden", "read ~/.claude/history.jsonl", f"cat {HOME}/.claude/history.jsonl 2>&1"),
            ("hidden", "read the session registry", f"cat {HOME}/.claude/sessions/1.json 2>&1"),
            ("allow", "write own transcript dir", f"touch {plat.claude_project_dir(os.path.join(work, 'out'))}/probe"),
            ("allow", "write ~/.claude.json", f"touch {HOME}/.claude.json"),
        ],
        "codex": [
            ("deny", "write ~/.codex/config.toml", f"echo x >> {HOME}/.codex/config.toml"),
            ("hidden", "read ~/.codex/history.jsonl", f"cat {HOME}/.codex/history.jsonl 2>&1"),
            ("allow", "write ~/.codex/sessions", f"mkdir -p {HOME}/.codex/sessions && touch {HOME}/.codex/sessions/p"),
        ],
    }
    passed = failed = 0
    try:
        for runtime, extra in per_runtime.items():
            policy = {"read": [work], "write": [f"{work}/out/"]}
            for expect, name, command in common + extra:
                argv = plat.sandbox_argv(policy, runtime, ["/bin/sh", "-c", command], profile_dir=work,
                                         extra_read=[ROOT], tmp_dir=os.path.join(work, "tmp"),
                                         cwd=os.path.join(work, "out"))
                r = subprocess.run(argv, capture_output=True, text=True)
                if expect == "contained":
                    got = "contained" if not os.path.exists(escape_marker) else "escaped"
                elif expect == "hidden":
                    got = "hidden" if MARK not in r.stdout + r.stderr else "visible"
                else:
                    got = "allow" if r.returncode == 0 else "deny"
                ok = got == expect
                passed += ok
                failed += not ok
                print(f"{'PASS' if ok else 'FAIL'} [{runtime}] {name}" + ("" if ok else
                      f" (want {expect}, got {got}; {(r.stderr or r.stdout).strip()[-160:]})"))
    finally:
        sleeper.kill()
        for s in listeners:
            s.close()
        for path in sockets.values():
            if os.path.exists(path):
                os.remove(path)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)
        if os.path.exists(escape_marker):
            os.remove(escape_marker)
    print(f"passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
