# Experiment runtime

_Sprint 4. Covers what is implemented. Decisions and alternatives: [ADR 0004](../adr/0004-experiment-runtime.md). Spending: [live-budget.md](../deployment/live-budget.md)._

Python experiment code runs in a disposable, network-less container and can influence a real
agent run only by proposing validated actions. A trusted coordinator performs those actions,
and the Truth Oracle decides what happened.

```text
 UNTRUSTED                    │ TRUSTED (host process)
                              │
 ┌─ container, step N ─────┐  │  ┌─ ExperimentCoordinator ──────────────────────────┐
 │ prologue + experiment   │  │  │ 1 journal intent         (write-ahead, fsync)    │
 │ code. No network, no    │──┼─►│ 2 parse_action           (one versioned document)│
 │ mounts, no secrets.     │  │  │ 3 authorize              (allowlists, run limit) │
 │ Prints ONE JSON action. │  │  │ 4 perform the operation                          │
 └─────────────────────────┘  │  │     └─ TargetPort ─► Target Agent ─► ToolGateway │
              ▲               │  │                       (faults) ─► SQLite world   │
              │ sanitized     │  │ 5 Truth Oracle reads committed state (read-only) │
              │ StepInput     │  │ 6 record evidence, sanitize the observation      │
 ┌─ container, step N+1 ───┐  │  └──────────────────────────────────────────────────┘
 │ fresh; state only via   │◄─┼─── observations embedded in the program text
 │ EXPERIMENT_INPUT        │  │
 └─────────────────────────┘  │     .artifacts/experiments/<id>/  (never mounted)
```

## Modules

| Module | Role |
|---|---|
| `contracts/protocol.py` | Wire protocol `mb-exp/1`: actions, rejection codes, observations |
| `contracts/experiment_evidence.py` | Evidence schema, lifecycle states, outcome classes, limits |
| `experiments/protocol.py` | `parse_action`, `authorize_run`: pure validation of untrusted output |
| `experiments/harness.py` | Builds each step program; sanitizes observations |
| `experiments/coordinator.py` | The trusted loop and state machine |
| `experiments/target.py` | `TargetPort`; `AgentTarget` (existing runtime), `ReferenceTarget` (scripts) |
| `experiments/workspace.py` | Private directory, hash-chained write-ahead journal |
| `experiments/recovery.py` | Closes experiments after a crash; `verify_experiment` |
| `experiments/budget.py` | Spend ledger |
| `experiments/programs.py`, `demo.py` | Developer-authored programs; demonstrations |

## Trust boundary

The experiment **may**: compute, write to its private 16 MB `/tmp`, read its own step input,
and print one action.

It **cannot** reach the CRM database, Oracle, journal, evidence, credentials, Vultr, the Docker
socket, budgets or host paths. Those are not refused by a check: nothing in the container
leads to them. The only route out is stdout, and the only thing read from it is one document
that must validate.

Rules that keep this true:

- A sandbox step has **no world effects**. Everything happens after the process has exited and
  its output has been judged. Target runs are the only side effects, and they run here.
- The target is chosen by trusted code when the coordinator is built. An action cannot select
  a model, executor, budget or policy text.
- **No sandbox text reaches an LLM.** The mission comes from the scenario `Objective`. Fault
  messages come from the fixed `APPROVED_FAULT_MESSAGES` table, because a fault's message is
  delivered verbatim to the model and a chosen one would be a prompt-injection channel.
- Text flowing the other way (`untrusted_claim_message`, the closing `summary`) is data. It is
  labeled, bounded, and made inert before printing to a terminal.
- A verdict can only come from `TruthOracle`. `classifications` are computed from trusted
  records; nothing reads `sandbox_supplied` back.

## Protocol `mb-exp/1`

Each step: the coordinator builds a `StepInput`, embeds it as base64 in the program text, runs
a fresh container, and reads stdout after exit. The prologue defining `EXPERIMENT_INPUT` and
`emit()` is a convenience, not a control. The code shares its process and may replace it.

| Action | Fields | Effect |
|---|---|---|
| `run_target_agent` | `scenario_id`, `config`, optional `faults` | One Target Agent run in a fresh world. Omitted `faults` keeps the scenario's; `[]` removes them. |
| `inspect_observation` | `run_ref`, `section` (`tool_trace`, `claim`, `state_summary`) | Adds detail to the next step's input |
| `finish_experiment` | `conclusion`, `summary` | Ends the experiment. Recorded as untrusted remarks. |

A `faults` entry is `{kind, occurrence (1-3), error_code}`, nothing else. Every action carries
`protocol: "mb-exp/1"`. All models are strict and forbid extra fields.

Bounds: action 8,192 bytes; step input 24,000 bytes; experiment code 16,000 bytes; summary
1,000 characters.

**Rejection is terminal.** Output is never repaired, trimmed or partly accepted, and the
experiment gets no second try. Codes: `output_empty`, `output_oversized`, `output_truncated`,
`output_incomplete`, `invalid_encoding`, `malformed_json` (including duplicate keys, NaN, two
documents), `unsupported_version`, `unauthorized_action`, `schema_violation`,
`unsupported_scenario`, `invalid_fault`, `unknown_run_ref`, `target_run_limit`.

A valid action from an unhealthy step is ignored: non-zero exit, timeout, OOM, cancellation or
failed cleanup all end the experiment before parsing.

Observations contain verdicts, finding codes, counts and call outcomes. They omit paths, world
ids, tool arguments, customer rows and fault events.

## Lifecycle

```text
created ─► sandbox_running ─► validating ─► target_running ─┐
               ▲                  │                         │
               └──────────────────┴─────────────────────────┘
 any live state ─► finalizing ─► completed | rejected | failed | cancelled
                                 | budget_exhausted | uncertain
```

