---
name: ask
description: Answer a question from the notes in the vault, citing them. Use when a yt-wiki work order asks a question about stored knowledge. Do not use outside a yt-harness sub-session.
---

# Answer from the vault

The vault path is in the work order (`TASK.md`, "Vault"). Do not change the vault.

1. Search the vault for the question's keywords (`grep -ril`, then read the matches).
2. Answer only from what the notes say. If the notes do not cover it, say so plainly
   rather than filling the gap from general knowledge.
3. Write `out/result.md` in the language of the brief (not of your user-level
   instructions): the answer first, then a "Sources" list with each note's path
   relative to the vault.
4. Run `yt-mask out/result.md`; mask anything it reports (`yt-mask --fix`).
5. `yt-status done`.
