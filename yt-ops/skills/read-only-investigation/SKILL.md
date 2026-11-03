---
name: read-only-investigation
description: How to carry out a yt-ops work order (read-only investigation). Use when a work order (TASK.md) names the yt-ops harness. Do not use outside a yt-harness sub-session.
---

# Read-only investigation

1. Read the work order (`TASK.md`) and every file it names under `in/`.
2. Do not change inputs. Write only inside `out/`.
3. If the brief leaves a choice open that changes the answer, ask once with
   `yt-status waiting-human --question "<one sentence>"` and wait for the reply.
4. Write `out/result.md`: the answer first, then how you got it. Overwrite, never append.
5. Run `yt-status done`. If you cannot finish, run `yt-status failed --reason "<one sentence>"`.
