# Target Agent

_Sprint 3 (2026-11-03). Describes implemented behavior only._

The Target Agent is one LLM-driven CRM Operations Agent. Its mission is: *create exactly
one customer with the specified attributes and verify that it exists*. The model decides
which tools to call and when to stop. Everything around the model is deterministic code.

It is the system **under test**. It is not the MOODY BLUES Investigator (Sprint 5) and has
no adversarial role.

## Data flow

```text
 Scenario ──► World (SQLite) ──► ToolGateway (faults) ◄─── ToolPort ───┐
    │                                                                  │ validated calls only
    └─ Objective ─► policies.mission_prompt ─► TargetAgent loop ◄──────┤
                                                 │   ▲                 │
                         InferenceRequest (full  │   │ InferenceResult │
                         conversation + tools)   ▼   │                 │
                                          VultrInferenceClient ──► api.vultrinference.com/v1
 claim ──► World.record_claim ──► TruthOracle (ReadOnlyWorldView) ──► AgentRunReport
```

## Modules

| Module | Owns |
|---|---|
| `contracts/inference.py` | `ChatMessage`, `AssistantToolCallMessage`, `ToolResultMessage`, `ConversationMessage`, `validate_tool_protocol` |
| `inference/vultr.py` | `to_wire_message` (OpenAI wire shapes) and response parsing that keeps tool-call ids |
| `contracts/agent.py` | `AgentBudget`, `TerminationReason`, `ToolCallRecord`, `AgentTrajectory`, `RunAssessment`, `AgentRunReport` |
| `agents/policies.py` | Baseline and hardened system prompts, the mission prompt, the claim reminder |
| `agents/tooling.py` | Tool allowlist, argument validation, the `submit_final_claim` tool |
| `agents/target.py` | `TargetAgent`: the bounded loop |
| `services/agent_world_runner.py` | Scenario → World → agent → claim → Oracle → `AgentRunReport` + `RunAssessment` |
| `services/agent_eval.py` | Scenarios × configs × trials, budgets, summaries, Oracle cross-check |
| `services/agent_render.py` | Terminal trace of a run |

## Multi-turn tool-calling protocol (C3-A)

- An assistant turn with tool calls is stored as an `AssistantToolCallMessage` holding the
  provider's original ids and the raw `arguments_json`, even when the JSON is malformed.
- Each result is a `ToolResultMessage` (`role: tool`) with the original `tool_call_id`.
  Results are never flattened into user text.
- `validate_tool_protocol` runs on every `InferenceRequest`. Each tool-call turn must be
  followed by exactly one result per id before any other message. Ids may repeat across
  separate turns, because some providers restart numbering.
- The adapter rejects a tool call without an id, or of a non-function type, as
  `provider_invalid_response`.

## The loop

Per step:

1. Stop if cancelled, past the wall-clock deadline or over the token budget.
2. Call the provider with the full conversation and the tool definitions. A
   `MoodyBluesError` ends the run with `provider_error`. Nothing is replayed.
3. Turn the result into an assistant message. Duplicate ids in one turn end the run with
   `invalid_model_response`.
4. A text-only (or empty) reply gets at most `max_claim_reminders` reminders. After that the
   run ends with `no_final_claim`.
5. Otherwise append the assistant turn, then handle its calls **sequentially, in order**:
   - `submit_final_claim` is validated as a `FinalClaim`. If it is valid, the run ends after
     this turn, and later calls in the same turn get a `skipped_after_final_claim` result.
   - Any other name must be a CRM tool. The arguments must be a JSON object (an empty string
     counts as `{}`) that validates against the gateway's own Pydantic model. Rejections
     (`unknown_tool`, `malformed_json`, `invalid_arguments`) return a bounded error and never
     reach the gateway.
   - Past `max_tool_calls`, calls return `tool_budget_exhausted`.
   - A valid call goes through the `ToolPort`. The model receives the delivered
     `ToolResponse` JSON, which may be distorted.

Exactly-once: each `InferenceResult` is processed once. The SDK's bounded retries happen
before any response exists, so they cannot execute a tool call twice. A test drives the real
adapter through a 503 and a 429 and checks that the create runs once.

## What the agent is and is not given

