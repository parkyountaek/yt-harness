# yt-harness

A personal harness for running AI coding agents (Claude Code and Codex) on tasks
in isolated, sandboxed sub-sessions. One coordinator session hands a task to a
sub-session, the sub-session works inside its own task folder, and a human can
step in at any point.

Claude and Codex get the same work order and the same sandbox, and must reach the
same states. Hard rules live in neutral layers (scripts, git hooks, the shared
sandbox profile), not in runtime-specific features.

## How it works

```
 coordinator session (Claude or Codex, with the yt-core plugin)
   │  1. decides: do it directly / use a subagent / spawn a sub-session
   │  2. yt-spawn <task-id> <harness> --runtime claude|codex
   ▼
 ~/yt-work/<task-id>/          task folder
   in/       inputs (read-only to the session)
   out/      session cwd: result.md, status.json
   tmp/      per-task TMPDIR
   TASK.md   work order, identical for every runtime
   │
   │  3. runtime starts inside the shared sandbox, in a tmux session
   ▼
 sub-session (harness plugin enabled for this run only)
   │  4. reports state only through yt-status:
   │       running → waiting-human → running → done | failed
   ▼
 human / coordinator
      5. yt status                 see every task, its state and deadline
      6. yt attach <id>            answer a question, type directly
      7. yt stop / yt resume <id>  pause and continue, same runtime session
```

- **States.** `running`, `waiting-human`, `done`, `failed` come from the session.
  `stale` is set by `yt status` when the deadline passes. `done` and `failed`
  are final. `done` requires `out/result.md`.
- **Trust boundary.** The task folder and the deadline come from the
  coordinator's registry (`~/yt-local/data/sessions.json`), never from
  `status.json`, which the session can write.
- **Concurrency.** At most 3 sub-sessions run at once. Spawn and resume exit
  with code 2 when the limit is reached.

## Layout

| Path | Role |
|---|---|
| `yt-core/` | Shared core plugin: `bin/` commands, `lib/ytlib/`, the coordinator skill, `deps.json` |
| `yt-core/lib/ytlib/platform/` | One module per OS: package install and upgrade, sandbox backend |
| `yt-core/lib/ytlib/runners/` | Runner adapters: `tmux` (default), `headless`, `orca` |
| `yt-ops/` | First harness: read-only investigation |
| `yt-wiki/` | Knowledge vault harness: capture notes, answer from them (experimental) |
| `templates/harness.yaml` | Starting point for a new harness |
| `.githooks/` | Repo guard (pre-commit and pre-push) |
| `tests/` | Repo guard, sandbox, and instruction-length tests |
| `.claude-plugin/`, `.agents/plugins/` | Marketplaces for Claude and Codex (generated) |

**yt-core** is always loaded. It provides the commands and the coordinator
skill. **A harness** (such as `yt-ops`) is a plugin with a `harness.yaml`
(purpose, sandbox read/write paths, default deadline) and its own skills. It is
loaded only inside the sub-session that uses it: Claude gets `--plugin-dir`,
Codex has it installed disabled and enabled per run.

Each plugin carries both `.claude-plugin/plugin.json` and
`.codex-plugin/plugin.json` and shares one `skills/` folder.

Machine-specific data lives outside the repo, in `~/yt-local/`: `config.json`,
`routes.json`, `blocked-terms.txt`, `blocked-paths.txt`, and `data/`
(registry, events, locks).

## Setup

```sh
git clone <this repo> && cd yt-harness
yt-core/bin/yt-setup            # install and configure everything
yt-core/bin/yt-setup --check    # report only, change nothing
yt-core/bin/yt-setup --upgrade  # upgrade tools, then rerun the repo guard tests
yt-doctor                       # read-only health check (setup, manifests, Codex copies, tasks)
yt-update [--full]              # pull the skeleton, run the tests, roll back on failure
```

`yt-setup` is safe to rerun. It:

1. Installs missing tools from `yt-core/deps.json` with the OS package manager.
   Each tool has a minimum version. Required: python3, git, gh, tmux, gitleaks,
   and the sandbox backend. Claude and Codex use their official installers.
