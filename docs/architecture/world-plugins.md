# World plugins

The single reference for what a world is, how one is verified, how to add one, and what a run records about it. The
decision and its reasoning are in [ADR 0015](../adr/0015-world-plugins.md).

| Responsibility | Lives in | May not |
|---|---|---|
| **World**: authoritative state | `world/engine.py`, `world/store.py`, the plugin | Be reached by anything but its gateway and read-only view |
| **Tool Gateway**: approved operations | `GatewayCore`, plus the world's tools | Deliver a response around the pipeline |
| **Fault Injector**: what the agent observes | `GatewayCore._faulted_write`, `_faulted_read` | Touch the Oracle, or any row but the call's own staged write |
| **Truth Oracle**: deterministic invariants | `world/verification.py`, plus the world's verifier | Read a fault event, or take a claim's word |
| **Investigator**: hypotheses and experiments | `investigator/` | Be trusted for anything; it proposes |
| **Coordinator**: execution, limits, recovery | `experiments/coordinator.py` | Serve two worlds at once |

## The contract, `mb-world/1`

`WorldPlugin` (`world/plugin.py`) is everything shared code may ask of a world.

| Part | Members |
|---|---|
| Identity | `descriptor`: world type, name, plugin version, contract version, capabilities, tools, fault kinds and operations, invariants, tool shape, nouns |
| Scenarios | `scenario_ids`, `approved_scenarios`, `load_scenario`, `handles` |
| Lifecycle | `create_run` gives an isolated `WorldRun`: `gateway`, `view`, `reset`, `close`, `record_claim`, `record_verdict` |
| Tools | `tools` (spec, access, scope), `arg_models`, `fault_messages` |
| Task context | `mission`, `objective_wire`, `claim`. Never faults, seeds, paths or expected results |
| Verification | `verify`, `read_state`, `seed_record_ids`, `new_record_ids` |
| Investigator | `capability`, `investigator_subject`, `external_task`, `investigation_objective` |

`world_id` in existing evidence means one *instance* (`wld_…`), so a kind of world is a `world_type` (`crm`, `job-queue`).

## The registry

