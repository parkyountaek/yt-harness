#!/bin/sh
# Fails when any instruction file reaches 200 lines (rule in AGENTS.md).
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LIMIT=200
fail=0
for f in "$ROOT/AGENTS.md" $(find "$ROOT" -path "$ROOT/.git" -prune -o \
         \( -name SKILL.md -o -path "*/agents/*.md" \) -type f -print); do
  n=$(wc -l < "$f" | tr -d ' ')
  if [ "$n" -ge "$LIMIT" ]; then echo "FAIL ${f#$ROOT/}: $n lines (limit $LIMIT)"; fail=1; fi
done
# The work order template in yt-spawn counts too.
n=$(python3 -c "import re,sys;s=open(sys.argv[1]).read();print(re.search(r'TASK_TEMPLATE = \"\"\"(.*?)\"\"\"',s,re.S).group(1).count(chr(10)))" "$ROOT/yt-core/bin/yt-spawn")
if [ "$n" -ge "$LIMIT" ]; then echo "FAIL TASK.md template: $n lines"; fail=1; fi
[ "$fail" -eq 0 ] && echo "instruction files ok (limit $LIMIT lines)"
exit $fail