2. Enables the repo git hooks (`core.hooksPath = .githooks`).
3. Creates `~/yt-local/` and records the checkout path.
4. Links yt-core for Claude (`CLAUDE_CODE_PLUGIN_DIRS`). For Codex it adds the
   marketplace, installs yt-core enabled, and installs every harness disabled.
5. Links the commands into `~/.local/bin`.
6. Checks that the Claude and Codex global setup match (see below).

The local layer defaults to `~/yt-local/`; set `YT_LOCAL` to move it
(`YT_WORK` moves `~/yt-work/` the same way).

It warns when tools have not been upgraded for 7 days. `--upgrade` reruns the
repo guard tests afterwards, so a gitleaks update that changes behaviour is
caught before the next commit.

### Platforms

| Platform | Packages | Sub-sessions |
|---|---|---|
| macOS | Homebrew | Yes: `sandbox-exec` |
| Linux, WSL2 | apt or dnf | Yes: bubblewrap (sandbox cases verified in a container; Claude and Codex not yet run on Linux) |
| Windows | winget or Scoop | No: setup and commits work. Run sub-sessions inside WSL2 |

Linux and Windows have not been verified on real machines yet. On Linux the
sandbox builds the filesystem view instead of denying paths: `/` read-only, `$HOME`,
`/home`, `/tmp`, `/run` as empty tmpfs, and only the task folder, yt-core, the
harness, and the runtime dirs mounted back; escape programs are covered with
`/dev/null`, and the PID namespace and terminal session are separate. Abstract
unix sockets are not isolated (that would need a network namespace).

### Moving to another machine

The repository carries the skeleton; the local layer moves by hand, never through
GitHub.

```sh
yt-export [~/yt-local-export.tar.gz] [--data]   # on the old machine
yt-import <archive> --dry-run                   # on the new machine: show the merge
yt-import <archive>                             # merge, backing up what changes
yt-core/bin/yt-setup && yt-doctor
```

The archive holds `config.json` (without `repo`), `routes.json`, `active.json`, and
the blocked lists; `--data` adds `metrics`, `evals`, and `events`. The session list,
runner state, and task folders stay behind. Home paths are written as `~/...`.
Import merges: routes by task kind and vaults by name take the archive's value,
local entries stay, and list and record lines are added once. The whole archive is
refused if it holds an unexpected file or fails its checksums. It holds your blocked
terms, so it is written with mode 600, never inside the repository; delete it after
the import.

## Usage

`yt-setup` links the `yt` commands (`yt`, `yt-spawn`, `yt-doctor`, `yt-update`,
`yt-mask`, `yt-export`, `yt-import`, ...) into `~/.local/bin` (it warns when that is
not on `PATH`).

```sh
mkdir -p ~/yt-work/read-001/in
$EDITOR ~/yt-work/read-001/in/BRIEF.md      # goal, constraints, done criteria
yt-spawn read-001 yt-ops --runtime codex --deadline 30m
yt status
yt attach read-001                          # when the state is waiting-human
yt stop read-001
yt resume read-001 --deadline 1h
yt answer read-001 "Include blank lines"    # or pass the human's answer through
yt collect read-001                         # contract check, then print result.md
yt forget read-001                          # drop a finished task from the list
yt panel                                    # what needs you, what runs, harness health
yt watch                                    # live task view + desktop notices, any terminal
yt route read-check                         # which harness handles a task kind
yt metrics --days 7                         # success rate, tokens, turns per harness and runtime
yt harness list                             # harnesses, versions, on/off, Codex copies
yt harness off yt-ops                       # refuse new sub-sessions of a harness
yt harness new doc-review "Review a document"  # scaffold an experimental harness
yt eval read-001 pass --fixed               # verdict for evaluation (no free text)
yt improve yt-ops                           # compare harness versions
yt card read-001                            # case card: shape of a task, no content
```

Roadmap frameworks and their data contracts: `docs/roadmap.md`.

Usually the coordinator skill (`yt-core/skills/coordinator/SKILL.md`) runs these
for you: it picks the harness from `~/yt-local/routes.json`, writes the brief,
relays questions word for word, and reports the collected result.

