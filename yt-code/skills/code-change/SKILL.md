---
name: code-change
description: How to carry out a yt-code work order (a code change on a private clone). Use when a work order (TASK.md) names the yt-code harness. Do not use outside a yt-harness sub-session.
---

# Code change

1. Read the work order (`TASK.md`), every file it names under `in/`, and the
   repository's own rules (AGENTS.md, CLAUDE.md, README, contributing notes).
2. Work only in the clone named in the work order, on the branch it names. Never
   push, never add remotes, never change git config or hooks. Write nothing outside
   the clone and `out/`.
3. If the brief leaves a choice open that changes the code, ask once with
   `yt-status waiting-human --question "<one sentence>"` and wait for the reply.
4. Make the smallest change that meets the brief. Run the repository's tests or
   checks that cover it when they exist and can run here.
5. Commit on the task branch with a message that says what changed and why. Leave
   nothing uncommitted.
6. Write `out/result.md`, overwriting it: what changed (files and why), the commits
   (`git log --oneline` of the branch), the tests or checks you ran with their result,
   and anything left undone. Say plainly when a check failed or could not run.
7. Run `yt-status done`. If you cannot finish, run `yt-status failed --reason "<one sentence>"`.