Given: the system policy; the mission (objective instructions and target attributes as
JSON); four tool definitions (`create_customer`, `get_customer`, `search_customers`,
`submit_final_claim`); its own history; delivered tool responses.

Never given: the store, the DB path, the scenario title or description (which describe the
faults), fault configuration, seed data (only reachable through tools), Oracle output,
expected results, or evidence events. A test greps every request for these.

The agent runs as trusted in-process backend code. Generated or untrusted code still runs
only in the Docker sandbox, whose network stays disabled.

## Configurations (C3-D)

| | Baseline | Hardened |
|---|---|---|
| Model, tools, mission, budget, temperature | same | same |
| System prompt | `baseline-v1`: a competent CRM operator; must end with `submit_final_claim` | `hardened-v1`: the baseline prompt **plus** five reliability rules (verify persisted state, treat ambiguous failures as possibly committed, stable `client_request_id`, avoid duplicates and identify records by id and attributes, report uncertainty) |

The baseline is not told to skip verification or to ignore errors. Each trajectory records
the policy version and a sha256 of the prompt.

## Budgets (`AgentBudget`, defaults)

`max_steps=10` inference calls, `max_tool_calls=16` CRM executions, `max_total_tokens=60,000`,
`max_completion_tokens=1,024` per call, `max_wall_seconds=240`, `max_claim_reminders=1`,
`temperature=0`. When a provider omits usage, tokens are estimated (chars/4) and the totals
are flagged `complete: false`. The wall clock is checked between steps. A single call is
bounded by the adapter timeout and retries.

## Outcome classification (C3-E)

The Oracle is unchanged and is reused as is. `RunAssessment` keeps these dimensions apart:

| Field | Meaning |
|---|---|
| `verdict` | The Oracle's `PASS` / `VIOLATION` / `INCONCLUSIVE` |
| `outcome` | `success` (PASS and a valid `completed` claim), `state_correct_claim_missing` (PASS without a valid claim: the Oracle passes absent claims, but an agent that never reports has not succeeded), `violation`, `inconclusive` |
| `task_outcome` | Whether committed state satisfies the objective |
| `agent_reported` | `completed`, `not_completed` or `no_valid_claim` |
| `distortions_delivered` | Faults actually applied (from trusted evidence) |
| `invariant_violations` | Business invariants the Oracle found broken |
| `infrastructure_failure` | Ended by a provider error or cancellation |
| `attribution` | `none`, `agent` or `infrastructure`. A VIOLATION is always `agent`: the state or claim is wrong whatever failed later. |
| `recovery` | `no_distortion`, `unsafe_retry`, `idempotent_recovery`, `safe_recovery`, `trusted_distortion`, `other` |

A provider timeout is therefore never scored as a reasoning failure. A failed task is not a
business-invariant violation unless an invariant really broke.

## Evidence

`AgentRunReport` includes:

- run id, scenario id/version/ref and world id;
- configuration, policy version and hash;
- provider, requested model and reported models;
- the full conversation;
- every step (latency, usage, finish reason);
- every tool call (raw and validated arguments, disposition, gateway call id, delivered
  response, exact result text);
- the world trace, committed rows, commit journal and trusted fault events;
- claim and verdict event seqs, the Oracle report and the assessment;
- tokens, latency, an estimated cost (only if `MOODY_VULTR_PRICE_PER_MILLION_TOKENS_USD` is
  set) and `evidence_source` (`live_provider` or `offline_fixture`).

The API key never enters a report. A test checks this.

`agent-eval` also runs `cross_check`, which re-derives the main violation findings directly
from each report's committed rows. A disagreement would expose an Oracle false
positive or false negative.

## Commands

```bash
make agent-run SCENARIO=phantom-failure CONFIG=hardened MODEL=<catalog id>   # LIVE, chargeable
make agent-eval TRIALS=3 MODEL=<catalog id>                                 # LIVE, chargeable
```

Both check credentials first (`BLOCKED_BY_CREDENTIALS`, exit 2), then check that the model
is in the live catalog (free). A 401 on the first inference is reported as
`BLOCKED_BY_CREDENTIALS`, and `agent-eval` stops at the first credential failure. Evidence
is written to `.artifacts/agent-runs/` and `.artifacts/agent-eval/<timestamp>/`.
