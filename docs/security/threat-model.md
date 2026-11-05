# Threat model: Investigation Explorer

_Sprint 7, local release. Sandbox containment is covered in
[experiment-runtime.md](../architecture/experiment-runtime.md)._

## Assets

Provider credentials. Promotional credit. The integrity of evidence, meaning no reader is shown a result
that did not happen. Raw traces. The host.

## Threats and controls

| Threat | Control | Tested by |
|---|---|---|
| Anonymous paid inference | Operator routes refuse without a token, and return 403 with none configured | `tests/explorer/test_jobs.py`, Playwright |
| A stolen session starts unbounded runs | One job at a time, a live switch, the shared ledger, a $0.75 scope | `test_jobs.py` |
| Arbitrary code or parameters through the API | `extra="forbid"` and a closed mission catalog; the Next layer forwards only `mission_id` | `test_only_a_catalog_mission_id_is_accepted` |
| Used or reserved worlds run again | Not in the catalog | `test_no_mission_touches_a_used_or_reserved_world` |
| Token guessing | Constant-time compare, 32-character minimum, ten failures a minute | `test_repeated_failures_are_throttled...` |
| Cross-site request | SameSite=Strict, an Origin check on every state change, no CORS for the auth header | Playwright |
| Token reaching page scripts or bundles | httpOnly cookie, no `NEXT_PUBLIC_`, bundle scan | Playwright |
| Path traversal | Ids compared with the manifest and job records, never joined to a path | `test_traversal_and_unknown_ids_reach_nothing`, Playwright |
| Raw records exposed | No route to them; projection copies named fields | `test_raw_records_have_no_route`, `test_committed_bundles_carry_no_raw_prompts_or_paths` |
| Secrets or paths in exported evidence | Decoded-string scan refuses export; configured secrets checked by value | `tests/explorer/test_recorded.py` |
| Tampered evidence shown as real | Hash and schema checked on every read; refusal is visible | `test_evidence_api.py`, Playwright |
| A recorded case passed off as live | The store refuses a recorded slot with another mode | `test_a_recorded_slot_cannot_serve_a_bundle_labeled_live` |
| A fixture presented as model behavior | Export refuses it; rehearsals say fixture in the UI | `test_recorded.py`, Playwright |
| Model or target text used as markup or commands | React escapes all of it; none is streamed in job events; nothing acts on it | `test_events_carry_no_free_text` |
| Oversized responses | Bundle, text and page limits | `test_evidence_api.py` |
| Duplicate side effects after a crash | Never retried; `outcome_uncertain` | `test_a_killed_worker_during_a_target_run...`, `test_explorer_restart.py` |
| Sandbox reads provider secrets | No host environment passed, canary tested | `tests/security` |

## Residual risks

- **`POST /sandbox/smoke` needs no token.** It runs a fixed harmless program but starts a container, so
  an exposed backend could be made to start many. The backend must not be public.
- **`/investigations` carries no rate limit.** Reads are cheap and bounded, but a public host should put
  a limit in front.
- **The failed-attempt limit is global and in-process.** An attacker can lock out the operator for a
  minute, and a restart clears the count.
- **The token is one shared secret.** Actions are not attributed, and rotation needs a restart.
- **Evidence hashes are not signatures.** See [recorded-investigations.md](../architecture/recorded-investigations.md).
- **`secure` on the cookie follows the request URL.** Behind a TLS proxy it needs forwarded-proto
  handling, or the cookie is not marked secure.
- **The Target Agent runs in the API process during a live job.** It is trusted code holding the provider
  key, and it is fed untrusted tool output by design.
- **Containers share the host kernel.** There is no gVisor or Kata layer.
