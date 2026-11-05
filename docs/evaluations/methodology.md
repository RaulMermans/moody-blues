# Evaluation methodology

Three achievements are counted separately, because they are different:

1. **Generated:** a model wrote a program that ran.
2. **Adaptively selected:** what it chose depended on what it observed.
3. **Discovered:** a target run broke an expectation, confirmed by the Oracle.

Selecting a known fault is never a discovery.

## World tiers

`development` worlds have legible names and serve fixtures and demos. `validation` worlds (`w-v*`)
are used while tuning. `evaluation` worlds (`w-e*`) are reserved and run once, after their plan is
committed. Held-out worlds have neutral ids and titles and no description. Expected outcomes for
reference scripts live in `tests/world/test_investigation_worlds.py`, and no expected outcome exists
for any model. Each hard world is shown to be winnable by a script that verifies the returned id.

## Paired counterfactual

Does an observation change the next decision?

1. A fixed first experiment runs against two reference executors that really behave differently.
2. The model decides from two prompts that differ only in that observation (checked).
3. Each branch is asked several times, because temperature 0 is not deterministic here.
4. Follow-up programs are executed, and what they actually did is compared.

**Strict:** both branches internally identical, and no answer shared across them. **Coarse:** the
same on world and config only. Differences between branches count only against the noise inside
branches. References cost nothing, and these results describe the Investigator, not a target.

## Strategy comparison

Fixed, one-shot and adaptive share worlds, experiment budget, target model and reproduction rule.
One-shot writes every program before any runs, in separate calls so that the call budget is
comparable. Model, target and sandbox costs are tracked separately.

## Reading a violation

Every violation trace is read by hand before being described. The first live "violation" in this
project was an agent declining, openly, to duplicate an identical record, with no fault delivered,
while the Investigator credited the faults. The check: did a fault fire, and does the trace show
the mechanism claimed?

## Limits

Sample sizes are small. A difference here is a reason to run more, not a demonstration of
superiority. The worlds were designed by the same author as the Investigator, and the Investigator
and target are the same model.

## Sprint 6: registered evaluation

Earlier sections describe Sprint 5 and stand as its record. From Sprint 6, comparisons follow a
frozen [manifest](sprint-06/manifest.json) and [plan](sprint-06/plan.md). What changed:

- **Tiers.** `evaluation` worlds are used up: results on them are regression evidence, not held-out
  evidence. `reserved` worlds (`w-r1`-`w-r3`) are fresh and used once.
- **Matched conditions.** Strategies share worlds, faults, severity range, target limits and experiment
  budget. Coverage and adaptation are separate questions with separate units.
- **Eligibility.** Rates use complete, unimpaired runs, decided without reading the outcome. Attempted
  counts and impaired results are always shown beside them.
- **Attribution.** A delivered fault is exposure. Support for a causal effect needs a registered
  contrast against a clean control.
- **Adaptation.** Scored on what follow-ups ran, against a no-observation control, at four separate
  levels. Citations count for nothing.
- **Units.** Tables state their unit. Repeats of one prompt and transitions inside one investigation
  are not independent. Intervals are exact, and no significance tests are run.

