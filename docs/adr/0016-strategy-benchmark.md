# ADR 0016: A strategy benchmark on the existing runtime

**Status:** accepted, Sprint 19.

## Context

Sprints 16 to 18 showed the Investigator runs. They did not show it finds more than a simpler strategy. Sprint 6's registered study answered
`NO_DEMONSTRATED_ADVANTAGE` on nine paid investigations, and its manifest is CRM-only and hashes `WORLD_TIERS`.

## Decision

- **Reuse the runtime.** Fixed and randomized are the workflow's `fixed_schedule`. The Investigator is the workflow's adaptive loop. There is
  no second Investigator, no benchmarking agent, and no new evidence format.
- **One action space.** `ExperimentMenu` gives the model the same validated candidates the baselines draw from. It picks one instead of writing
  a program, and trusted code runs the same probe. Writing novel experiments is a separate capability that this comparison leaves out.
- **Equal budget.** With a menu, the model must spend all six slots before it can conclude.
- **Neutral menus.** Scenario ids can name their conditions, so the model sees aliases. Records keep real ids.
- **Bounded revision.** One revision per slot, with fixed advice. No open-ended self-reflection, and the workflow's rejection path is the
  whole of the evaluator-optimizer.
- **A separate registration.** `evaluation/benchmark/` freezes its own spec and plan and journals with the existing hash chain, and is
  labeled `local_ollama`. It does not touch the Sprint 6 manifest, and the two studies are never combined.
- **Metrics from evidence.** `analysis.py` reads each run's evidence file and verifies its hash. Nothing the model wrote feeds a metric.
- **The target policy is the unit.** Seeds are averaged inside a unit. The only interval is the exact one on win share, used as a threshold.

## Consequences

- A strategy is measured against scripted targets, which removes target noise and makes results reproducible, but says nothing about
  model-driven agents.
- `ProposalRecord.candidate_id` is new and left out when absent, so old records stay byte-identical. A chosen candidate keeps
  `developer_script` authorship, because the model did not write that program.
- Menu prompts are compact JSON. Other prompts are unchanged, so registered hashes still hold.
- `bench-*` refuses canonical artifacts.
