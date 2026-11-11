---
name: improve-proposal
description: How to carry out a yt-improve work order (a proposal to change one harness's skills). Use when a work order (TASK.md) names the yt-improve harness. Do not use outside a yt-harness sub-session.
---

# Improvement proposal

1. The brief holds results per version, eval verdicts, and case cards: numbers and
   shapes only. In the clone, read the target harness's `harness.yaml`, every file
   under its `skills/`, and `AGENTS.md`.
2. Name the signal you act on (a success drop, human fixes, many turns or resumes,
   a failing eval) and the skill step that plausibly causes it. If the numbers are
   too few or unclear, change nothing and say so.
3. Otherwise make the smallest change to the skill text and raise the patch part of
   `version:` in the target's `harness.yaml` (0.1.0 to 0.1.1). Nothing else: yt
   rejects a branch outside that scope. Keep the skill under 200 lines. Commit.
4. `out/result.md`: the signal and its numbers, the change (or why none), the metric
   it should move and how to tell (`yt improve <harness>`), and the risk.
