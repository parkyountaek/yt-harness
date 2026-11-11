---
name: spec
description: Write a specification before code for a yt-code work order, and implement it when the brief asks. Use instead of code-change when the brief asks for a spec, PRD, or spec-first work. Do not use outside a yt-harness sub-session.
---

# Spec first

1. Read the files under `in/` and the repository's own rules. Look for existing specs
   or PRDs (`docs/specs/`, `docs/prd/`, `specs/`) and copy their location and shape.
   With none, use `docs/specs/<slug>.md`.
2. Work only in the clone on the branch the work order names. Never add remotes or
   change git config or hooks. Commit only source files: never caches or build output.
3. Write the spec, short: Goal, Scope and non-goals, Behavior (each as a checkable
   statement), Done criteria. Base it on the brief and the code; mark anything the
   brief leaves open as an open question rather than deciding it.
4. If an open question changes the behavior, ask with
   `yt-status waiting-human --question "<one sentence>"` before implementing.
5. Commit the spec alone. Stop here unless the brief asks for the implementation.
6. When it does: implement exactly the behavior the spec lists, run the repository's
   tests or checks, and add a test only for behavior that has none. Commit
   separately. If the code shows the spec is wrong, fix the spec in the same commit
   and say so.
7. `out/result.md`: the spec path, its open questions, what was implemented (or
   "spec only"), the checks you ran, and `git log --oneline` of the branch.
