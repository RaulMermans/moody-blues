# Threat model: Investigation Explorer

_Sprint 7, local release; hosted controls added in Sprint 8. Sandbox containment is covered in
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
| Backend reached from the internet | Loopback bind, Vultr firewall, ufw, no public route, no smoke route in production; a deploy that finds a non-loopback listener rolls back | `test_deployment_config.py`, hosted suite |
| Forged forwarded headers | Caddy is the edge and replaces them; uvicorn ignores them; origin comes from configuration | `product.spec.ts`, hosted suite |
| A fresh VM forgets past spending | Ledger floor; one path for every caller | `test_hosted_controls.py` |
| A local report presented as hosted | Only the metadata service sets `vultr_hosted`; relabeling fails the hash | `test_containment.py` |
| Sandbox reads the instance metadata service | No network; attempted in every containment report | `containment-report` |

## Residual risks

- **`POST /sandbox/smoke` needs no token.** It is not mounted in production, and the backend binds to
  loopback. It remains in development.
- **Rate limiting is per connection, not per request.** The host firewall limits new connections per
  source. Keep-alive connections can still send many cheap reads.
- **The backend user can reach Docker, which is root-equivalent.** Compromising the trusted backend means
  compromising the host. Sandboxes never inherit this.
- **The failed-attempt limit is global and in-process.** An attacker can lock out the operator for a
  minute, and a restart clears the count.
- **The token is one shared secret.** Actions are not attributed, and rotation needs a restart.
- **Evidence hashes are not signatures.** See [recorded-investigations.md](../architecture/recorded-investigations.md).
- **`MOODY_PUBLIC_ORIGIN` must be set on a host.** It decides `Secure` and the origin check. Unset, as in
  local use, the origin check falls back to the Host header. An invalid value refuses sign-in.
- **The session cookie holds the operator token itself**, for eight hours, httpOnly and Secure. Signing out
  clears that browser's copy and does not revoke the token.
- **The Target Agent runs in the API process during a live job.** It is trusted code holding the provider
  key, and it is fed untrusted tool output by design.
- **Containers share the host kernel.** There is no gVisor or Kata layer.
