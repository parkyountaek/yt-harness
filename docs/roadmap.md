# Roadmap frameworks

Each roadmap item has a place, a data contract, and the deterministic part as a
command. The judgement (what to change, what to adopt) stays with the human. Data
under `~/yt-local/data/` is numbers, ids, and enumerations only; task content never
goes there, so it may leave the machine after a human check.

| Item | Framework | Status |
|---|---|---|
| Harness generation | `yt harness new`, `yt harness candidates` | ready |
| Run evaluation | `yt eval`, `evals.jsonl` | ready |
| Self-improvement | `yt improve` | report ready; proposals manual |
| Experiments | `experimental: true`, `yt-spawn --experimental`, `yt card` | ready |
| Knowledge store (`yt-wiki`) | contract below | not started |
| Control panel and retirement | contract below | not started |

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
harness's `evals:` list in `harness.yaml` (scripts that print pass or fail); they
are not run automatically yet.

## Self-improvement

`yt improve <harness>` groups `metrics.jsonl` by harness version. An eval verdict
overrides the final state. It compares the last two versions:

- **worse:** success dropped. This always wins over savings.
- **better:** success held, and tokens or turns dropped.
- **no gain:** success held, but neither dropped.
- **unclear:** fewer than 3 tasks on either version.

Next step, not built: a `yt-improve` loop (collect → diagnose → propose → regression
→ apply) that writes proposals only. Enforcement layers (sandbox, guards, tests,
eval criteria) are never changed by it.

## Experiments

- A harness with `experimental: true` starts only with `yt-spawn --experimental`.
  An experimental harness is adopted by setting `experimental: false` once it passes
  the contract tests and its evals.
- `yt card <task-id>` prints a case card. It holds the harness, version, runtime,
  final state, input file kinds by extension, human answers, resumes, steps, turns,
  tokens, and the eval verdict. It holds no names, values, or text. A human checks
  the card before it leaves the machine. Synthetic regression cases are built from
  cards on another machine.

## Knowledge store (`yt-wiki`), not started

Contract: a harness with `folderKind: vault`. The sandbox writes only inside the
vault, and capture and ask procedures are skills. Only generic parts move into the
skeleton: the write guard, masking checks, and the capture and ask frames. Notes,
rule files, and operating commands stay where they are.

## Control panel and retirement, not started

Contract: a status view over `yt status`, `yt metrics`, and `yt improve` output. It
also flags retirement when a harness has no tasks for 60 days. A panel is a
runtime UI feature, so it must stay optional. Every action stays available as a
`yt` command, so Claude and Codex keep the same behaviour.