`yt-spawn` refuses an id that is already registered, and refuses an `out/`
that is not empty. The result is in `~/yt-work/<id>/out/result.md`.

Inside a sub-session the only state command is `yt-status`:

```sh
yt-status running
yt-status waiting-human --question "Which branch should I compare?"
yt-status done                     # out/result.md must exist
yt-status failed --reason "Input file is missing"
```

## Interface mods (Claude)

`mods/` holds three Claude Code mods (function-hook plugins) for the human's own
sessions. They change what the human sees, not what a sub-session does.

| Mod | What it does | Commands |
|---|---|---|
| `token-usage` | One line above the input: context use, 5-hour and 7-day limits, model and effort; one row per running subagent, click to open its transcript | `/token-usage`, `/token-usage theme` |
| `work-alerts` | Popup, sound, and macOS notification when a long turn ends, a check fails, a subagent finishes, or a limit is near | `/alerts`, `/task-alert` |
| `compact-handoff` | A task-progress line, and a handoff note so work continues after compaction | `/work`, `/handoff` |

All three also show yt-harness sub-sessions, read from `yt panel --json` (every
15 seconds for the band and alerts, once at compaction for the note):

- `token-usage`: a row `🧩 yt 1 waiting · 1 to collect · 2 running`; pressing it
  lists the tasks, needs first, each with the yt command that deals with it.
- `work-alerts`: a popup and sound when a task asks a question, finishes, passes
  its deadline, or ends without reporting. Each need is told once across all open
  sessions and `yt watch` (`~/yt-local/data/alerted.json`).
- `compact-handoff`: the handoff note lists the tasks, so a compacted coordinator
  still collects and evaluates them.

Each has a "yt-harness tasks" switch in `/config`. The mods only show and alert:
starting, answering, and collecting stay `yt` commands, which Codex sessions use the
same way (the `panel` skill gives Codex the same overview as text).

For Codex, or any terminal, `yt watch` shows the same tasks live and posts a desktop
notice (`osascript` on macOS, `notify-send` on Linux) when one needs you; it shares
the told file with `work-alerts`, so running both never tells a need twice. Codex's
own status line covers context and limits: `/statusline`, or in
`~/.codex/config.toml`:

```toml
[tui]
status_line = ["model-with-reasoning", "context-used", "five-hour-limit", "weekly-limit", "task-progress"]
```

`yt-setup` adds them to `CLAUDE_CODE_PLUGIN_DIRS` next to yt-core and points
`CLAUDE_MODS_THEME_FILE` at `~/yt-local/mods-theme.json`; `"mods": false` in
`~/yt-local/config.json` leaves them out. Settings are in `/config`.

They stay out of sub-sessions twice over: the sub-session's `--settings` drops
`mods/` from the plugin dirs (flag settings outrank `~/.claude/settings.json`), and
`disableAllHooks` stops any hooks module from loading. Codex has no equivalent
interface, so the parity check leaves `mods/` out. `tests/mods/run.sh` runs each
mod's tests and `claude plugin validate`.

## Knowledge vault (`yt-wiki`)

A `folderKind: vault` harness works inside a named folder. The vaults are listed
in `~/yt-local/config.json`:

```json
{ "vaults": { "work-notes": "~/notes/work" } }
```

```sh
yt-spawn cap-001 yt-wiki --vault work-notes --experimental   # brief: what to capture
yt-spawn ask-001 yt-wiki --vault work-notes --experimental   # brief: the question
```

The sandbox can read and write the vault, the task folder, and nothing else. The
`capture` skill files notes under `inbox/` and updates an existing note before it
adds a new one. The `ask` skill answers only from the notes and lists them as
sources. Both run `yt-mask` before they finish. `yt-mask` reports or masks secrets
(the repo guard's patterns), personal data (email, phone, resident registration and
card numbers), and the local blocked terms. It never prints the matched text.

## Runners

A runner starts and supervises the sandboxed runtime; pick it with `yt-spawn --runner`.

