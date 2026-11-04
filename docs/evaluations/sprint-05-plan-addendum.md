# Sprint 5 evaluation plan: addendum (registered before this test was run)

_Committed after the held-out paired test and before the test below. The original
[plan](sprint-05-plan.md) stands unedited, and its result stands as it came out._

## Why

The registered per-case metrics failed on the held-out tier: strict 0 of 3, coarse 0 of 3. Across
all 24 held-out answers, though, `hardened` was chosen 0 of 12 times after a PASS and 10 of 12 times
after a VIOLATION. That pattern was found by reading the data, so it is exploratory and proves
nothing by itself.

## Confirmatory test

- **Prediction:** the rate of choosing `hardened` as the next experiment's config is higher after a
  VIOLATION observation than after a PASS observation.
- **Data:** fresh answers only. `make investigator-eval CONFIRM=1 TIER=validation PART=pairs
  REPEATS=4`: the three pair cases, seed world `w-v1`, 12 answers per branch. The held-out data that
  suggested this is not reused.
- **Pass:** at least 8 of 12 after VIOLATION, and at most 2 of 12 after PASS. Answers that ran no
  target count as not choosing `hardened`.
- **Scope:** one specific behavioral shift. Answers share prompts, so they are not independent, and
  no p-value is claimed. Passing would show that this observation changes this choice, not that the
  Investigator adapts well in general. Run once. Failure is reported as failure.
