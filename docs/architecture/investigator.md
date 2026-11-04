# Investigator

_Sprint 5. Covers what is implemented. Decisions: [ADR 0005](../adr/0005-autonomous-investigator.md).
Measurement: [methodology](../evaluations/methodology.md)._

One model inside a deterministic workflow. **Reasoning is agentic; execution authority is not.**

```text
 MODEL (untrusted reasoning)      │ TRUSTED WORKFLOW
 hypothesis + Python program ─────┼─► validate (schema, references, size, limits)
                                  │     │ journal, reserve spend
 prompt rebuilt from typed state  │     ▼
 ◄── sanitized observation ───────┼── ExperimentCoordinator ─► sandbox ─► Target ─► Oracle
                                  │     │ evidence
 claims (interpretation) ─────────┼─► findings: from Oracle reports only; reproduce in fresh world
```

## Modules (`backend/moody_blues/investigator/`)

| Module | Role |
|---|---|
| `contracts/investigation.py` | Hypotheses, proposals, observations, findings, report |
| `catalog.py` | World tiers, and what may be known about the target |
| `context.py` | Builds the prompt from typed state |
| `model.py` | Budgeted model calls, flat tool schema, strict parsing |
| `observations.py` | Evidence to observation; result classes; diagnostics |
| `workflow.py` | State machine; adaptive, one-shot and fixed strategies |
| `findings.py` | Classification, reproduction, claim checks |
| `workspace.py` | Journal, sources, verification, lock, recovery |
| `preflight.py` | Generated-code safety checks on real Docker |
| `evaluation.py` | Paired counterfactual and strategy comparison |
| `fixtures.py` | Labeled offline stand-ins for the model |

## Lifecycle

```text
created ─► planning ─► experimenting ─► evaluating ─► revising ─► experimenting ...
any live state ─► completed | failed | cancelled | budget_exhausted | inconclusive
```

Default limits (`InvestigationLimits`, trusted only): 3 experiments, 1 target run each, 5 model
calls, 8,192 completion tokens, `reasoning_effort` low, 1 refinement, 1 reproduction, 900 s. One
investigation runs at a time (a file lock refuses a second). When experiments run out, only
`conclude_investigation` is offered.

## What the model sees and does not see

| Sees | Never sees |
|---|---|
| Mission, tool contracts, operating expectations | Oracle code, verdict logic, policy prompts |
| Permitted faults and the protocol | Worlds' built-in faults, seed rows, objective attributes |
| World ids and seed counts | Paths, database files, credentials, scenario descriptions |
| Structured results of its own experiments | Target claim text, sandbox summaries, stderr text, other investigations |

Every field group carries a provenance: `oracle` establishes truth; `coordinator` records what ran;
`gateway_delivered` is what the target was told, possibly distorted; `target_reported` and
`sandbox_reported` are assertions.

## Result classes

Each experiment gets one class from trusted records: `invalid_python`, `invalid_protocol_output`,
`unauthorized_action`, `sandbox_runtime_failure`, `no_target_run`, `infrastructure_failure`,
`provider_failure`, `target_agent_shortfall`, `oracle_confirmed_violation`, `no_violation_found`,
`uncertain_side_effects`, `budget_exhausted`, `cancelled`.

A replacement proposal is allowed only after `invalid_python`, `invalid_protocol_output`,
`sandbox_runtime_failure` or `no_target_run`, and only if no target ran. `unauthorized_action` gets
none. After `uncertain_side_effects` the investigation ends and nothing repeats.

## Findings

| Class | Meaning |
|---|---|
| `oracle_confirmed_violation` | Oracle VIOLATION, run finished, evidence verifies |
| `impaired_violation` | Oracle VIOLATION, but the run or its evidence was impaired |
| `impaired_run` | No violation; cut off by a provider, cancellation or our token limit. Says nothing about the agent |
| `target_shortfall` | No violation; the agent did not finish properly |
| `correct_recovery` | Faults delivered and the run succeeded |
| `clean_success` | No fault delivered and the run succeeded |

**Read three fields together:** the class, `fault_attributable` (did any fault reach the target?)
and `reproduction` (`reproduced`, `not_reproduced`, `untested`, `not_applicable`). A rerun under
different conditions is `untested`. The model's conclusion is checked by `claim_checks` and can
neither add nor remove a finding. With no confirmed violation the report says: "No verified
violation discovered within the tested scenarios and budget."

## Evidence

`.artifacts/investigations/<id>/` (mode 0700): `journal.jsonl`, `state.json`, `report.json`,
`sources/` (every executed program), `calls/` (exact prompts and responses, including rejected
output). Experiments stay under `.artifacts/experiments/`, so existing recovery applies, and are
linked by id and evidence hash. `verify_investigation` checks all of it. As with experiments, this
detects casual edits, not a determined local attacker.

## Threat model additions

Verified on real Docker by `tests/security/test_generated_code.py` and `make investigator-preflight`:
pinned digest, unprivileged uid, no capabilities, no new privileges, seccomp filter, read-only root,
noexec `/tmp`, loopback only, no socket, no host paths, no credentials in the environment, memory and
PID limits, fail-closed output.

Remaining risks:

- **Shared kernel.** Only `runc` is available; `runsc` (gVisor) is not installed in the Colima VM. A
  kernel or runtime escape defeats everything above. Generated code is confined to `mb-exp/1`.
- **Image provenance** is a digest pin of the official `python:3.12-slim`. The digest resolves on
  the registry as a multi-architecture index. No signature is verified.
- **The model's own prose** returns to it in later prompts. It derives only from sanitized
  observations, but it is unverified interpretation.
- **Persuasive conclusions.** Claim checks test codes, not causal stories. `fault_attributable`
  catches one such story; others can pass, so violation traces must be read by a person.
- The Target Agent still runs in the trusted process, and evidence is protected only by host
  permissions.

## Commands

| Command | Cost | Purpose |
|---|---|---|
| `make investigator-preflight` | free | Verify the generated-code path on this host |
| `make investigator-demo` | free | Fixture model, real sandboxes, worlds and Oracle |
| `make investigator-test` | free | Offline tests |
| `make investigator-containment` | free | Hostile programs on real Docker |
| `make investigator-live CONFIRM=1` | **chargeable** | One investigation (`TIER=`, `STRATEGY=`) |
| `make investigator-eval CONFIRM=1` | **chargeable** | Pairs and comparison (`TIER=`, `PART=`, `EVAL_TRIALS=`, `REPEATS=`) |
| `make investigator-repro EXPERIMENT= CONFIRM=1` | **chargeable** | Rerun one generated program unchanged (`RUNS=`, at most 8) |
