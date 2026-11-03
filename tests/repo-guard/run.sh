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
export YT_BLOCKED_PATHS="$TMP/blocked-paths.txt"
printf 'docs/local-notes.md\n' > "$YT_BLOCKED_PATHS"

setup; expect ok     "allowed path"            commit_file docs/note.md "hello"
setup; expect reject "path outside allowlist"  commit_file notes.txt "hello"
setup; expect reject "github token"            commit_file docs/t.md "token gh""p_$(printf 'a%.0s' $(seq 1 36))"
setup; expect reject "private key"             commit_file docs/k.md "-----BEGIN RSA PRIV""ATE KEY-----"
setup; expect reject "personal absolute path"  commit_file docs/p.md "see /Us""ers/alice/work"
setup; expect ok     "placeholder path"        commit_file docs/p.md "see /Users/<user>/yt-work"
setup; expect reject "local blocked path"      commit_file docs/local-notes.md "notes"
setup; expect reject "local blocked term"      commit_file docs/b.md "host api.example-corp.internal"

# Fake secrets are assembled at run time so this file never matches the guard.
E=''   # empty string used to split fake secrets inside the heredoc
rep() { printf "%${2}s" "" | tr ' ' "$1"; }   # rep <char> <count>
A20=$(rep a 20); A36=$(rep a 36); A40=$(rep A 40); H32=$(rep f 32)
while IFS='|' read -r name value; do
  [ -z "$name" ] && continue
  setup; expect reject "secret: $name" commit_file docs/s.md "$value"
done <<EOF
github fine-grained|github${E}_pat_$(rep a 60)
gitlab token|gl${E}pat-$A20
npm token|np${E}m_$A36
pypi token|py${E}pi-AgE$(rep a 60)
aws session key|AS${E}IA$(rep A 16)
aws secret key|aws_secret_access_key = $A40
google api key|AI${E}za$(rep a 35)
gcp service account|{"ty${E}pe": "service_account"}
azure storage key|Account${E}Key=$A40
openai project key|s${E}k-proj-$A20$A20
anthropic key|s${E}k-ant-$A20$A20
huggingface token|h${E}f_$A36
slack token|xo${E}xb-1234567890-$A20
slack webhook|https://hooks.sl${E}ack.com/services/T000/B000/$A20
discord webhook|https://discord.com/api/web${E}hooks/123456/$A20
telegram bot token|123456789:A${E}A$(rep a 33)
stripe key|s${E}k_live_$A20
sendgrid key|S${E}G.$(rep a 22).$(rep a 43)
twilio key|S${E}K$H32
jwt|ey${E}J$(rep a 12).ey${E}J$(rep a 12).$(rep a 12)
openssh private key|-----BEGIN OPENSSH PRIV${E}ATE KEY-----
url with password|postgres:${E}//admin:hunter2pass@db.local:5432/app
secret assignment|DB_PASS${E}WORD=$(rep x 20)
EOF

# Sensitive file names are rejected even inside an allowed directory.
for f in docs/.env docs/.env.local docs/.env.production docs/id_rsa docs/id_ed25519 docs/server.pem \
         docs/tls.key docs/cert.p12 docs/credentials.json docs/service-account-prod.json \
         docs/terraform.tfstate docs/prod.tfvars docs/.npmrc docs/.netrc docs/.git-credentials docs/.kube/config; do
  setup; expect reject "sensitive name: $f" commit_file "$f" "x"
done

# Placeholders and templates must stay allowed.
setup; expect ok "template .env.example"       commit_file docs/.env.example "API_KEY=<your-key>"
setup; expect ok "placeholder assignment"      commit_file docs/c.md 'API_TOKEN=${API_TOKEN}'
setup; expect ok "short assignment value"      commit_file docs/c.md "PASSWORD=changeme"
setup; expect ok "url without password"        commit_file docs/c.md "https://user@github.com/org/repo"
setup; expect ok "git sha is not a key"        commit_file docs/c.md "commit $(rep f 40)"

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
