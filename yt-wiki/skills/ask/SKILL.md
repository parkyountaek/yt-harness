---
name: ask
description: Answer a question from the notes in the vault, citing them. Use when a yt-wiki work order asks a question about stored knowledge. Do not use outside a yt-harness sub-session.
---

# Answer from the vault

Do not change the vault (path in `TASK.md`).

1. Run `yt-vault <vault>` for its kind, search and skip folders, and link style. Read
   any rule files it lists first.
2. `grep -ril` the question's keywords over the search folders, skipping the skip
   folders, and read the matches. Follow links one step from matching notes, and
   check notes that link to them. In Logseq, journals count as notes.
3. Answer only from the notes. If notes disagree, prefer the newer one by its date
   metadata and say they disagree. If the notes do not cover it, say so.
4. `out/result.md`: the answer, then "Sources" with each note's path relative to the
   vault. Run `yt-mask out/result.md`; fix anything it reports with `yt-mask --fix`.