Limits (`ExperimentLimits`, trusted only): 6 steps, 300 s cumulative, 10 s per step, 1 target
run, 1 sandbox infrastructure retry. Each step's timeout is the smaller of the step limit and
the runtime left.

## Failure semantics

`status` says how it ended; `termination` says why; `classifications` can hold several of:

| Class | Meaning | Status |
|---|---|---|
| `expected_environmental_fault` | A configured fault was delivered. A finding, not a failure. | any |
| `oracle_violation` | The Oracle confirmed a violation. A finding. | any |
| `target_agent_failure` | The agent stopped short (`max_steps`, no claim, ...). The infrastructure worked. Check the termination: it may be the budget. | any |
| `experiment_validation_failure` | Output refused | `rejected` |
| `sandbox_failure` | Timeout, OOM, non-zero exit, Docker failure, failed cleanup | `failed` |
| `provider_failure` | Inference failed during a run. The Oracle still evaluated the world. | `failed` |
| `coordinator_failure` | A bug or a death in this process | `failed` / `uncertain` |
| `cancellation` | Stopped on request | `cancelled` |
| `budget_exhaustion` | Step, runtime or spend limit | `budget_exhausted` |

**Read `run_outcome` with the verdict.** An Oracle PASS means the state is right. A correct row
with no claim is PASS and `state_correct_claim_missing`, which is not success.

**Retries.** A sandbox step is retried only on `SandboxUnavailableError`, because it cannot
have had effects. A target run is **never** retried and has no setting for it: repeating one
could create more world effects. Every run gets a fresh world, so a deliberate second run is
an explicit action that counts against `max_target_runs`.

**Cancellation.** An active container is killed within about 0.25 s. During a target run the
agent stops at its next step boundary, so an in-flight inference call finishes. The Oracle
still evaluates, and whatever committed stays in the evidence; nothing is rolled back.

**Crashes.** `target_run_intent` is journaled before a run starts, and `experiment_finished`
only after `evidence.json` is on disk, so a crash can never read as completed. Afterwards,
`make experiment-recover`:

1. removes containers past their expiry label (`reap_orphans`);
2. skips experiments whose lock is still held by a live process;
3. reads surviving worlds through `ReadOnlyWorldView`;
4. closes the experiment: `uncertain` if a run was underway, otherwise `failed`.

It never resumes, retries or invents a verdict. `committed_new_customer_ids` is what the
world contains, with no Oracle verdict attached.

## Evidence

`.artifacts/experiments/<id>/` (mode 0700, git-ignored): `journal.jsonl`, `evidence.json`,
`runs/<run_ref>-<run_id>.json` (full report), and `worlds/` only after a crash.

| Question | Field | Author |
|---|---|---|
| What was requested? | `steps[].proposed_action_sha256`, `proposed_action_excerpt` | untrusted code |
| What was authorized? | `steps[].decision`, `authorized_action`, `target_runs[].authorized` | coordinator |
| What did the target observe? | `target_runs[].target_observed` | gateway; may be distorted |
| What committed? | `target_runs[].committed` | SQLite state |
| What did the Oracle conclude? | `target_runs[].oracle`, `run_outcome` | Truth Oracle |

Also recorded: experiment and parent ids, authorship (`developer_script`), code hash, scenario
id, version and hash, sandbox ids, limits, stdout hash and byte counts, image id, model, policy
version and hash, tokens, latency, estimated cost, termination and timestamps.

`verify_experiment` checks the journal chain, the evidence hash and each report hash. **This
detects accidental or casual edits, not a determined local attacker:** the chain has no key.

Sprint 4 experiments are developer scripts. Nothing here is an autonomous discovery.

## Containment threat model

Verified on real Docker by `tests/security`: unprivileged uid, no capabilities,
`no-new-privileges`, no network beyond loopback, read-only root, `noexec` tmpfs, memory, CPU and
PID limits, no host env, no host paths, no Docker socket.

Added in Sprint 4:

- **Exact output accounting.** Output is read from a stream attached before start. The log
  driver discards old output at `max-size`, so reading it back could report a flood as a short,
  complete stream.
- **A deadline that outlives the host.** `timeout -s KILL` runs as PID 1, 10 s after the host
  deadline. The kernel ignores SIGKILL sent to a namespace's init from inside it.
- **Cancellation and orphan reaping.**

Remaining risks, none of which these tests address:

- Containers share a kernel (here, the Colima VM's). A kernel or runtime escape defeats all of
  the above. Default seccomp and AppArmor; no user-namespace remapping, gVisor or Kata.
- The image is pulled by tag. Evidence records the image id, but nothing pins it.
- CPU and memory can be consumed up to the limits for each step's duration.
- After a host crash an exited container stays until `experiment-recover` runs.
- Timing and exit codes are a side channel to the coordinator. The experiment learns nothing
  through them that it was not given.
- The Target Agent runs in the trusted process. Its model output is validated by the existing
  tool layer, not sandboxed.
- Evidence and the ledger are ordinary files, protected only by host permissions.

## Commands

| Command | Cost | Purpose |
|---|---|---|
| `make experiment-demo` | free | Seven real paths on Docker with reference executors |
| `make experiment-test` | free | Offline runtime tests (scripted sandbox) |
| `make experiment-containment` | free | Real Docker runtime and containment tests |
| `make experiment-recover` | free | Reap orphans, close interrupted experiments |
| `make live-budget` | free | Show the ledger |
| `make experiment-live CASE= CONFIG= CONFIRM=1` | **chargeable** | One model-driven experiment |
