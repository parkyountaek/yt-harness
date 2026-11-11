---
name: tdd
description: Carry out a yt-code work order test-first (red, green, refactor). Use instead of code-change when the brief asks for TDD or test-first. Do not use outside a yt-harness sub-session.
---

# Test-driven change

1. Read the files under `in/` and the repository's own rules (AGENTS.md, CLAUDE.md,
   README, contributing notes). Find how its tests run.
2. Work only in the clone on the branch the work order names. Never add remotes or
   change git config or hooks.
3. Red: write the smallest test that states the brief's behavior. Run it and see it
   fail for the expected reason. Commit the test alone (`test: ...`).
4. Green: make the smallest code change that passes it, without changing the test.
   Run the related tests. Commit (`feat:` or `fix: ...`).
5. Refactor only if it clearly helps, with the tests passing; commit separately.
   Repeat 3-5 for each behavior the brief asks for.
6. Keep tests lean: one test per behavior the brief names, plus an edge case only when
   the brief or a real bug calls for it. No tests for trivial code, no duplicate cases,
   no new test helpers or mocks beyond what the test needs.
7. If the repository has no test setup that can run here, stop and ask with
   `yt-status waiting-human` rather than skipping the red step.
8. `out/result.md`: each behavior with its test, the failing output from the red step
   (one or two lines), the passing run, `git log --oneline` of the branch, and
   anything left undone.
