---
name: panel
description: Show the yt-harness overview (what needs the human, running sub-sessions, harness health, retire hints). Use when the human asks for the overview, the status of the harness or its tasks, or types /yt or "yt panel".
---

# Panel

1. Run `yt panel`.
2. Report "Needs you" first, one line per item, with the command it suggests. If it is
   empty, say so in one line.
3. Then running tasks, then anything unusual in Harnesses (off, experimental, low
   success), Retire?, Harness candidates, and Health. Skip sections with nothing new.
4. Do not act on the suggestions yourself (answer, resume, stop, retire). Each needs
   the human's decision.
5. If the human wants to keep watching, suggest `yt watch` in a separate terminal: a live
   view with a desktop notice when a task needs them (works next to Claude or Codex).
