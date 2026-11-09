---
name: improve-proposal
description: How to carry out a yt-improve work order (a proposal to change one harness's skills). Use when a work order (TASK.md) names the yt-improve harness. Do not use outside a yt-harness sub-session.
---

# Improvement proposal

1. Read the work order (`TASK.md`) and its brief: results per version, eval verdicts,
   and case cards. They are numbers and shapes only; there is no task content.
2. In the clone, read the target harness: its `harness.yaml` and every file under
   its `skills/`. Read the repository rules (`AGENTS.md`) too.
3. Diagnose from the numbers. Name the signal you act on (a success drop, human
   fixes, many turns or resumes, an eval failing) and the step in the skill that
   plausibly causes it. If the numbers are too few or say nothing clear, change
   nothing: say so in the result and finish.
4. Otherwise make the smallest change to the skill text that addresses it, and
   raise the patch part of `version:` in the target's `harness.yaml` (0.1.0 to
   0.1.1). Change nothing else: yt rejects a branch outside that scope. Keep the
   skill under 200 lines.
5. Commit on the task branch. Never push.
6. Write `out/result.md`, overwriting it: the signal and the numbers behind it, the
   change (or why none), the metric it should move and how to tell after the next
   few tasks (`yt improve <harness>`), and the risk.
7. Run `yt-status done`. If you cannot finish, run `yt-status failed --reason "<one sentence>"`.
