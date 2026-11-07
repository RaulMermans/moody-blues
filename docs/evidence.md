# Oracle and evidence

The Oracle is why a result here can be believed. This page explains what it says, what is written down, and how to check it.

## Verdicts

| Verdict | Means | Does not mean |
|---|---|---|
| `PASS` | The objective is met in committed state, no invariant is broken, and any claim agrees | The agent is correct in general. One run is one sample |
| `VIOLATION` | At least one invariant is broken in committed state | The fault caused it. A delivered fault is exposure, not proof |
| `INCONCLUSIVE` | Neither could be established | A soft pass or a soft failure |

Verdicts come only from the Oracle, which reads committed state through a read-only view. It never reads what the agent
was told, fault events, or the agent's word. What the agent claimed is checked against state, never believed.

**Validity is separate from the verdict.** A run can be valid or not, whatever its verdict: if a selected fault never
fired, that run is no evidence for or against a hypothesis about that fault, and the record says so. `run_outcome` adds
how the run ended. Read them together.

**What the labels say about the target.** A *reference script* and an *external scripted agent* are deterministic code. A
*fixture-driven* run used a labeled stand-in for a model. Only an evidence source of `live_provider` (hosted inference) or
`local_ollama` (local inference) means a real model answered. A *recorded investigation* is a real past run, exported and
hash-pinned. Scripted and fixture results never describe model behavior.

## What is on disk

```text
<artifacts>/
  investigations/<inv_id>/
    journal.jsonl       hash-chained, written ahead of each effect
    report.json         the investigation's report, hashed in the journal
    calls/              what the Investigator's model was sent and answered
    sources/            each generated experiment program
  experiments/<exp_id>/
    journal.jsonl       hash-chained
    evidence.json       every target run: trace, committed state, Oracle report, provenance
    runs/*.json         the full run report, hashed in evidence.json
    source.py           the program that ran
  live-jobs/<job_id>/
    job.json, bundle.json   what the pages read, with the bundle's hash
```

For one run in `evidence.json`: `target_observed.tool_trace` is what the tools reported, `committed` is what is true,
`target_observed.claim` is what the agent said, and `oracle` holds `verdict`, `invariants_violated` and `findings`.

## Checking evidence

```sh
make evidence-verify            # .moody-local, or MOODY_ARTIFACTS_DIR
make evidence-verify DIR=path
```

| Check | Fails when |
|---|---|
| journal and hashes | A journal chain breaks, or a report, source, model call or linked evidence file differs from its hash |
| run report | A report on disk disagrees with the evidence about its run, Oracle report or world |
| tool calls | Calls are misnumbered, a fault count is wrong, a tool was not offered or granted, or accepted calls differ from traced ones |
| model calls | A script claims model calls, or a call count differs from its records |
| world identity | The records of one run name different worlds or scenarios |
| oracle findings | A verdict does not follow from its own findings, or an invariant is violated without a finding |
| published bundle | A bundle differs from the hash in its job record |

Exit code 0 means intact, 1 means a problem was found, and 2 means nothing was checked. It writes nothing and takes no
lock, and it reads evidence from every schema version, including records older than the world provenance fields.

**What it cannot show.** Nothing is signed, so someone who rewrites a record and every hash above it is not detected. A
world is removed when its experiment closes, so state is not read again: the verdict is checked against its findings, not
recomputed. To test a result again, run it again.

`make recorded-verify` does the same job for the five investigations committed in `evidence/recorded/`.

## Where state lives

| What | Where | Rule |
|---|---|---|
| Active run state | A world's SQLite file, and the lock, under the artifacts directory | Removed when its experiment closes |
| Temporary artifacts | `.moody-local/` by default for `make` commands, or a printed scratch directory when a command is run directly | Disposable. `make clean-local` removes `.moody-local` |
| Recorded evidence | `evidence/recorded/`, `evidence/live/`, `evidence/containment/` | Committed and hash-pinned. Never hand-edited |
| Evaluation snapshots | `evidence/benchmark/`, `docs/evaluations/` | Frozen. A correction is a new revision |
| Spend ledger | `live-spend/` in the artifacts directory it was created in | Maintainers only. Never reset or edited. Free commands never touch it |
| Deployment state | `.artifacts/vultr-state.json` | Maintainers only. Git-ignored |
| Logs | Your terminal; `*.log` is git-ignored | Never hold secrets |

Free demonstration and test commands never write to `.artifacts/`, which is where a maintainer's paid runs and ledger live.
Only paid commands and deliberate maintainer operations do: `experiment-recover`, `recorded-export` and the live smoke
commands. You never need those for local work. `make dev` reads
`.moody-local` unless you set `MOODY_ARTIFACTS_DIR`, and with that default, live runs are forced off, because a ledger
belongs to its directory and an empty one must not become a fresh budget.
