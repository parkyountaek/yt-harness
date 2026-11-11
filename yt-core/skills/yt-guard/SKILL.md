---
name: yt-guard
description: What to do when a command is blocked with "yt-guard blocked this". Explains the block, offers a read-only alternative, and how the human can lift it. Use only after such a block.
---

# yt-guard blocks

The block message says what was blocked and what to do instead.

1. Do not retry it in another form (other tool, script, alias, encoding).
2. Tell the human in one or two sentences what was blocked and why you needed it.
3. Offer the alternative from the message, or ask the human to run the step and share
   the output that matters (never the secret itself).
4. To allow a category, the human restarts the session with `YT_GUARD_ALLOW=<category>`
   in their own shell. Setting it inside a command has no effect; never suggest editing
   hook or guard files.
