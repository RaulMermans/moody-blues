# ADR 0015: Versioned world plugins and a shared Oracle path

**Status:** accepted, Sprint 18. Extends [ADR 0002](0002-world-engine.md), [ADR 0012](0012-external-agent-adapter.md) and
[ADR 0013](0013-investigating-external-targets.md).

## Context

Everything around a run was generic in intent and CRM-shaped in fact: the store, the gateway, the Oracle, the evidence
types, the Investigator's prompts and the pages. A developer whose agent does not manage customers could not use any of it.

## Decision

A world is a trusted backend component behind a typed contract, `mb-world/1`, listed by hand in `world/registry.py`.
The coordinator, Investigator and evidence layer hold a `WorldPlugin` and never a store. Job Queue World is the second
implementation, and is what proved the contract: nothing was added to the contract that it did not need.

The contract itself is in [world plugins](../architecture/world-plugins.md). This records why it looks the way it does.

**Sibling types, not renamed fields.** `customer_id`, `customers` and `new_customer_ids` serialize into every bundle ever
written, and hashes cover those bytes. So the CRM's types did not change. Other worlds use neutral siblings
(`WorldClaim`, `WorldOracleReport`, `WorldCommittedSummary`), and `extra="forbid"` keeps a stored record from parsing as the
other kind. Shared code reads accessors both have (`record_ref`, `seed_ids`, `new_ids`, `record_ids`). The alternative, a
mass rename with a migration, would have rewritten history to make the code tidier.

**The vocabulary was already neutral.** `duplicate_side_effect`, `false_completion_claim` and the verdicts mean the same in
any world, so Job Queue reuses them and adds only what the CRM lacks. That keeps the design rule "only
`false_completion_claim` may call a status wrong" true in both worlds without a second rule.

**Shared cores, not a shared base for everything.** `GatewayCore` holds the call pipeline and both fault boundaries, because
a second copy of those would be a second definition of what a fault means. `WorldBase` and `WorldStore` hold lifecycle,
transactions and the evidence trail. Each world keeps its own tables, tools and verifier.

**A plugin supplies facts, never policy.** No limit, budget, sandbox setting or evidence rule is a plugin's to set.
`verify_world` refuses a report whose verdict disagrees with its own findings, so no world can redefine a verdict.

**One closed list stays closed.** `FaultSpec.operation` is a `Literal`. Widening it to `str` would have been tidier and
would have let a fault target a read tool directly. A third world adds one value.

**`WORLD_TIERS` is not extended.** Registered manifests hash that table. New worlds are development worlds through
`tier_of`, and `make eval-verify` still passes.

## Coupling found (Phase A)

| Area | Before | Class | Done |
|---|---|---|---|
| World create and reset | `World` builds a CRM | Configurable | `WorldBase`, `create_run` |
| Scenario selection | `load_scenario`, one directory | Configurable | `ScenarioBase`, registry lookup |
| Tool registration | `ToolName`, `ARG_MODELS` | Genuinely CRM | Stays; `arg_models()` per world |
| Fault registration | `Literal[create_customer, read]` | Configurable | One value added, checked per world |
| Fault boundaries | Inside `ToolGateway._create`, `_read` | Already generic in meaning | Moved to `GatewayCore` |
| Oracle invocation | `TruthOracle().evaluate` at 2 sites | Configurable | `verify_world` |
| Oracle rules | `world/oracle.py` | Genuinely CRM | Unchanged, behind the plugin |
| Verdict semantics | Inline | Already generic | `derive_verdict` |
| Orchestration | Coordinator | Shared, untouched in shape | One `world` argument |
| Task construction | `mission_prompt`, `Objective` | Genuinely CRM | `mission()`, `objective_wire()` |
| Evidence serialization | Customer fields | Genuinely CRM | Sibling types; CRM bytes unchanged |
| Evaluation fixtures, manifests | CRM worlds | Shared, must not move | Untouched |
| Investigator prompt | "synthetic CRM world", catalog | Configurable | `investigator_subject()`, `capability()` |
| Frontend projections | `customers`, CRM copy | Configurable | `design/world.ts`, additive views |
| Sandbox, journal, ledger, SDK transport | | Shared | Untouched |

## Consequences

- A new world means a plugin, its scenarios and one line in the registry. The coordinator, Oracle path, journal and
  validity checks do not change. `FaultSpec.operation`, `Scope` and the `DEFAULT_WORLDS` table in `external/commands.py`
  each take one new value, and the pages take new tool phrases in `design/sequence.ts`.
- The internal Target Agent stays CRM-only. Its prompts and baseline/hardened comparison are the CRM's, and nothing needed
  it elsewhere, so it refuses other worlds before anything exists. External agents are how a second world is tested.
- Reporting metrics in `RunAssessment.behavior` keep their CRM-era names (`create_calls`,
  `creates_with_client_request_id`) in Job Queue run reports: renaming would change CRM reports. They appear in no page.
- `ClaimView.customer_id` and similar stay in the public API type as empty fields on a queue run. No view shows them.

Rejected: a dynamic plugin loader (nothing needs one, and it is an arbitrary-code path); a generic record store shared by
all worlds (it would flatten the constraints each schema enforces); a new Oracle verdict for validity (validity is about the
experiment, and must never move a verdict).
