#!/bin/sh
# Regression tests for .githooks/repo_guard.py.
# Builds a throwaway repo, copies the guard and allowlist into it, and checks
# that each case is accepted or rejected as expected.
set -u
SRC=$(cd "$(dirname "$0")/../.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/yt-guard-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

setup() {
  rm -rf "$TMP/repo" "$TMP/remote.git"
  git init -q -b main "$TMP/repo"
  git init -q --bare "$TMP/remote.git"
  cd "$TMP/repo" || exit 2
  git config user.email "1+tester@users.noreply.github.com"
  git config user.name tester
  git config core.hooksPath .githooks
  git remote add origin "$TMP/remote.git"
  mkdir -p .githooks docs
  cp "$SRC/.githooks/repo_guard.py" "$SRC/.githooks/pre-commit" "$SRC/.githooks/pre-push" .githooks/
  cp "$SRC/allowlist.txt" .
  git add -A && git commit -q -m init
}

expect() {  # expect <ok|reject> <name> <command...>
  want=$1; name=$2; shift 2
  if "$@" >/dev/null 2>&1; then got=ok; else got=reject; fi
  if [ "$got" = "$want" ]; then pass=$((pass + 1)); echo "PASS $name"
  else fail=$((fail + 1)); echo "FAIL $name (want $want, got $got)"; fi
}

commit_file() {  # commit_file <path> <content>
  mkdir -p "$(dirname "$1")"; printf '%s\n' "$2" > "$1"; git add "$1" && git commit -q -m "add $1"
}

export YT_BLOCKED_TERMS="$TMP/blocked-terms.txt"
printf 'example-corp.internal\n' > "$YT_BLOCKED_TERMS"

setup; expect ok     "allowed path"            commit_file docs/note.md "hello"
setup; expect reject "path outside allowlist"  commit_file notes.txt "hello"
setup; expect reject "github token"            commit_file docs/t.md "token gh""p_$(printf 'a%.0s' $(seq 1 36))"
setup; expect reject "private key"             commit_file docs/k.md "-----BEGIN RSA PRIV""ATE KEY-----"
setup; expect reject "personal absolute path"  commit_file docs/p.md "see /Us""ers/alice/work"
setup; expect ok     "placeholder path"        commit_file docs/p.md "see /Users/<user>/yt-work"
setup; expect reject "local blocked term"      commit_file docs/b.md "host api.example-corp.internal"

setup; expect ok     "push clean branch"       git push -q origin main
setup
git config core.hooksPath /dev/null
printf 'x\n' > stray.txt; git add stray.txt; git commit -q -m "bypass pre-commit"
git config core.hooksPath .githooks
expect reject "push catches bypassed commit" git push -q origin main

setup
git config user.email "someone@example.com"
printf 'x\n' > docs/e.md; git add docs/e.md
git -c core.hooksPath=/dev/null commit -q -m "non-noreply author"
expect reject "push rejects non-noreply author" git push -q origin main

echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
