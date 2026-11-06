# ADR 0013: The Investigator against external targets

**Status:** accepted, Sprint 16. Extends [ADR 0012](0012-external-agent-adapter.md).

## Context

Sprint 15 said the investigation around external runs was a fixture. That was imprecise. `external_workflow`
already used the real `InvestigationWorkflow` and coordinator: only the Investigator's *model* was a
fixture. The real gaps were elsewhere, and some were defects:

- The Investigator's model was told every target was "an LLM CRM Operations Agent", including scripts.
- No validated selection existed, and nothing recorded which target an investigation was pointed at.
- No path gave an external target a live Investigator.
- The model broker had never met a provider that misbehaves. It could pay twice for a reused id, it counted
  only successes against its budget, the client silently retried, and a call could outlast the run.

## Decision

1. **No second coordinator or engine.** The workflow, coordinator, gateway, faults and Oracle are unchanged.
   `InvestigationWorkflow` already took a `capability`, and `ExperimentRunner` already took a `TargetPort`.
2. **The capability comes from the registration.** `external_capability` is fixed strings plus the host's own
   tool grant. Nothing an agent wrote reaches the model, not even its display name.
3. **Selection is validated, and only by trusted code.** `TargetKind` is `internal_llm`, `external_scripted`
   or `external_llm`. `external/selection.py` checks it against the manifest. It comes from an operator's
   command line. The HTTP API still names a catalog mission and nothing else.
4. **The selection is not the observation.** `TargetProvenance` records what was chosen. Whether a model took
   part stays on each run's record, written by the host.
5. **A model call that reached a provider makes a run a model run, even if it failed.** It may be billed.
   Sprint 15 labeled such a run `external_scripted`, which hid a possibly charged request.
6. **An ambiguous call is never repeated by the host.** Live clients have `max_retries=0`. A call with no
   trusted answer is `uncertain`, keeps its reservation, and the agent decides what to do next.
7. **Each model call is written down before it is made**, beside the world, so that a coordinator crash cannot
   lose the fact of it. Recovery reports calls with no outcome as `model_calls_unresolved`.

## Evidence compatibility

**No new schema version.** `model_requests`, `target` and `model_calls_unresolved` are optional and left out
when empty (`exclude_if`), so schema 1 and 2 records parse unchanged and earlier records stay byte-identical.
`make recorded-verify` holds this. A new version would only be needed if an old reader had to reject new records,
and nothing does.

## Consequences

- `model_calls` now counts requests that reached a provider, not only answers delivered.
- `external-run --live-inference` now needs `--approved-spend-usd`.
- `config` is still required by `mb-exp/1` and means nothing for an external target. The capability says so,
  but the coordinator accepts `hardened` from a model that ignores that, and records it.

## Not decided here

Whether the Investigator finds failures better than fixed testing. The registered answer stays
`NO_DEMONSTRATED_ADVANTAGE`, and nothing in this sprint measures it.