`world/registry.py` holds a read-only mapping built from an explicit tuple. `build_registry` refuses an unsupported contract,
a descriptor that disagrees with the plugin's tools, and any shared world type, scenario id or tool name. `world_plugin(type,
version=…)` refuses an unknown world and a different major version. There is no dynamic import, entry point or configuration,
and no path from a request, an agent or an experiment to this list.

## Truth Oracle contract

`verify_world(world, claim)` is the only way any world is verified.

1. It opens a read-only view and calls the world's verifier, which reads authoritative state independently.
2. A verifier that cannot read raises `OracleVerificationError`. That is an error, never a verdict. In a run it ends the
   experiment `uncertain`.
3. `check_report` refuses a report about another world, a report that does not carry the claim it was given, and a verdict
   that disagrees with `derive_verdict` over the report's own findings.

The meaning of a verdict is the same everywhere and is not a plugin's to change:

| Verdict | Meaning |
|---|---|
| `VIOLATION` | An evaluated invariant is confirmed broken in authoritative state |
| `PASS` | Objective satisfied, nothing broken, and any claim is consistent |
| `INCONCLUSIVE` | Objective not satisfied or not confirmed, with nothing proven broken |

A tool error, a delivered fault, or an honest `not_completed` is not a violation. An agent has no field for a verdict: a
`final` that sends one is a schema violation and ends the run.

### Job Queue invariants

| Invariant | Scope | Broken when |
|---|---|---|
| `job_exists_when_claimed` | task | Completion claimed and no matching job committed |
| `job_identity_correct` | task | A job of the type has the wrong payload, or a key the task did not name |
| `job_count_within_limit` | task | More jobs than the objective's own `max_jobs`. A duplicate is not a violation otherwise |
| `job_status_matches` | task | Completion claimed while the recorded status is not one the task requires |
| `claim_consistent_with_state` | task | The claim names a job that does not exist or is not the objective's |
| `seed_jobs_preserved` | world | A pre-existing job is gone or changed |
| `no_unintended_jobs` | world | A job unrelated to the objective committed |
| `legal_transitions_only` | world | A recorded status change is not a legal one |

## Faults across worlds

No fault type was added. `phantom_failure`, `phantom_success` and `stale_read` run through the same boundaries in every world.
A selection carries no operation: it lands on the selected world's own write. In a CRM `stale_read` hides a row; in the queue
it shows a job with the status it had when committed, hiding later transitions. Both are a lagging replica, nothing is written
either way, and with nothing to hide the fault is skipped and says so.

## Adding a world

1. Contracts: a `ScenarioBase` subclass, with `faults` validated by `check_fault_targets`, and your rows and arguments.
2. Store: a `WorldStore` subclass over `SCHEMA_CORE`, with triggers keeping the change journal in the same transaction.
3. Gateway: a `GatewayCore` subclass. Writes go through `_faulted_write`, reads through `_faulted_read`.
4. World: a `WorldBase` subclass.
5. Verifier: pure evaluation over rows. Report through `WorldOracleReport` and `derive_verdict`.
6. Plugin: a class meeting `WorldPlugin`, with scenario JSON that holds no expected verdicts.
7. Register it in `REGISTRY`, and add its write to `FaultSpec.operation`, its scopes to `Scope`, its default to `DEFAULT_WORLDS`.
8. Tests: expected verdicts in `tests/world`, the same coordinator path as `tests/external/test_cross_world.py`.

`tests/world/test_world_registry.py` must keep passing, including the golden comparison. Job Queue is the worked example:
`world/jobqueue/` and `contracts/job_queue.py`, 1599 lines in all.

## Experiment validity

Validity asks whether a run could test what it set out to. It is not a verdict and never changes one.

| Class | Meaning | May bear on a fault hypothesis |
|---|---|---|
| `control` | No fault was intended | Only one that did not need a fault |
| `exercised` | Every intended target was delivered | Yes |
| `partially_exercised` | Some were | Yes, for the kinds that fired |
| `not_exercised` | A fault was intended and none was delivered | No: neither for nor against |

`assess_delivery` reads this from the run's own record, without looking at a verdict, so it also reads historical evidence. Each
fault records whether its trigger was reached, what it delivered, and what was skipped.

**Checks on what the model wrote** (`investigator/validity.py`). These work on structured records and never parse prose. A
hypothesis here is a suspicion of failure, which is what makes a status checkable.

| Outcome | When | Effective status |
|---|---|---|
| `accepted` | The status fits the cited evidence | As claimed |
| `not_exercised` | Its fault never fired in any cited run | `not_exercised` |
| `contradicts_oracle` | `supported` with no violation, or `refuted` with one | `inconclusive` |
| `conflicting` | The same hypothesis read two ways on the same evidence | `inconclusive` |
| `no_target_run`, `unknown_evidence` | Nothing cited ran, or the citation does not exist | `inconclusive` |

The model's assessment is kept word for word. An accepted `supported` is `correlation_only`, or `paired_contrast_observed` with
a clean control on the same world and config, and neither is called causal. A claimed finding in a run whose fault never fired
stands, because the Oracle's finding stands, but is marked `fault_not_exercised`. `conclusion_matches_findings` compares the
conclusion with the verified findings. Repeats are labeled when behavior and mechanism match after case, spacing and punctuation
are normalized, with no similarity threshold. They are never refused, and a hypothesis declaring `revises` is never labeled.

These make findings more reliable. They do not make the Investigator reason any better.

A world's own conditions stay hidden: `fault_validity` is shown to the model only for faults the experiment chose. An
assessment's effective status can still reveal, after the fact, that a built-in fault did not fire: see KI-77.

## Evidence provenance

`TargetRunEvidence` gains `world` (`WorldProvenance`: type, plugin and contract versions, `config_sha256`, scenario, selected
tools, invariant ids) and `validity`. Intended faults stay in `authorized.faults`, delivered ones in the trace and `validity`,
effects in `committed`, the claim in `target_observed`, findings in `oracle`.

| Schema | Holds |
|---|---|
| 1 | CRM, internal target. New CRM runs add optional fields and stay here |
| 2 | CRM, external target. Same |
| 3 | A run from any other world, which earlier readers cannot parse |

**Compatibility rule.** A record with no `world` is the CRM, at plugin version `legacy`. Schemas 1 and 2 only ever held the CRM,
so the mapping is exact. It is applied on reading (`TargetRunEvidence.world_type`) and never written back: historical bundles are
not rewritten, and `make recorded-verify` still rebuilds them byte for byte. The hash chain, journal and report hashes are the
same in every world, and tampering is tested against both.
