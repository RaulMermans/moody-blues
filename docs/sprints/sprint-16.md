# Sprint 16: External AI validation

- **Branch:** `sprint/16-external-ai-validation`, from `origin/main` at `4794c76` (PR #21). Committed locally: not
  pushed, merged or deployed.
- **Worked in:** `~/dev/Moody-Blues`, as the brief says.
- **Outcome:** the path is built and its boundaries hold, offline and in real containers. **The core goal is not yet
  proven: no real model has driven an external agent or written a hypothesis about one.** Both wait on the owner's
  [approval](../external-agents/live-validation-approval.md). `EXTERNAL_LLM_LIVE_VALIDATION = NOT_RUN`.

## Release preflight, 2026-11-06

| Item | Finding |
|---|---|
| Hackathon submission | **UNKNOWN, treat as critical.** The form needs the owner's sign-in. Deadline 2026-11-08 22:00 UTC |
| Production | **Up, unchanged.** `/api/status` ready, inference `not_configured`, before and after this work |
| Deployed against `main` | **Behind.** Sprint 13 by the last records. Sprints 14 and 15 are merged, not deployed. There is no revision endpoint, so this comes from records and was not re-measured |
| CI on `main` | **Green** at `4794c76` |
| License | **None.** Public repository, no LICENSE file. Owner decision |
| Vultr keys | Rotation of both is **not confirmed**. It cannot be seen from here. No values were read |

## Audit

Sprint 15's "the investigation is a fixture" was imprecise: `external_workflow` already ran the real workflow and
coordinator, and only the Investigator's model was a fixture. The audit found these instead.

| # | Defect or gap | Fix |
|---|---|---|
| 1 | A reused model `call_id` reached the provider twice | Refused, shared with tool ids |
| 2 | Failed calls did not count, so paid failures were unbounded | Attempts are counted |
| 3 | The SDK client silently resent ambiguous requests | `max_retries=0` |
| 4 | A 120 s call could outlast a 60 s run, and could not be cancelled | Worker thread; `uncertain` |
| 5 | No prompt limit, and the last call could pass the reservation | Size and worst case checked first |
| 6 | A run whose only call failed read `external_scripted` | Labeled by requests that reached a provider |
| 7 | A provider failure read as the agent's shortfall | `provider_error`, as for the internal agent |
| 8 | A coordinator crash lost all trace of a model call | Written down first; `model_calls_unresolved` |
| 9 | The Investigator was told every target was an LLM | `external_capability` |
| 10 | No validated selection, no live Investigator route, no allowlist | `external/selection.py`, `external-investigate`, `external_model_allowlist` |
| 11 | A live Investigator would have published as a rehearsal, reading "a fixture chose the tests" | Mode follows the model |
| 12 | The example agent crashed on bad model JSON, a tool timeout or a fenced report | Handled in the agent |

No second coordinator or engine. Decision: [ADR 0013](../adr/0013-investigating-external-targets.md).

## Results

Real containers, on Colima. **Every model below is a labeled fixture, including the Investigator's.**
Details: [evaluation](../evaluations/sprint-16/README.md).

| Case | Target's evidence | Run 1 | Run 2 |
|---|---|---|---|
| A. Careful script | `external_scripted` | PASS | PASS |
| B. Unsafe script | `external_scripted` | VIOLATION | VIOLATION |
| C. LLM agent, fixture that verifies | `offline_fixture` | PASS | INCONCLUSIVE |
| C. LLM agent, fixture that retries | `offline_fixture` | VIOLATION | VIOLATION |
| D. LLM agent, real provider | | **NOT_RUN** | |
| E. Workflow against external targets | all four above | Ran, with a fixture Investigator | Model-written hypotheses **NOT_RUN** |

Case C's INCONCLUSIVE stands as recorded: the agent honestly said `not_completed` after a phantom success.

These prove integration and boundaries. They are not LLM behavior, and they compare nothing:
`NO_DEMONSTRATED_ADVANTAGE` stands.

## Acceptance gates

| Gate | Status | Evidence |
|---|---|---|
| C16-0 Submission and release protection | **BLOCKED** | Production safe and untouched. Submission and key rotation need the owner |
| C16-A External LLM integration | **PASS, deterministic.** Live: **NOT_RUN** | Real agent code and protocol in Docker, against a fixture. Wiring tested at the client seam with a labeled fake |
| C16-B Autonomous Investigator integration | **BLOCKED on approval** | The real workflow, coordinator and records run against external targets. But the hypotheses came from a fixture, so "authentic hypotheses" is unmet until a model writes one |
| C16-C Trusted model and tool boundaries | **PASS on this host** | `test_model_boundary.py`; 9 of 9 boundaries in real containers; 0 of 14 invalid tool calls reached the gateway |
| C16-D Oracle correctness | **PASS** | Two forged results changed nothing. Oracle code unchanged |
| C16-E Evidence integrity | **PASS** | Per-call host records, tamper detection, `make recorded-verify` |
| C16-F Failure recovery | **PASS** | All 15 scenarios below. Nothing replayed |
| C16-G Containment and developer experience | **PASS locally.** Hosted: **NOT_RUN** | External containment suite on Colima; an agent outside the repository run from the guide. [Plan](../security/hosted-containment-plan.md) |
| C16-H Regression safety | **PASS** | Below |

## Failure scenarios

| # | Scenario | Test |
|---|---|---|
| 1 | Adapter fails to start | `test_lifecycle.py` |
| 2 | Handshake rejected | `test_lifecycle.py`, real Docker |
| 3 | Unauthorized model | `test_an_agent_cannot_name_a_model_or_an_endpoint` |
| 4 | Model request times out | `test_a_timed_out_call_is_uncertain_and_never_repeated` |
| 5 | Malformed provider output | `test_an_empty_provider_answer...`, `...fails_validation...` |
| 6 | Crash after a model response | `test_a_crash_after_a_model_reply...` |
| 7 | Crash during a tool call | `test_a_crash_during_a_tool_call_is_not_replayed` |
| 8 | Coordinator restarts | `test_coordinator_killed_during_a_model_call...`: real SIGKILL |
| 9 | Tool quota exhausted | `ExhaustsQuota` |
| 10 | Inference budget exhausted | `test_failed_calls_count...`, `test_a_call_that_could_pass...` |
| 11 | Sandbox deadline expires | `test_a_model_call_cannot_outlast_the_run_deadline` |
| 12 | Malformed final output | `MalformedFinal` |
| 13 | Evidence persistence fails | `test_evidence_write_failure_is_uncertain_and_not_retried` |
| 14 | Cancellation | `test_cancel_during_a_model_call_does_not_wait_for_it` |
| 15 | Request id reused | `test_a_reused_model_call_id...`, `DuplicateCallId` |

## Validation

Artifacts went to a scratch `MOODY_ARTIFACTS_DIR`. `make evidence-audit` was not run. `evidence/` is unchanged.

| Check | Result |
|---|---|
| Ruff, ESLint, Pyright strict, tsc | **Pass** |
| Offline Python (`make test`) | **1,057 passed** (1,000 before) |
| Real Docker (`make test-integration`) | **106 passed** (97 before) |
| `frontend/e2e` | **37 passed** |
| `frontend/e2e-design` | **217 passed** |
| `frontend/e2e-external` | **8 passed** (6 before) |
| `make external-eval` | **16 of 16** |
| `make external-investigator-eval` | **4 of 4, and 9 of 9** |
| `make recorded-verify`, `eval-verify`, `ledger-verify` | **PASS** |
| gitleaks, 121 commits | **No leaks** |
| Paid inference | **None.** Cost $0, and no provider was contacted |
| Hosted containment | **NOT_RUN** |

The browser suites ran before the last changes, which touched only a print line, tests and docs.

**Two existing tests were changed.** `test_a_provider_failure_reaches_the_agent...` asserted a run whose only call
failed was `external_scripted`. That was defect 6, so the assertion is reversed. `test_live_inference_needs_a_key`
now passes the spend limit that a live run requires.

**Measured.** Agent startup about 290 ms. Total run about 460 ms for a script and 574 ms median across the Sprint 16
cases. Peak memory in the container 14 MB. **Model latency: none measured.** The 1 ms is a fixture's.

**Cost.** Inference estimate $0, provider billing $0 from this sprint, and application limits unchanged. Vultr
infrastructure charges continue separately, at $0.055 an hour, until the VM is destroyed.

## Supported today

| Works | Does not exist |
|---|---|
| Python agents, standard library, run locally by an operator | Other languages or frameworks |
| CRM tools and the approved development worlds | New worlds, faults or a pluggable Oracle |
| Scripted agents; LLM agents with a fixture model | **A real model driving an external agent** |
| The real workflow, with a fixture Investigator | **A real Investigator on an external target** |
| Local containment on Colima | External agents on the VM, or public submission of any kind |

## Known limitations

- **The real Vultr client has not met this path.** The live route was exercised with a fake at the client seam, so
  the provider's real replies, tool-call format and latency are unknown. Expect to fix something.
- **Fixture replies are shaped for the example agent.** Another agent's loop may need its own test double.
- **An abandoned provider call keeps running** until its client timeout. Its answer is dropped; it may still be billed.
- **A model can still choose `hardened`** for an external target. It has no effect, and is recorded.
- **A reserved live run needs the ledger limit raised,** and a laptop run splits the VM's canonical ledger.
- `make external-ui` is still not in CI.

## Sprint 17 prerequisites

1. **Confirm the submission.** Nothing else should come first.
2. Get a decision on [live validation](../external-agents/live-validation-approval.md), and run Option 1.
3. Run Option 2. Only then can C16-B pass.
4. Decide whether Sprints 14 to 16 ship. Then run the [hosted plan](../security/hosted-containment-plan.md).
5. Decide on stronger isolation before anyone else's code runs anywhere.
6. Add `make external-ui` to CI, and add a revision to `/api/status` so that a deployment can be identified.
