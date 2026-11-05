# Evidence API

_Sprint 7. Pydantic contracts: `backend/moody_blues/contracts/explorer.py`. TypeScript mirror:
`frontend/src/lib/evidence-types.ts`._

The browser never calls these directly. Server components and route handlers do.

## Public, read-only

| Route | Returns |
|---|---|
| `GET /investigations` | `InvestigationList`: summaries, any refused records, and the registered study result |
| `GET /investigations/{id}` | `InvestigationDetail`: hypotheses, proposals, observations, findings, conclusion, provenance |
| `GET /investigations/{id}/timeline?offset=&limit=` | `TimelinePage`, at most 500 entries |
| `GET /investigations/{id}/experiments` | `ExperimentList` |
| `GET /investigations/{id}/runs` | `RunList`: per-run summaries and the run to open first |
| `GET /investigations/{id}/runs/{run_id}` | `RealityRun`: sanitized agent and tool events, world state, Oracle findings, discrepancies |

Serves committed bundles only. An operator token also unlocks bundles from that server's own jobs.
Job evidence answers 404 to everyone else.

## Operator

All need `Authorization: Bearer <token>`. With no token configured they answer 403.

| Route | Purpose |
|---|---|
| `GET /operator/session` | Check a token |
| `GET /operator/status` | Ledger, active job, and each mission with why it is blocked |
| `POST /operator/jobs` `{"mission_id": ...}` | Start a mission. 202 with a `JobRecord` |
| `GET /operator/jobs` | The last 50 jobs |
| `GET /operator/jobs/{id}?after=n` | Record and events after `n`: the polling path |
| `POST /operator/jobs/{id}/cancel` | Request cancellation |
| `GET /operator/jobs/{id}/events` | Server-sent events. `Last-Event-ID` resumes after that event |

## Errors

The shared envelope, `{"error": {category, message, retryable}, "request_id"}`.

| Status | Category | Meaning |
|---|---|---|
| 401 | `unauthorized` | Missing or wrong operator token |
| 403 | `forbidden` | Operator access, or live runs, disabled |
| 404 | `not_found` | Unknown or malformed id, or evidence this caller may not see |
| 409 | `conflict` | Another job is running, or the job is not running |
| 409 | `budget_exceeded` | The ledger does not cover one investigation, or cannot be read |
| 422 | `validation` | Not a catalog mission, or an unexpected field |
| 429 | `rate_limited` | Ten failed token attempts in a minute |
| 500 | `evidence_integrity` | The record exists and failed verification. The message carries a code: `missing`, `hash_mismatch`, `schema_invalid`, `id_mismatch`, `mode_mismatch`, `too_large`, `unreadable`, `manifest_invalid` |

## Rules

- **Validated on every read.** Size, then manifest hash, then schema, then id, then mode. A hash match
  does not excuse a schema failure.
- **A refusal is visible.** A bad record stays in the list as `integrity: "corrupt"` with `summary: null`,
  and does not take other records down.
- **No path comes from a request.** Ids are compared with the manifest and job records.
- **Nothing is inferred.** `verdict` and `findings` are copied from the Oracle. `outcome` summarises
  recorded states, read in this order: confirmed violation, impaired violation, uncertain side effects,
  failed, cancelled, budget exhausted, then `no_violation_found` only if every finding is a recovery or a
  clean success. Everything else is `inconclusive`.
- **`verdict` and `run_outcome` stay separate.** An Oracle `PASS` with no claim is not a success.
- **Bounded.** Bundles at most 1.5 MB, messages 4,000 characters, code 16,000, tool JSON 2,000. Cut text
  keeps its original length and hash.

## Job lifecycle

`created → queued → running →` one of `completed`, `failed`, `cancelled`, `budget_exhausted`,
`outcome_uncertain`. Events add `cancel_requested`, `experiment_completed` and `finding_verified`.

Events hold ids and fixed codes only. No model or target text is streamed.

| After a restart the job had | It becomes |
|---|---|
| A report on disk | Finished normally, with evidence |
| A target run that never reported | `outcome_uncertain`, `interrupted_target_run_unresolved` |
| A journal but no open target run | `failed`, `interrupted_no_target_run_open` |
| No journal | `failed`, `interrupted_before_start` |

Nothing is resumed or retried. Open reservations stay on the ledger at full value.
