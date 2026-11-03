---
name: coordinator
description: Decide how to handle a task (do it directly, use a subagent, or spawn a harnessed sub-session) and, for sub-sessions, write the work order and collect the result. Use when a task needs a different harness, is long, or needs human input midway. Do not use for short read-only questions.
---

# Coordinator

Placeholder. The full procedure is written once the milestone passes (see `docs/plan.md` section 5).

Decision ladder, stop at the first match:
1. Do it directly: short, read-only work.
2. Subagent: only the result is needed.
3. Sub-session: needs another harness, is long, or needs a human midway. Run `yt-spawn <task-id> <harness>`.
