---
name: adr
description: Record an architecture decision (ADR) for a yt-code work order. Use instead of code-change when the brief asks for an ADR or to record a design decision. Do not use outside a yt-harness sub-session.
---

# Architecture decision record

1. Read the files under `in/` and the repository's own rules. Look for existing ADRs
   (`docs/adr/`, `doc/adr/`, `adr/`, `docs/decisions/`) and copy their location,
   numbering, file naming, and sections. With none, use `docs/adr/NNNN-<slug>.md`
   with Title, Status, Context, Decision, Consequences.
2. Work only in the clone on the branch the work order names. Never add remotes or
   change git config or hooks. Commit only source files: never caches or build output.
3. Ground the context in the repository: name the code, constraints, and numbers the
   decision rests on. List the options the brief or the code makes real, each with its
   main trade-off; do not invent options to fill a section.
4. If the brief does not settle the decision, ask with
   `yt-status waiting-human --question "<one sentence>"` instead of choosing for the
   human. Status is `Proposed` unless the brief says the decision is made.
5. One decision per ADR, about a page. If an earlier ADR is replaced, mark it
   superseded the way the repository does. Change no code unless the brief asks.
6. Commit, following the repository's commit style.
7. `out/result.md`: the ADR path, its status, the decision in one sentence, the
   options weighed, and `git log --oneline` of the branch.
