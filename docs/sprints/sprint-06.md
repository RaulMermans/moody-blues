# Sprint 6: Scientific validation, causal attribution and benchmarking

- **Date:** 2026-11-05
- **Branch:** `sprint/06-scientific-validation`, from Sprint 5 HEAD `cfe74f5`. Not pushed.
- **Outcome:** `ACCEPTED` locally. All eight checkpoints pass, some with stated limits. GitHub Actions has not run on this branch.
- **Conclusion:** `NO_DEMONSTRATED_ADVANTAGE`, from the registered rule.

## Goal

Answer: does adaptive adversarial experimentation provide measurable value beyond fixed tests and
non-adaptive LLM generation, and can discovered failures be attributed to specific conditions?
Results: [report](../evaluations/sprint-06/report.md). Design:
[evaluation.md](../architecture/evaluation.md), [ADR 0006](../adr/0006-registered-evaluation.md).

**Answer:** adaptive showed no advantage in this benchmark: fixed 2 of 3 investigations, adaptive 1 of 3,
non-adaptive 0 of 3. One failure was attributed to its condition, with small samples. The known
duplicate was not. Adaptive alone found the most repeatable failure, which is one event, not a result.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C6-A Evidence hygiene | **PASS** | [Audit](../evaluations/sprint-06/evidence-audit.md): 52 live Sprint 5 runs reclassified; eligibility kept apart from Oracle truth |
| C6-B Matched comparisons | **PASS**, with a stated bias | Same worlds, faults, severity range, limits and budget, registered at `4f161cb`. The fixed grid was written after the failure was known |
| C6-C Causal controls | **PASS** | Known duplicate `causality_inconclusive`. False completion `causal_evidence_supports_fault` at 3 of 3 against 0 of 3. A vacuous arm was caught and not claimed |
| C6-D Reproducibility | **PASS** | Known duplicate 0 of 5 eligible, not reproduced here. False completion 4 of 4 eligible, recurring |
| C6-E Adaptive value | **PASS** as an evaluation; the result is negative | Fresh worlds. Level 1 passed; levels 3 and 4 failed |
| C6-F Hardening | **PASS** | Better on the `w-e1` full condition, no measurable effect on `w-e3`, costs more when nothing goes wrong |
| C6-G Scientific reporting | **PASS** | Raw counts, exact intervals, stated units, JSON, Markdown and CSV. 114 of 114 recorded evidence hashes match; 5 rerun records have no stored hash |
| C6-H Regression and safety | **PASS** (real Docker and Playwright, on final code) | [Validation](../testing/validation.md) |

GitHub CI for this branch: **NOT_RUN**. Pushing needs the owner's approval. The brief said Actions had
never run, but it had: PR #6 passed CI on `cfe74f5`, as did its merge to `main`, including Docker and
Playwright jobs.

## Problems found and fixed

1. **Impaired runs looked like clean samples** (KI-31). Eligibility now sits beside the verdict and is
   read without the outcome.
2. **A truncated rerun counted as `not_reproduced`.** It now counts as untested.
3. **A report could say no violation was found** beside an impaired one (KI-32).
4. **A failed provider request settled at measured tokens.** It now keeps the full reservation. The one
   affected Sprint 6 run got an append-only $0.3785 adjustment. Sprint 5's single provider-error run was
   left as booked.
5. **The mechanism check counted a rolled-back write as real**, which would have wrongly failed the
   false-completion case. Caught before its study. No registered result depended on it.
6. **A control whose fault never fired looked like evidence.** Exposure is now shown (KI-35).
7. **`Strategy.ONE_SHOT` was described as one call.** It is several, and reports call it non-adaptive.
8. **Non-adaptive runs could not replace a program that never ran,** though adaptive runs could. An
   opt-in repair closes that gap, and planning still sees no observation.

An existing test (`test_the_one_shot_strategy_gets_no_refinement_from_results`) failed against the
repair. It protected valid Sprint 5 behavior, so the repair was made opt-in and the test stands.

## Design weaknesses, kept on record

- **The transition rubric saturated** (14 of 15, 15 of 15, 14 of 14), so it cannot separate strategies.
- **`stale-only` and `reduced` tested less than intended** at baseline, so no interaction is claimed.
- **Three studies' worth of decisions rest on 3 to 5 runs per cell.**

## Environment incident

The repo is on an iCloud-managed Desktop, and the disk is 97% full. macOS evicted files while the sprint
ran, including `.venv`, source, `.env`, journals and evidence, and 715 git files. Reads stalled, and git
crashed with SIGBUS on evicted objects, leaving stale locks and one half-applied reset (KI-34). Nothing
was lost: `git fsck` is clean, journal chains verify, and all 114 recorded evidence hashes match. Live suites ran from an
isolated copy with the ledger and evidence in place.

## Budget

Sprint 6 used 1,903,319 tokens: **about $3.96 of the $5 limit** at assumed ceiling prices, including
the adjustment above. Project total about $6.90 of the $200 credit. **Confirm actual billing in the
Vultr console.** The estimate is not a provider figure.

## Remaining risks

- One model in both roles, one provider, one author, small samples. Provider drift cannot be excluded.
- The false-completion failure is tested only in `w-e1`, which has an identical seed record.
- Shared kernel; no gVisor. Target Agent still runs in the trusted process.
- Project files on iCloud remain exposed to eviction until moved or until disk space is freed.

## Readiness for Sprint 7

Ready to build on, once the repo is off iCloud or the disk has room. Suggested first steps:

1. Register a larger test of whether adaptation reliably finds the false-completion failure. Sprint 6
   saw it once in 3 adaptive investigations and never without feedback.
2. Isolate stale reads properly, with an occurrence that fires in `w-e1`, and test a world with no
   identical seed record.
3. Add a second target model, since `glm-5.3` is in both roles.
4. Replace the transition rubric with one that can separate strategies.
5. Decide whether `completed` with a disclosed duplicate should be its own claim class.
