# Sprint 3: Real LLM Target Agent, Vultr integration and behavioral evaluation

- **Date:** 2026-11-03
- **Branch:** `sprint/03-target-agent`, branched from the Sprint 2 HEAD `7007efe`
- **Outcome:** `LOCALLY_ACCEPTED_LIVE_BLOCKED`. Everything that can be verified offline is
  done and green. **Live model behavior is unverified:** the configured Vultr key is rejected
  with HTTP 401. Full acceptance is **not** claimed.

## Goal

Put a genuinely tool-using LLM agent into the stateful synthetic CRM, distort what it
observes, and have the unchanged Truth Oracle verify the outcome independently.

## Delivered

| Area | What | Where |
|---|---|---|
| C3-A protocol | Typed conversation: text, assistant tool-call turns (original ids and raw arguments kept), `role=tool` results; `validate_tool_protocol`; OpenAI wire serialization; tool calls without an id are rejected | `contracts/inference.py`, `inference/vultr.py` |
| C3-B fault semantics | `FaultEffect` follows the real outcome; `fault_skipped`; `new_commit`/`call_outcome` on evidence | `world/gateway.py`, `contracts/scenario.py` |
| Target Agent | Bounded loop, sequential exactly-once execution, budgets (steps, tool calls, tokens, wall clock), cancellation, reminders, `submit_final_claim` | `agents/target.py`, `agents/tooling.py` |
| Policies | `baseline-v1` and `hardened-v1` (baseline plus five reliability rules); identical tools, mission, model and budget | `agents/policies.py` |
| Oracle integration | `AgentRunReport` + `RunAssessment` (outcome, task outcome, reported outcome, distortions, violations, infrastructure, attribution, recovery pattern, behavior metrics) | `services/agent_world_runner.py`, `contracts/agent.py` |
| Evaluation | Scenarios × configs × trials, eval-wide token budget at trial boundaries, stop on credential failure, JSON/Markdown summaries, Oracle cross-check | `services/agent_eval.py` |
| Live commands | `make agent-run`, `make agent-eval` (credential and catalog preflight); `vultr-smoke` adds `tool_round_trip` | `cli.py`, `inference/smoke.py` |
| Scenario | `preexisting-email`: a different customer already has the objective email, plus a phantom success | `world/scenarios/preexisting-email.json` |
| Docs | [target-agent.md](../architecture/target-agent.md), [ADR 0003](../adr/0003-target-agent.md), world-engine fault effects, preflight, validation, known issues KI-11, KI-16 to KI-19 | `docs/` |

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C3-A Protocol correctness | **PASS** (offline) | `tests/unit/test_inference_protocol.py`: JSON round trip keeps ids, order and raw arguments; exact wire shapes; parallel calls; protocol violations rejected. The live `tool_round_trip` check is BLOCKED_BY_CREDENTIALS. |
| C3-B Fault correctness | **PASS** | `tests/world/test_fault_idempotency.py` (12) and the Hypothesis state machine, which now checks the recorded effect and `new_commit` after every faulted create. The 8 Sprint 2 reference verdicts are unchanged. |
| C3-C Live target agent | **BLOCKED_BY_CREDENTIALS** | `agent-run` reached Vultr and got `401 Invalid API key` (run `run_f72108449985`). No live trajectory exists. |
| C3-D Comparable configurations | **PASS** (offline) / **NOT_RUN** (live) | `test_both_configurations_get_identical_tools_mission_and_budget`: requests differ only in the system prompt. No live comparison was possible. |
| C3-E Verified outcomes | **PASS** (offline, fixture behaviors) / **NOT_RUN** (live) | `tests/agent/test_agent_world.py`: 10 scenario × behavior cases give the expected verdicts and recovery patterns, and the Oracle ignores optimistic claims. |
| C3-F Regression safety | **PASS** | `make check` exit 0: 271 offline, 16 Docker, 4 Playwright; no skips; `world-demo` unchanged |
| C3-G Documentation and evidence | **PASS** for implemented behavior | Run reports carry every field in brief §10. The live evaluation report is still missing. |

## Live Vultr record

| Step | Result |
|---|---|
| Credentials in env | `MOODY_VULTR_API_KEY` set (not printed) |
| `make vultr-models` | 35 models. **Defect found:** `GET /models` returns 200 with no key or a bogus key, so the Sprint 1 interpretation of this check was wrong. The report now says `verifies_credentials: false`. |
| Configured model | `kimi-k2-instruct` is **not** in the catalog |
| `make vultr-smoke` with `glm-5.3`, `qwen3.8-27b`, `deepseek-v4.1-flash-1017` | 401 `Invalid API key` on every completion |
| `make agent-run` with `glm-5.3` | `provider_error / provider_auth` → BLOCKED_BY_CREDENTIALS; Oracle INCONCLUSIVE, attributed to infrastructure; 0 tokens; nothing written to the CRM |
| Model ID, reported model, latency, token usage | **Not available**: no request was accepted |
| Cost | $0 observed. Pricing is not configured; nothing is estimated. |

