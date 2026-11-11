# Roadmap frameworks

Each roadmap item has a place, a data contract, and the deterministic part as a
command. The judgement (what to change, what to adopt) stays with the human. Data
under `~/yt-local/data/` is numbers, ids, and enumerations only; task content never
goes there, so it may leave the machine after a human check.

| Item | Framework | Status |
|---|---|---|
| Harness generation | `yt harness new`, `yt harness candidates` | ready |
| Run evaluation | `yt eval`, `evals.jsonl` | ready |
| Self-improvement | `yt improve`, `yt improve --propose`, `yt-improve` harness | ready (proposals only) |
| Experiments | `experimental: true`, `yt-spawn --experimental`, `yt card` | ready |
| Knowledge store (`yt-wiki`) | `folderKind: vault`, `yt-wiki` harness, `yt-mask` | ready |
| Control panel and retirement | `yt panel`, `panel` skill | ready |

## Harness generation

- A task kind with no route is logged (`route-miss`) when `yt route <kind>` finds
  nothing. `yt harness candidates` lists kinds that came up twice or more.
- `yt harness new <name> "<purpose>"` copies `templates/harness.yaml`, adds a
  procedure skill stub, runs `yt-build`, and adds the folder to `allowlist.txt`.
  New harnesses start `experimental: true`.
- The human fills in the skill and the sandbox paths, adds a route in
  `~/yt-local/routes.json`, and runs `yt-setup` so Codex installs it.

## Run evaluation

`yt eval <task-id> pass|fail [--judge human|model|deterministic] [--fixed]` appends
to `~/yt-local/data/evals.jsonl`:

```json
{"taskId": "...", "harness": "...", "harnessVersion": "...", "runtime": "...",
 "verdict": "pass", "judge": "human", "humanFixed": false}
```

The last verdict per task wins. `--fixed` marks that the human had to correct the
result. Free-text notes are refused on purpose. Deterministic checks belong in a
harness's `evals:` list in `harness.yaml`: paths inside the harness folder, such as
`evals: ["evals/has-title.py"]`. `yt collect` runs them once the result meets the
contract. Each gets the task folder as its argument, runs in `out/` with a minimal
environment and a 60-second limit, and prints `pass` or `fail` on its last line. Any
fail records `fail`, all pass records `pass` (judge `deterministic`); an error (a
crash, no verdict, a path outside the harness) records nothing. A later `yt eval`
replaces it. Only the verdict is kept, never the script's output.

Every shipped harness has `evals/result.py`, built on `ytlib/evalkit.py`: the task
reported `done`, `result.md` is not empty and has nothing `yt-mask` would mask, and
it shows the harness's own mark (a commit for `yt-code`, a note path for `yt-wiki`,
how to judge it with `yt improve` for `yt-improve`).

## Self-improvement

`yt improve <harness>` groups `metrics.jsonl` by harness version. An eval verdict
overrides the final state. It compares the last two versions:

- **worse:** success dropped. This always wins over savings.
- **better:** success held, and tokens or turns dropped.
- **no gain:** success held, but neither dropped.
- **unclear:** fewer than 3 tasks on either version.

`yt improve <harness> --propose [--runtime claude|codex]` runs the loop as far as a
proposal:

1. **Collect:** the brief holds the version table, eval verdict counts, and case cards
   of failed or human-fixed tasks. Numbers and shapes only; no task content.
2. **Diagnose and propose:** a `yt-improve` sub-session works on a private clone of this
   checkout (folderKind worktree). It names the signal it acts on and makes the smallest
   skill change with a patch version bump, or concludes that none is justified.
3. **Scope:** the branch may change only `<harness>/skills/` and the `version:` line of
   `<harness>/harness.yaml`. `yt collect` lists anything else and `yt bring` refuses it,
   so enforcement layers (sandbox, guards, tests, eval criteria) and other harnesses are
   never part of a proposal.
4. **Apply:** the human runs `yt bring <task>`, reviews the branch, merges it, and pushes
   through the repo guard. The new version then earns its verdict in `yt improve`.

Verified live on both runtimes: with 8 tasks at 100% and one version, both concluded
that no change was justified and committed nothing.

## Experiments

- A harness with `experimental: true` starts only with `yt-spawn --experimental`.
  An experimental harness is adopted by setting `experimental: false` once it passes
  the contract tests and its evals, and by listing in `runtimes:` each runtime its
  evals passed on in a live run. Once `runtimes:` is set, `yt-spawn` refuses any other
  runtime without `--experimental`.
- Adopted 2026-11-10: `yt-ops`, `yt-code`, `yt-wiki`, and `yt-improve` passed their
  evals in live runs on Claude and on Codex (`runtimes: [claude, codex]`). Both
  runtimes produced the same `yt-code` change.
- `yt card <task-id>` prints a case card. It holds the harness, version, runtime,
  final state, input file kinds by extension, human answers, resumes, steps, turns,
  tokens, and the eval verdict. It holds no names, values, or text. A human checks
  the card before it leaves the machine. Synthetic regression cases are built from
  cards on another machine.

## Knowledge store (`yt-wiki`)

- `folderKind: vault` harnesses take `yt-spawn --vault <name>`. The name is looked
  up in `vaults` in `~/yt-local/config.json`, and the path is kept in the session
  list, so `yt resume` uses the same vault. The sandbox policy uses `<vault>`.
- The `yt-wiki` harness has two skills. `capture` writes notes the vault's own way
  and updates an existing note before adding a duplicate. `ask` answers only from
  the notes and cites them. Both start with `yt-vault`, which detects the kind
  (Obsidian, Logseq, Dendron, MkDocs, Docusaurus, plain) and its conventions from the
  vault's files; the vault's own rule files win.
- A git vault is cloned like a `worktree` repository: notes are committed on
  `yt/<task id>` and reach the vault only through `yt bring`.
- `yt-mask` is the masking check. It covers the repo guard's secret patterns,
  personal data, and the local blocked terms. It reports the kind and line only,
  and `--fix` masks in place.
- Only generic parts live here. Notes, rule files, and operating commands stay in
  the vault itself.
- Verified live on both runtimes: capture with masking, and ask with sources and an
  unchanged vault. Its evals pass on both runtimes, so it is adopted.

## Control panel and retirement

`yt panel` is one text view built from the coordinator's data. Its sections:
**Needs you** (questions, past deadlines, results not collected, runs that ended
without reporting), **Running**, **Harnesses** (version, on or off, last used,
30-day tasks and success), **Retire?** (no use for 60 days), **Harness
candidates**, and **Health** (`yt-doctor`). The `panel` skill runs it when the
human asks for the overview. A graphical panel would be a runtime-only UI, so it is
left out; every action stays a `yt` command, so Claude and Codex behave the same.