| Runner | How it runs | Human in the loop |
|---|---|---|
| `tmux` (default) | interactive runtime in a detached tmux session | `yt attach` to type into it, or `yt answer` |
| `headless` | `claude -p` / `codex exec`, one background process per run, no terminal | `yt answer` starts the next run on the same session with the answer; `yt attach` shows the output log |
| `orca` | interactive runtime in an Orca terminal tab (opened in the workspace from `orca.worktree` in `~/yt-local/config.json`, default this checkout) | `yt attach` brings the tab to the front; `yt answer` types into it |

Both use the same work order, sandbox, environment, and state contract. Headless
needs no tmux, so it also suits machines without a terminal multiplexer.

## Sandbox (macOS)

Both runtimes run under one generated `sandbox-exec` profile
(`<task>/sandbox-<runtime>.sb.generated`). Codex's own sandbox is set to
`danger-full-access` because sandboxes cannot be nested.

- **Writes** are denied except in `out/`, `tmp/`, the runtime state dirs, and
  devices. Runtime config files (settings, hooks, skills, plugins,
  `config.toml`, `AGENTS.md`) stay read-only, so a session cannot change
  how later sessions start.
- **Reads** are denied for `$HOME`, `/Users`, `/Volumes`, and the per-user
  temp area, except for the task folder, yt-core, the harness, and what the
  runtime needs. Other sessions' transcripts and history cannot be read.
- **Escape channels** are blocked: tmux sockets, AppleEvents, and running
  `open`, `osascript`, `launchctl`, `crontab`, `at`, `screen`, `ssh`, `tmux`.
- **Local services** are unreachable: unix-socket connections are denied except
  DNS (`mDNSResponder`), `syslog`, and the task `tmp/`. That closes Docker's API,
  ssh-agent, terminal-app daemons, and editor CLIs, each of which could act
  outside the sandbox.
- **Peer sessions** are unreachable: the Claude session registry
  (`~/.claude/sessions/`) and other sessions' messaging sockets (`cc-socks/`)
  are closed, so a sub-session cannot list or message the coordinator or any
  other local session. Its own socket lives in the task `tmp/`.

Outside the profile, every sub-session also starts:

- from a clean environment (an allowlist in `launch.session_env`, plus
  `envPassthrough` in `~/yt-local/config.json`), so no coordinator token,
  socket, or terminal-app variable leaks in;
- with user-level hooks off and with no MCP servers or connectors (Claude:
  `--strict-mcp-config`, `ENABLE_CLAUDEAI_MCP_SERVERS=false`; Codex:
  `features.apps=false` and every configured server disabled).

Network egress is open on purpose. Sub-sessions (and their subagents) must be
able to search and fetch the web, and the runtimes' web search runs on the
model provider's side, so a host allowlist proxy would add upkeep without
closing that path. What stays closed is everything that acts outside the
sandbox: local service sockets, peer sessions, escape programs, MCP connectors.

## Metrics

When a task is collected or forgotten, `yt` reads that runtime's own session log
and appends one line to `~/yt-local/data/metrics.jsonl`: tokens (input, cache read,
cache write, output), turns, tool calls, large tool outputs, file rereads,
compactions, subagents, and success. Numbers only, never content, in the same
shape for Claude and Codex (`ytlib/metrics.py`, parity in `tests/metrics/run.py`).
Main session only; subagent tokens are not counted on either side. A change is
an improvement only if success holds while tokens or turns drop.

## Global setup on each runtime

Each runtime also loads its own user-level setup into every sub-session:
`~/.claude/CLAUDE.md` (and `~/.claude/rules/`) for Claude, and
`~/.codex/AGENTS.md` (or `AGENTS.override.md`) for Codex. User-level hooks
and globally enabled plugins are loaded the same way. If the two sides
differ, the runtimes stop behaving the same, so yt-harness checks them
(`ytlib/parity.py`) and never edits them:

- the instruction text must be identical on both sides;
- the same plugins must be enabled globally (normally only `yt-core`);
- no runtime-only instruction settings (Codex `developer_instructions`, Claude `outputStyle`).

User-level hooks are not compared: every sub-session starts with them turned
off (`--settings '{"disableAllHooks": true}'` for Claude, `-c features.hooks=false`
for Codex), so hooks that other tools install (e.g. a terminal app) never run there.

