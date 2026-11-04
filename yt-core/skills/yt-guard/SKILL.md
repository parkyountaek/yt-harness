---
name: yt-guard
description: What to do when a command is blocked with "yt-guard blocked this". Explains the block, offers a read-only alternative, and how the human can lift it. Use only after such a block.
---

# yt-guard blocks

yt-guard checks each command before it runs and blocks four kinds of action:

| Category | Blocked | Still allowed |
|---|---|---|
| infra | writes via kubectl, terraform, helm, aws, gcloud, az, migration tools | get, describe, logs, plan, list, status |
| db | interactive database clients (psql, mysql, mongosh, redis-cli, ...) | local sqlite3, reading exports |
| secrets | reading or printing .env, keys, credentials, kube or cloud configs | `.env.example`, public keys |
| git | force push, deleting remote branches, mirror push | normal push, local history |

When a command is blocked:

1. Do not retry it in another form (other tool, script, alias, encoding). That is a
   workaround, and it defeats the point of the block.
2. Tell the human, in one or two sentences, what was blocked and why it was needed.
3. Offer the read-only alternative from the block message, or ask the human to run the
   step themselves and share the output that matters (never the secret itself).
4. If the human wants to allow the category, they restart the session with
   `YT_GUARD_ALLOW=<category>` set in their own shell. Setting it inside a command has
   no effect, and you must not suggest editing hook or guard files.
