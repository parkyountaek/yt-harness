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
| `yt-core/lib/ytlib/runners/` | Runner adapters (`tmux` now; Orca later) |
| `yt-ops/` | First harness: read-only investigation |
| `templates/harness.yaml` | Starting point for a new harness |
| `.githooks/` | Repo guard (pre-commit and pre-push) |
| `tests/` | Repo guard, sandbox, and instruction-length tests |
| `.claude-plugin/`, `.agents/plugins/` | Marketplaces for Claude and Codex |

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
```

`yt-setup` is safe to rerun. It:

1. Installs missing tools from `yt-core/deps.json` with the OS package manager.
   Each tool has a minimum version. Required: python3, git, gh, tmux, gitleaks,
   and the sandbox backend. Claude and Codex use their official installers.
2. Enables the repo git hooks (`core.hooksPath = .githooks`).
3. Creates `~/yt-local/` and records the checkout path.
4. Links yt-core for Claude (`CLAUDE_CODE_PLUGIN_DIRS`). For Codex it adds the
   marketplace, installs yt-core enabled, and installs every harness disabled.

It warns when tools have not been upgraded for 7 days. `--upgrade` reruns the
repo guard tests afterwards, so a gitleaks update that changes behaviour is
caught before the next commit.

### Platforms

| Platform | Packages | Sub-sessions |
|---|---|---|
| macOS | Homebrew | Yes: `sandbox-exec` |
| Linux, WSL2 | apt or dnf | Not yet: the bubblewrap backend is a stub |
| Windows | winget or Scoop | No: setup and commits work. Run sub-sessions inside WSL2 |

Linux and Windows have not been verified on real machines yet.

## Usage

The commands live in `yt-core/bin/`. Add it to `PATH` (setup does not change
your shell profile):

```sh
export PATH="$PWD/yt-core/bin:$PATH"
mkdir -p ~/yt-work/read-001/in
$EDITOR ~/yt-work/read-001/in/BRIEF.md      # goal, constraints, done criteria
yt-spawn read-001 yt-ops --runtime codex --deadline 30m
yt status
yt attach read-001                          # when the state is waiting-human
yt stop read-001
yt resume read-001 --deadline 1h
yt forget read-001                          # drop a finished task from the list
```

`yt-spawn` refuses an id that is already registered, and refuses an `out/`
that is not empty. The result is in `~/yt-work/<id>/out/result.md`.

Inside a sub-session the only state command is `yt-status`:

```sh
yt-status running
yt-status waiting-human --question "Which branch should I compare?"
yt-status done                     # out/result.md must exist
yt-status failed --reason "Input file is missing"
```

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

1. Copy `templates/harness.yaml` into `<name>/harness.yaml` and set `id: <name>`.
2. Add `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, and `skills/`.
3. Register it in both marketplaces and in `allowlist.txt`.
4. Rerun `yt-core/bin/yt-setup` so Codex installs it.

## Tests

```sh
tests/repo-guard/run.sh      # repo guard accept/reject cases
python3 tests/sandbox/run.py # sandbox allow/deny cases for both runtimes (macOS)
tests/instructions/run.sh    # instruction files stay under 200 lines
```

## Rules for contributors

See `AGENTS.md`. Everything is in English. Instruction files stay under 200
lines. Runtime-specific files will be generated by `yt-build` from the neutral
sources; `yt-build` is not written yet.
