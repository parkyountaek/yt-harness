#!/usr/bin/env python3
"""yt-guard decisions. Every case runs through bin/yt-guard as a Claude-shaped and a
Codex-shaped PreToolUse event; both must give the expected verdict (same script, same
result for both runtimes).

Usage: tests/guard/run.py      exit 0 when every case passes
"""
import json
import os
import subprocess
import sys
import tempfile
import io
import runpy
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
GUARD = os.path.join(REPO, "yt-core", "bin", "yt-guard")

CASES = [  # (expect, tool, command or path, YT_GUARD_ALLOW)
    ("allow", "Bash", "kubectl get pods -n prod", ""),
    ("allow", "Bash", "kubectl describe deploy api", ""),
    ("block", "Bash", "kubectl apply -f deploy.yaml", ""),
    ("block", "Bash", "kubectl -n prod delete pod api-1", ""),
    ("block", "Bash", "sudo kubectl rollout restart deploy/api", ""),
    ("block", "Bash", "kubectl config use-context prod", ""),
    ("allow", "Bash", "terraform plan", ""),
    ("block", "Bash", "terraform apply -auto-approve", ""),
    ("block", "Bash", "terraform state rm aws_instance.x", ""),
    ("allow", "Bash", "helm list -A", ""),
    ("block", "Bash", "helm upgrade api ./chart", ""),
    ("allow", "Bash", "aws s3 ls s3://bucket", ""),
    ("block", "Bash", "aws ec2 terminate-instances --instance-ids i-1", ""),
    ("block", "Bash", "gcloud run deploy api --image x", ""),
    ("allow", "Bash", "gcloud projects list", ""),
    ("block", "Bash", "alembic upgrade head", ""),
    ("block", "Bash", "echo ok && bash -c 'kubectl delete ns x'", ""),
    ("block", "Bash", "psql -h db.internal -U app", ""),
    ("block", "Bash", "redis-cli -h cache", ""),
    ("allow", "Bash", "sqlite3 local.db .tables", ""),
    ("block", "Bash", "cat .env", ""),
    ("block", "Bash", "grep TOKEN config/.env.production", ""),
    ("allow", "Bash", "cat .env.example", ""),
    ("block", "Bash", "cat ~/.ssh/id_ed25519", ""),
    ("allow", "Bash", "cat ~/.ssh/id_ed25519.pub", ""),
    ("block", "Bash", "cat ~/.aws/credentials", ""),
    ("allow", "Bash", "grep -n credentials README.md", ""),
    ("block", "Bash", "cat < secrets.json", ""),
    ("block", "Bash", "cat 'unbalanced .env", ""),
    ("allow", "Bash", "echo 'unbalanced", ""),
    ("block", "Read", "/repo/.env", ""),
    ("block", "Read", "/home/<user>/.kube/config", ""),
    ("allow", "Read", "/repo/src/app.py", ""),
    ("allow", "Bash", "git push origin main", ""),
    ("block", "Bash", "git push --force origin main", ""),
    ("block", "Bash", "git push -f", ""),
    ("block", "Bash", "git push --force-with-lease origin feature", ""),
    ("block", "Bash", "git push origin --delete old-branch", ""),
    ("block", "Bash", "git push origin :old-branch", ""),
    ("block", "Bash", "git -C repo push +main:main", ""),
    ("allow", "Bash", "git status && git log --oneline -3", ""),
    # exceptions come only from the session environment
    ("allow", "Bash", "kubectl apply -f deploy.yaml", "infra"),
    ("block", "Bash", "YT_GUARD_ALLOW=infra kubectl apply -f deploy.yaml", ""),
    ("block", "Bash", "export YT_GUARD_ALLOW=secrets; cat .env", ""),
    ("block", "Bash", "cat .env", "infra"),
    ("allow", "Bash", "cat .env", "secrets"),
    # Nested execution from the review (these strings are never executed).
    ("block", "Bash", "find . -maxdepth 0 -exec kubectl delete ns prod ';'", ""),
    ("block", "Bash", "xargs kubectl delete pod < pods.txt", ""),
    ("block", "Bash", "xargs -I {} /usr/bin/kubectl delete pod {}", ""),
    ("block", "Bash", "python3 -c 'import os; os.system(\"kubectl delete ns prod\")'", ""),
    ("block", "Bash", "python3 -c 'import subprocess; subprocess.run([\"git\", \"push\", \"-f\"])'", ""),
    ("allow", "Bash", "python3 -c 'print(1 + 1)'", ""),
    ("block", "Bash", "bash <<< 'psql -h db.internal'", ""),
    ("block", "Bash", 'echo "$(git push --force origin main)"', ""),
    ("block", "Bash", 'echo "`kubectl delete ns prod`"', ""),
    ("allow", "Bash", "echo '$(git push --force origin main)'", ""),
    ("block", "Bash", "env -S 'kubectl delete ns prod'", ""),
    ("block", "Bash", "env -i -S 'kubectl delete ns prod'", ""),
    ("block", "Bash", "env --split-string='kubectl delete ns prod'", ""),
    ("block", "Bash", "/usr/bin/env -u TOKEN /usr/bin/kubectl delete ns prod", ""),
    ("block", "Bash", "sudo -u root kubectl delete ns prod", ""),
    ("block", "Bash", "sudo -n kubectl delete ns prod", ""),
    ("block", "Bash", "bash -lc 'kubectl delete ns prod'", ""),
    ("block", "Bash", "alias k='kubectl'; k delete ns prod", ""),
    ("block", "Bash", "npx prisma migrate deploy", ""),
    ("block", "Bash", "npx --yes prisma migrate deploy", ""),
    ("block", "Bash", "kubectl --request-timeout 10s delete pod api", ""),
    ("block", "Bash", "aws s3api upload-part --bucket b --key k --part-number 1 --upload-id x --body data", ""),
    # Paths, expansions and alternate read tools.
    ("block", "Bash", 'p=.env; cat "$p"', ""),
    ("block", "Bash", "cat ./.e[n]v", ""),
    ("block", "Bash", "cat ~/.kube/./config", ""),
    ("block", "Bash", "cat secret-link", ""),
    ("block", "Bash", "python3 -c 'print(open(\".env\").read())'", ""),
    ("block", "Bash", "cat .env; cat <<'EOF'\n'\nEOF", ""),
    ("allow", "Bash", "kubectl delete ns prod '", ""),  # infra parsing fails open
    ("block", "mcp__filesystem__read_file", ".env", ""),
    ("block", "Read", "secret-link", ""),
    # Git global options, short-option bundles, inline and stored configuration.
    ("block", "Bash", "git -C. push --force origin main", ""),
    ("block", "Bash", "git --work-tree=. push origin :old-branch", ""),
    ("block", "Bash", "git --git-dir=.git push --force", ""),
    ("block", "Bash", "git push -vf origin main", ""),
    ("block", "Bash", "git -c alias.pf='push --force' pf origin main", ""),
    ("block", "Bash", "git -calias.pf='push --force' pf origin main", ""),
    ("block", "Bash", "git -c alias.pf='!git push --force' pf", ""),
    ("block", "Bash", "git -c remote.origin.mirror=true push origin", ""),
    ("block", "Bash", "git -c remote.origin.push=+main:main push origin", ""),
    ("block", "Bash", "git pf origin main", ""),
    ("block", "Bash", "git -C mirror push origin", ""),
    ("allow", "Bash", "git -C. push origin main", ""),
    # Open shells allow stdin that some runtimes do not hook again.
    ("block", "Bash", "bash", ""),
    ("block", "Bash", "bash -i", ""),
    ("block", "Bash", "bash -il", ""),
    ("block", "Bash", "python3", ""),
    ("allow", "Bash", "bash --version", ""),
    ("block", "Bash", "bash", "infra,db,git"),
    ("allow", "Bash", "bash", "infra,db,secrets,git"),
    # Normal development commands previously rejected.
    ("allow", "Bash", "test -f .env", ""),
    ("allow", "Bash", "touch .env", ""),
    ("allow", "Bash", "echo .env", ""),
    ("block", "Bash", "echo ok < .env", ""),
    ("allow", "Bash", "openssl x509 -in cert.pem -noout -dates", ""),
    ("block", "Bash", "openssl pkey -in private.pem -text", ""),
    ("allow", "Bash", "kubectl rollout status deployment/api", ""),
    ("allow", "Bash", "kubectl rollout history deployment/api", ""),
    ("allow", "Bash", "kubectl apply --dry-run=client -f deploy.yaml", ""),
    ("allow", "Bash", "kubectl apply --dry-run client -f deploy.yaml", ""),
    ("block", "Bash", "kubectl apply --dry-run=server -f deploy.yaml", ""),
    ("block", "Bash", "kubectl apply --dry-run=client --dry-run=none -f deploy.yaml", ""),
    ("allow", "Bash", "prisma migrate status", ""),
    ("allow", "Bash", "psql --version", ""),
    ("allow", "Bash", "redis-cli --help", ""),
    ("allow", "Bash", "aws s3 ls s3://bucket --profile delete", ""),
    ("allow", "Bash", "aws --profile delete s3 ls s3://bucket", ""),
    ("allow", "Bash", "aws s3 ls --profile delete s3://bucket", ""),
    ("allow", "Bash", "gcloud run services list", ""),
    ("allow", "Bash", "git push -of origin main", ""),
    ("allow", "Bash", "git push -o +metadata origin main", ""),
    ("allow", "Bash", "git -C mirror push upstream main", ""),
]


