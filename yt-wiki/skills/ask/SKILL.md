---
name: ask
description: Answer a question from the notes in the vault, citing them. Use when a yt-wiki work order asks a question about stored knowledge. Do not use outside a yt-harness sub-session.
---

# Answer from the vault

The vault path is in the work order (`TASK.md`, "Vault"). Do not change the vault.

1. Run `yt-vault <vault>` for its kind, the folders to search and to skip, and its
   link style. If it lists rule files, read them first.
2. Search the search folders for the question's keywords (`grep -ril`), skipping the
   skip folders, then read the matches. Follow the vault's links (`[[...]]` or
   relative Markdown links) from a matching note one step, and check notes that
   link to it, when the answer may be spread out. In Logseq, journals count as notes.
3. Answer only from what the notes say. If notes disagree, prefer the newer one by
   its date metadata and say that they disagree. If the notes do not cover it, say
   so plainly rather than filling the gap from general knowledge.
4. Write `out/result.md` in the language of the brief (not of your user-level
   instructions): the answer first, then a "Sources" list with each note's path
   relative to the vault.
5. Run `yt-mask out/result.md`; mask anything it reports (`yt-mask --fix`).
6. `yt-status done`.
