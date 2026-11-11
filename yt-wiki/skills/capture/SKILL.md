---
name: capture
description: Save new knowledge from a yt-wiki work order into the vault as a note. Use when a yt-wiki work order asks to capture, record, or file something. Do not use outside a yt-harness sub-session.
---

# Capture into the vault

The vault path is in `TASK.md`. Write the way this vault already does.

1. Run `yt-vault <vault>`: kind, where new notes go, file names, metadata, link
   style, search and skip folders, git. Read any rule files it lists; they win over
   everything here. Conventions seen in existing notes win over its defaults.
2. Read two or three notes near where yours will go and copy their shape.
3. Capture only what the brief asks for. If a note on the subject exists
   (`grep -ril` over the search folders), update it instead of adding a duplicate.
4. Otherwise create the note per `newNotes`, `fileName`, and `metadata`. Record the
   source (input file or "brief") and today's date the vault's way (`source`/`captured`
   in YAML, `source::`/`captured::` in Logseq). Link related notes in its link style.
   One subject per note, short and factual, in the brief's language. For a docs site, add the page to the
   navigation only when it lists pages explicitly.
5. Never touch tool folders (`.obsidian/`, `logseq/`, templates) or unrelated notes.
6. Run `yt-mask` on every note you wrote; fix findings with `yt-mask --fix` and say
   in result.md which kinds were masked. No secrets or personal data in the vault.
7. In a git vault, commit on the work order's branch.
8. `out/result.md`: the vault kind, the notes created or updated (vault-relative
   paths), and the commit in a git vault.
