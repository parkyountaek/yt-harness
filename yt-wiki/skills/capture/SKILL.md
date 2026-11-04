---
name: capture
description: Save new knowledge from a yt-wiki work order into the vault as a note. Use when a yt-wiki work order asks to capture, record, or file something. Do not use outside a yt-harness sub-session.
---

# Capture into the vault

The vault path is in the work order (`TASK.md`, "Vault").

1. Read the brief and the inputs under `in/`. Capture only what the brief asks for.
2. Look for an existing note on the same subject first (`grep -ril "<keyword>" <vault>`).
   Update it rather than adding a duplicate.
3. New notes go to `<vault>/inbox/<yyyy-mm-dd>-<short-slug>.md` with this header:

   ```
   ---
   title: <one line>
   source: <input file name or "brief">
   captured: <yyyy-mm-dd>
   tags: [<a few>]
   ---
   ```

   Then the knowledge itself: short, factual, one subject per note, in the language
   of the brief (not of your user-level instructions).
4. Before you finish, run `yt-mask <note>` on every note you wrote. If it reports
   anything, run `yt-mask --fix <note>` and mention in result.md which kinds were masked.
   Never keep secrets, credentials, or personal data in the vault.
5. Write `out/result.md`: the notes created or updated (paths relative to the vault),
   one line each. Then `yt-status done`.
