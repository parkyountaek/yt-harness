---
name: capture
description: Save new knowledge from a yt-wiki work order into the vault as a note. Use when a yt-wiki work order asks to capture, record, or file something. Do not use outside a yt-harness sub-session.
---

# Capture into the vault

The vault path is in the work order (`TASK.md`, "Vault"). Vaults differ (Obsidian,
Logseq, Dendron, MkDocs or Docusaurus docs, a plain folder); write the way this one does.

1. Run `yt-vault <vault>`. It prints the kind and conventions: where new notes go,
   file names, metadata, link style, folders to search and to skip, and whether it
   is a git repository. If it lists rule files, read them now: they win over
   everything else here, including the output of `yt-vault`.
2. Read two or three existing notes near where yours will go and copy their shape
   (headings, metadata keys, tags, language). Conventions you see in the notes win
   over the defaults that `yt-vault` prints.
3. Read the brief and the inputs under `in/`. Capture only what the brief asks for.
4. Look for an existing note on the same subject first (`grep -ril "<keyword>"` over
   the search folders, skipping the skip folders). Update it rather than adding a
   duplicate.
5. Otherwise create the note where `newNotes` says, named as `fileName` says, with
   the metadata `metadata` names. Record where the knowledge came from (input file
   name or "brief") and today's date in the vault's own way (a `source` and a
   `captured` key in YAML, `source::` and `captured::` properties in Logseq). Link
   related notes in the vault's link style. One subject per note, short and factual,
   in the language of the brief (not of your user-level instructions). For a docs
   site, add the page to the navigation only when the navigation lists pages explicitly.
6. Never touch the tool's own folders (`.obsidian/`, `logseq/`, templates) or other
   notes beyond the update in step 4. In a git vault, do not commit.
7. Run `yt-mask <note>` on every note you wrote. If it reports anything, run
   `yt-mask --fix <note>` and mention in result.md which kinds were masked. Never keep
   secrets, credentials, or personal data in the vault.
8. Write `out/result.md`: the vault kind, then the notes created or updated (paths
   relative to the vault), one line each. Then `yt-status done`.
