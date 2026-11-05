#!/bin/sh
# The Claude interface mods in mods/: each mod's own tests and manifest check.
# Skips (exit 0) when Claude Code is not installed: the mods are Claude-only.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
if ! command -v claude >/dev/null 2>&1; then echo "skip: claude not installed"; exit 0; fi
fail=0
cd "$ROOT/mods" || exit 1
for m in */; do
  m=${m%/}
  [ -f "$m/.claude-plugin/plugin.json" ] || continue
  if claude plugin validate "$m" >/dev/null 2>&1; then :; else echo "FAIL $m: plugin validate"; fail=1; fi
  out=$(claude plugin test "$m" 2>&1)
  pass=$(printf '%s\n' "$out" | sed -n 's/^ *\([0-9][0-9]*\) pass$/\1/p' | tail -1)
  bad=$(printf '%s\n' "$out" | sed -n 's/^ *\([0-9][0-9]*\) fail$/\1/p' | tail -1)
  if [ "${bad:-1}" = 0 ]; then echo "PASS $m: ${pass:-0} tests"; else echo "FAIL $m: ${bad:-?} failed"; fail=1; fi
done
[ "$fail" -eq 0 ] && echo "mods ok"
exit $fail
