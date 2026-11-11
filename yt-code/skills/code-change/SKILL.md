---
name: code-change
description: How to carry out a yt-code work order (a code change on a private clone). Use when a work order (TASK.md) names the yt-code harness, unless the brief asks for TDD, an ADR, or a spec (then use tdd, adr, or spec). Do not use outside a yt-harness sub-session.
---

# Code change

1. Read the files under `in/` and the repository's own rules (AGENTS.md, CLAUDE.md,
   README, contributing notes).
2. Work only in the clone on the branch the work order names. Never add remotes or
   change git config or hooks. Commit only source files: never caches or build output
   (`__pycache__/`, `node_modules/`, ...), even when the repository does not ignore them.
3. Make the smallest change that meets the brief. Run the repository's tests or
   checks that cover it when they exist and can run here.
4. Commit on the task branch, saying what changed and why. Leave nothing uncommitted.
5. `out/result.md`: what changed (files and why), `git log --oneline` of the branch,
   the checks you ran and their result (say plainly when one failed or could not
   run), and anything left undone.
