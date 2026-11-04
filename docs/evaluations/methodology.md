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
