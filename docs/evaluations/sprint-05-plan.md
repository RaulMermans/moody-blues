# Sprint 5 evaluation plan (registered before the evaluation tier was run)

_Committed before any run against `w-e1`, `w-e2` or `w-e3`. Results go in
[sprint-05-investigator.md](sprint-05-investigator.md); this file is not edited afterwards._

## Questions

1. Does the Investigator change its next decision because of what it observed?
2. Do adaptive investigations do better than fixed tests or one-shot generation here?

## Paired counterfactual (Question 1)

- Tier `evaluation`, seed world `w-e3`, the three `PAIR_CASES`, 4 answers per branch
  (`REPEATS=4`). Targets are reference scripts, so nothing here describes a target agent.
- **Primary metric (strict):** both branches internally identical in decision, world, config and
  faults, and no answer shared across branches. Validation scored this 1 of 3.
- **Secondary metric (coarse):** the same test on world and config only. It was added after
  seeing the validation result, so a pass on validation is not evidence; this run is its test.
- Adaptation is claimed only for cases that pass. No case is dropped.

## Strategy comparison (Question 2)

- Tier `evaluation`: `w-e1`, `w-e2`, `w-e3`. `glm-5.3` as Investigator and target. 2 trials per
  strategy (`EVAL_TRIALS=2`), run once. Same 3-experiment budget and reproduction rule.
- **Fixed:** each world as built, baseline policy, developer probe. Chosen before any result.
- **One-shot:** all programs written before any result is available.
- **Adaptive:** each program written after earlier observations.
- **Primary metric:** Oracle-confirmed violations on the live target with a fault delivered.
- **Secondary:** reproduced violations, distinct conditions, shortfalls, unsupported claims,
  rejections, tokens, latency and estimated cost.
- Six investigations is a small sample. It can show a difference worth following up; it cannot
  establish superiority, and this report will not claim it.

## Rules

- Every violation trace is read by hand before it is described.
- World changes after this commit invalidate the run and must be stated.
- Budget: at most about $1.50 estimated, inside the $5 sprint limit.