def event(runtime, tool, value, cwd):
    tool_input = {"file_path": value} if tool == "Read" else {"command": value}
    if tool.startswith("mcp__"):
        tool_input = {"path": value}
    base = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "cwd": cwd, "session_id": "test"}
    if runtime == "codex":
        base.update(turn_id="t", model="m", permission_mode="bypassPermissions", tool_use_id="exec-1")
    return json.dumps(base)


def main():
    with tempfile.TemporaryDirectory(prefix="ytguard") as local:
        return run(local)


def run(local):
    # Fixture files contain no real secrets. Git commands only set up local config.
    with open(os.path.join(local, ".env"), "w") as f:
        f.write("FAKE=fixture\n")
    os.symlink(".env", os.path.join(local, "secret-link"))
    subprocess.run(["git", "init", "-q", local], check=True)
    subprocess.run(["git", "-C", local, "config", "alias.pf", "push --force"], check=True)
    mirror = os.path.join(local, "mirror")
    subprocess.run(["git", "init", "-q", mirror], check=True)
    subprocess.run(["git", "-C", mirror, "config", "remote.origin.mirror", "true"], check=True)
    # A mutable config.json must not disable the hook on the next invocation.
    with open(os.path.join(local, "config.json"), "w") as f:
        json.dump({"guard": "off"}, f)
    passed = failed = 0
    for expect, tool, value, allow in CASES:
        for runtime in ("claude", "codex"):
            env = dict(os.environ, YT_GUARD_ALLOW=allow, YT_LOCAL=local)
            r = subprocess.run([sys.executable, GUARD], input=event(runtime, tool, value, local), env=env,
                               capture_output=True, text=True)
            got = {0: "allow", 2: "block"}.get(r.returncode, f"rc={r.returncode}")
            if got == "allow" and r.stdout.strip():
                got = "allow-with-output"   # the guard must never answer for other hooks
            if got == "block" and (r.stdout or not r.stderr):
                got = "invalid-block-output"
            ok = got == expect
            passed += ok
            failed += not ok
            if not ok:
                print(f"FAIL [{runtime}] {tool} {value!r} allow={allow!r}: want {expect}, got {got}")
    # Malformed events and internal failures must never silently bypass secrets.
    hook = runpy.run_path(GUARD)
    for payload in ("{", "[]", '{"tool_input": "invalid"}', '{"tool_input": {"command": 42}}'):
        for allow, expect in (("", 2), ("secrets", 0)):
            with patch.dict(os.environ, {"YT_GUARD_ALLOW": allow}), patch("sys.stdin", io.StringIO(payload)), \
                    redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
                rc = hook["main"]()
            ok = rc == expect and not stdout.getvalue()
            passed += ok
            failed += not ok
            if not ok:
                print(f"FAIL invalid event {payload!r} allow={allow!r}: rc={rc}")
    for allow, expect in (("", 2), ("secrets", 0)):
        with patch.dict(os.environ, {"YT_GUARD_ALLOW": allow}), \
                patch("sys.stdin", io.StringIO(event("claude", "Bash", "cat .env", local))), \
                patch.object(hook["guard"], "check", side_effect=RuntimeError("injected")), \
                redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
            rc = hook["main"]()
        ok = rc == expect and not stdout.getvalue()
        passed += ok
        failed += not ok
        if not ok:
            print(f"FAIL check exception allow={allow!r}: rc={rc}")
    print(f"passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
