# Sprint 2: Stateful World Engine, controlled distortions and Truth Oracle

- **Date:** 2026-11-03
- **Branch:** `sprint/02-world-engine`, branched from the Sprint 1 HEAD `6fc58be`
- **Outcome:** `LOCALLY_ACCEPTED_WITH_EXTERNAL_BLOCKERS`

The external blockers are carried over from Sprint 1: live Vultr verification and the first
GitHub Actions run. Neither is needed by the World Engine.

## Goal

Answer this question with real persisted state: *when an agent receives misleading
information about a tool operation, can MOODY BLUES independently determine what really
happened?*

## Delivered

- **Synthetic CRM** (`world/store.py`, `world/engine.py`):
  - one SQLite file per world, with transactional writes and an explicit pre-commit boundary;
  - idempotency keys;
  - a trigger-maintained commit journal;
  - an append-only evidence trail;
  - a SQLite-enforced read-only view;
  - reset and cleanup.
- **Tool gateway** (`world/gateway.py`): `create_customer`, `get_customer` and
  `search_customers`. Faults:
  - `phantom_success`: pre-commit abort plus a fabricated success.
  - `phantom_failure`: post-commit replacement of the response with an error.
- **Truth Oracle** (`world/oracle.py`): `PASS`, `VIOLATION` or `INCONCLUSIVE`, with typed
  findings and response/state divergences, computed from authoritative state only.
- **Scenarios** (`world/scenarios/*.json`): `normal-success`, `phantom-success`,
  `phantom-failure` and `clean-negative-control`. They are versioned and contain no expected
  answers.
- **Reference executors and cases** (`world/reference.py`): deterministic scripts, not LLM
  agents.
- **Runner** (`services/world_runner.py`): returns a `RunReport` with a reproducibility
  fingerprint.
- **CLI:** `make world-demo` and `moody-blues world-run --scenario … --executor … [--json]`.
- **Docs:** [world-engine.md](../architecture/world-engine.md) and
  [ADR 0002](../adr/0002-world-engine.md).

## Acceptance

| Gate | Status | Evidence |
|---|---|---|
| C2-A State integrity | PASS | `tests/world/test_domain.py` (36): validation, CRUD, rollback on a pre-commit exception, abort, CHECK constraints, append-only journals, `mode=ro` refusal, lock → no unobserved action, reset, isolation |
| C2-B Fault semantics | PASS | `tests/world/test_faults.py` (20): commit/no-commit per fault, exact occurrence targeting, invalid and read calls don't consume occurrences, no cross-world leakage, contract validation. The state machine models fault semantics under random plans. |
| C2-C Independent truth | PASS | `tests/world/test_oracle.py` (23): PASS, VIOLATION and INCONCLUSIVE cases. Tampering with delivered responses, or deleting fault events, leaves the verdict unchanged (also a Hypothesis property). |
| C2-D Deterministic reproducibility | PASS | Fingerprints are equal for every reference case across fresh worlds and across `reset()`; a Hypothesis property covers random fault plans × executors |
| C2-E Realistic controls | PASS | 8 reference cases: 5 PASS (including 3 recoveries), 2 VIOLATION, 1 INCONCLUSIVE. The unsafe and safe executors receive an identical first response. |
| C2-F Regression safety | PASS | `make check` exit 0: 174 unit + world tests, 16 Docker, 4 E2E; lint, types and build clean |
| Live Vultr | BLOCKED_BY_CREDENTIALS | `MOODY_VULTR_API_KEY` not set; not needed for this sprint |
| GitHub Actions | NOT_RUN | not pushed; pushing needs approval |

## Reference case results (`make world-demo`)

| Case | Scenario × executor | Verdict | Key findings |
|---|---|---|---|
| normal | normal-success × verify_then_report | PASS | none |
| phantom-success-trusted | phantom-success × trusting | VIOLATION | `false_completion_claim`, `claim_references_uncommitted_id` |
| phantom-success-verified | phantom-success × verify_then_report | PASS | divergence on call 1 (diagnostic) |
| phantom-failure-trusted | phantom-failure × trusting | INCONCLUSIVE | `underreported_completion` (warning) |
| unsafe-retry | phantom-failure × blind_retry | VIOLATION | `duplicate_side_effect` (calls 1 and 2), `false_completion_claim` |
| safe-recovery | phantom-failure × verify_then_report | PASS | divergence on call 1 (diagnostic) |
| safe-recovery-idempotent | phantom-failure × idempotent_retry | PASS | call 2 is an `idempotent_replay` |
| negative-control | clean-negative-control × busy_but_correct | PASS | none (7 calls, including honest `not_found` and `validation_error`) |

## Problems found and fixed

1. **A reference executor never used its idempotency key.** The demo trace showed
   `idempotent_retry` making only 2 calls: it searched state before retrying, so the
   idempotency path never ran. It now retries with the same key and verifies after a
   success. Regression test: `test_idempotent_recovery_actually_replays`.
2. **The fingerprint would have broken across reset.** `epoch` was in the
   `world_initialized` payload, so the evidence after `reset()` would differ from a fresh
   world. Fixed by moving `epoch` to `world_meta` only. Covered by
   `test_execute_inspect_reset_execute_again`.
3. **A read-only test could not tell its two protections apart.** As first written, one
   `pytest.raises` block covered both the `query_only` and the `mode=ro` attempts, so a
   pass could not show which protection held. It is now split: lift `query_only`, then
   assert that `mode=ro` alone still refuses writes.
4. **A divergence message rendered `customer None`** for error responses. The wording now
   depends on the direction of the divergence.
5. **Tooling:**
   - Pyright strict flags `@contextmanager` with an `Iterator` return type as deprecated; it
     now uses `Generator`.
   - Ruff S105 flagged `Verdict.PASS = "PASS"` as a password; it carries a scoped `noqa`.
   - Ruff S101 flagged production asserts; they are now explicit raises.

### Mutation check

These bugs were injected one at a time and then reverted. Each was caught by the suite:

| Injected bug | Failing tests |
|---|---|
| `phantom_success` commits | 7 |
| Oracle trusts all-ok responses | 11 |
| Idempotency removed | 5 |
| `phantom_failure` skips the commit | 15 |

## Remaining risks

- There is one write tool. Update and delete faults will need new boundaries; the triggers
  already journal them.
- Objective matching keys on email. Seeding a pre-existing customer with the objective's
  email would require an executor to tell old records from new ones. The Oracle already
  separates seeds by id, but no scenario exercises this yet.
- Reference executors are scripts. **No real LLM agent behavior has been tested.**
- The World Engine runs as trusted in-process code. Connecting sandboxed or untrusted
  executors needs a coordinator (Sprint 3+). Sandbox networking stays disabled.

## Prerequisites for Sprint 3

- Vultr credentials, then `make vultr-models` and `make vultr-smoke`. This is required
  before a real target agent or the Investigator can run.
- Adapt `ToolPort` and `tool_specs()` to the Vultr tool-calling adapter (an LLM target agent).
- Push the branch and confirm CI (it now also runs `tests/world` and `world-demo`).