`yt-setup --check` reports drift. `yt-spawn` and `yt resume` refuse to start
until it is fixed. The check is skipped when only one runtime is installed.

Inside a task, the work order says how the two layers combine. User-level
instructions still apply. Where they conflict with the work order, the work
order wins. `result.md` is written in the language of the brief.

## yt-guard (all sessions)

`yt-core` carries a PreToolUse hook (`hooks/hooks.json` → `bin/yt-guard`) that both
runtimes run before every tool call in normal and coordinator sessions. It blocks
infra writes, interactive database clients, reading secret files, and irreversible
remote git; rules are in `ytlib/guard.py`, cases in `tests/guard/run.py`.

- It only blocks (exit 2 with a reason). It never answers "allow", so existing
  user-level hooks and permission prompts behave exactly as before; if any hook
  blocks, the call is blocked.
- It never edits `~/.claude/settings.json` or `~/.codex/hooks.json`.
- The human lifts a category for one session with `YT_GUARD_ALLOW=infra,secrets`
  set before starting it. No file can turn the guard off, so an agent cannot either.
  Blocks are logged as metadata only (category, tool).
- Unreadable hook input or an internal error blocks (secrets fail closed); other
  parse failures let the command through.
- It is a best-effort guard on visible commands, not a sandbox: computed file
  names, shell aliases and functions, and arbitrary programs are out of its reach.
- Codex asks once to trust the plugin hook; `yt-doctor` notes it until then.
- Sub-sessions start with hooks off; the sandbox protects them instead.

## Repo guard

The repository holds the shared skeleton only. The hooks reject a commit or push when:

- a path is not in `allowlist.txt`, or is listed in `~/yt-local/blocked-paths.txt`;
- the file name is sensitive (`.env`, keys, credentials and similar);
- gitleaks finds a secret (built-in patterns are the fallback);
- the content has a personal home path or a term from `~/yt-local/blocked-terms.txt`;
- the author or committer email is not a GitHub noreply address.

Merges, file type changes, and new branches are checked too. Review the diff
yourself before every push.

## Adding a harness

`yt harness new <name> "<purpose>"` does steps 1 to 3; by hand:

1. Copy `templates/harness.yaml` into `<name>/harness.yaml` and set `id: <name>`.
   Set `purpose` and `description`.
2. Add `skills/`, then run `yt-core/bin/yt-build`. It generates both plugin
   manifests and both marketplace entries. Never edit those JSON files by hand;
   the pre-commit hook rejects them when they drift from the sources.
3. Add the folder to `allowlist.txt`.
4. Rerun `yt-core/bin/yt-setup` so Codex installs it.

## Tests

```sh
tests/repo-guard/run.sh      # repo guard accept/reject cases
python3 tests/sandbox/run.py # sandbox allow/deny cases for both runtimes (macOS; Linux via linux.py)
python3 tests/lab/run.py             # roadmap frameworks: improve, eval, candidates, cards, panel
python3 tests/transfer/run.py        # yt-export / yt-import: packing, merging, rejection
tests/mods/run.sh                    # interface mods: their own tests and plugin validate
python3 tests/metrics/run.py         # same session as Claude and Codex logs -> same metrics
python3 tests/guard/run.py           # yt-guard decisions, Claude- and Codex-shaped events
python3 tests/contract/run.py         # same scenarios on Claude and Codex, fake runner, no model
python3 tests/contract/run.py --live  # plus one real task on both runtimes (model calls)
tests/instructions/run.sh    # instruction files stay under 200 lines
```

## Rules for contributors

See `AGENTS.md`. Everything is in English. Instruction files stay under 200
lines. Runtime-specific files are generated by `yt-build` from the neutral
sources (`harness.yaml`, `yt-core/plugin.yaml`).

## Contributors

- **parkyountaek**: owner. Design, decisions, and review of every change before it is pushed.
- **Claude Code** (Anthropic): implementation, tests, and documentation, as co-author of the commits.
- **Codex** (OpenAI): independent reviews, the runtime-equivalence runs, and the rule hardening in yt-guard.

## License

MIT, see `LICENSE`.
