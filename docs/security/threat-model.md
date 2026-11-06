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

## External agents (Sprint 15)

An external agent is untrusted code, written by someone else, which holds a live channel to trusted code
for the whole of a run. Everything below is enforced on the host or by the sandbox. The SDK enforces nothing.

| Threat | Control | Tested by |
|---|---|---|
| Agent reaches the CRM, the Oracle or the engine directly | Separate container; the engine, world files and database are simply not in it | `test_the_engine_is_not_in_the_sandbox`, `test_no_world_database_is_reachable` (real Docker) |
| Agent reaches the host, a network or a credential | No mounts, socket, network or host environment; canary checked | `tests/security/test_external_agent_containment.py` (real Docker) |
| Agent forges a tool result, a verdict or a commit | There is no such message: an unknown `type` ends the run | `test_a_forged_tool_result...`, `test_an_oracle_request_is_not_a_message` |
| Agent claims success, with invented evidence | The claim is checked against committed state; unknown references are kept apart | `test_a_claim_is_checked_not_believed`, `test_forged_evidence_references...` |
| Calls past its scope, allowlist or quota | Decided in the driver, before the gateway | `tests/external/test_boundaries.py` |
| A retry becomes a duplicate | Nothing repeats a call; a reused `call_id` is refused | `test_one_call_id_never_runs_twice`, `test_a_timed_out_call_is_not_retried` |
| Agent learns what its world will do | Opaque `scenario_ref`; the same mission as an internal target | `test_the_context_says_nothing_about_the_world` |
| Agent passes as a model, or hides one | The label comes from model calls the host brokered | `test_saying_llm_does_not_make_a_run_an_llm_run` |
| Spends money | No network, so a model only through the host: opt-in, ledger, caps | `tests/external/test_inference.py`, `test_commands.py` |
| Floods output, fills memory, forks, hangs, or stops reading | Line and queue bounds, cgroup limits, a host deadline, a send timeout | `test_a_stdout_flood_is_bounded`, `test_memory_limit...`, `test_pid_limit_holds`, `test_a_process_that_stops_reading...` |
| Agent output attacks whoever reads it | Rejected lines kept by hash; stderr labeled untrusted, never parsed; events hold ids and fixed codes; React escapes the rest | `test_a_rejected_line_is_recorded_by_hash_only`, `test_events_hold_no_agent_text_or_arguments` |
| Coordinator dies mid-run | Journal first; `uncertain`; nothing replayed; the container stops at its own deadline | `test_coordinator_killed_mid_run...` (real Docker) |
| Evidence is altered afterwards | Hashes on report, evidence and journal; a chain over every protocol line | `test_an_edited_external_record_fails_verification` |

Residual risks specific to external agents:

- **Containers share a kernel.** An external agent is the first sustained, attacker-writable process in that
  sandbox on a machine with a Docker daemon. These controls were tested on Colima on a laptop, and **have
  not been run on the Vultr VM**: see the [plan](hosted-containment-plan.md). Hosting this for strangers needs
  stronger isolation first.
- **`scenario_ref` hides the name, not the behavior.** An agent that runs repeatedly can learn how faults
  behave. That is what a resilient agent would do anyway, but do not read a result as a blind trial.
- **A model call's content is the agent's.** With a model granted, the agent chooses the prompt, inside the
  budget. It cannot see the key, but it can spend what was granted.
- **A manifest's `name` is chosen by the agent's author** and shown to operators, as text.
- **Scopes are all-or-nothing per manifest.** An operator cannot narrow them per run.
- **A hash is not a signature**, as elsewhere. `bundle_sha256` says what ran, not who wrote it.

## Worlds (Sprint 18)

A world plugin is trusted backend code, reviewed like any other. External agents and the Investigator stay untrusted.

| Threat | Control | Tested by |
|---|---|---|
| An agent registers or selects a world or an Oracle | The registry is a read-only table built in code. No protocol message, route or experiment action names one | `tests/world/test_world_registry.py` |
| Arbitrary code through a plugin | No dynamic import anywhere on the path, checked over the AST | same |
| An agent reaches another world's tools | Scopes are the world's own names. A foreign scope never starts; a foreign tool is unknown and reaches no gateway | `tests/external/test_cross_world.py`, real Docker |
| An experiment names another world's scenario | One coordinator, one world; refused as `unsupported_scenario` | same |
| A plugin redefines a verdict | `verify_world` recomputes it from the report's findings and refuses a disagreement | `tests/world/test_job_queue.py` |
| An agent supplies a verdict | No field exists; a `final` that sends one ends the run | `tests/external/test_cross_world.py` |
| A claim of one world read as another's | `extra="forbid"` on both, and the driver reads only the world's own field | same |
| A world database read across worlds | One directory and file per run, and agents have only their sandbox | `tests/world/test_job_queue.py` |

No public route changed. Operator missions are unchanged and name no world, so Job Queue World cannot be run from the API.

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