The key is 36 upper-case alphanumeric characters. That matches a Vultr *account* API key,
not a Serverless Inference key (likely, not confirmed). To unblock, see
[vultr-preflight.md](../deployment/vultr-preflight.md).

## Baseline vs hardened

**No live comparison exists.** This sprint makes no claim about whether the hardened
policy changes real model behavior. The offline fixture behaviors (trusting, blind retry,
idempotent retry, verify, same-email claim) only show that the harness labels each
trajectory correctly:

| Scenario | Fixture behavior | Oracle | Recovery label |
|---|---|---|---|
| normal-success | trusting | PASS | no_distortion |
| phantom-success | trusting | VIOLATION (false completion, uncommitted id) | trusted_distortion |
| phantom-success | verify | PASS | safe_recovery |
| phantom-failure | trusting | INCONCLUSIVE (underreported) | trusted_distortion |
| phantom-failure | blind retry | VIOLATION (duplicate) | unsafe_retry |
| phantom-failure | verify | PASS | safe_recovery |
| phantom-failure | idempotent retry | PASS | idempotent_recovery |
| clean-negative-control | verify | PASS | no_distortion |
| preexisting-email | claim any same-email record | VIOLATION (wrong record, false completion) | no_distortion |
| preexisting-email | verify | PASS | safe_recovery |

To produce the real comparison once the key works:

```bash
MOODY_VULTR_MODEL=<id> make vultr-smoke     # basic, tool_calling, tool_round_trip
make agent-run SCENARIO=normal-success CONFIG=baseline MODEL=<id>
make agent-eval TRIALS=3 MODEL=<id>         # 5 scenarios x 2 configs x 3 = 30 runs, <=400k tokens
```

## Problems found and fixed

1. **Fault labels contradicted the write outcome (C3-B).** `phantom_failure` on an
   idempotent replay was labeled `post_commit` although nothing committed in that call.
   `phantom_success` on a replay fabricated a new id and claimed a pre-commit abort that
   never happened, which also produced a spurious Oracle divergence. The fault effect is
   now decided from the real outcome. The Hypothesis model had encoded the old behavior; it
   now asserts the intended one (as AGENTS.md requires for wrong tests, and stated in the
   commit).
2. **`vultr-models` was taken as credential evidence.** The endpoint is unauthenticated.
3. **The default model is absent from the catalog.** The live commands now refuse unlisted
   models before spending anything.
4. **An absent claim scored as Oracle PASS.** This is deliberate Sprint 2 Oracle semantics
   and is left unchanged. For agent runs it would have read silence as success, so
   `RunOutcome.STATE_CORRECT_CLAIM_MISSING` now keeps it apart from `success`.
5. **The eval budget could split a trial.** The token check could stop between the
   baseline and hardened runs, giving unequal samples. It now runs only at trial boundaries.
6. **Silently dropped tool calls.** The adapter used to drop non-function tool calls. It
   now raises `provider_invalid_response`, and also does so for calls without an id.
7. **A test false positive.** `"fault"` matched `"default"` in the leak test; it now uses
   word boundaries (KI-19).
8. **Environment:** the macOS `hidden` flag on `.pth` files broke imports mid-sprint
   (KI-18).

### Mutation check

| Injected bug | Failing tests |
|---|---|
| `phantom_success` always labeled as applied (the old bug) | 6 |
| Assistant tool-call turn not appended before its results | 47 |
| Pydantic argument validation skipped | 3 |
| Missing claim counted as success | 2 |

## Remaining risks

- **No real model has run.** Tool-call reliability, argument quality and recovery behavior
  of any Vultr model are unknown. A model may not support `tools`
  (`provider_bad_request`), or may emit text-encoded tool calls the adapter does not parse.
- The wall clock is checked only between steps. One call can take up to timeout ×
  (retries + 1) = 90 s with the current settings.
- Token estimates (chars/4) are used only when a provider omits usage, and are flagged.
- The agent runs in-process as trusted code. Untrusted or generated agents need the
  Sprint 4 coordinator; the sandbox stays network-isolated.
- Behavioral conclusions will need several trials per cell. Three trials is a floor, not
  statistical power.

## Readiness for Sprint 4

Ready offline: protocol, agent runtime, evaluation harness and evidence format are in place
and tested. Before Sprint 4 depends on agent behavior:

1. Put a valid Serverless Inference key in `.env`; run `make vultr-smoke` with a catalog
   model and record model, latency and tokens.
2. Run `make agent-eval TRIALS=3 MODEL=<id>` and add the measured comparison to this
   record.
3. Push the branch and get the first CI run (needs approval).
