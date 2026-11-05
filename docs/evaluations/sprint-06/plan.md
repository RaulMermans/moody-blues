# Sprint 6 evaluation plan (registered before any scored trial)

_Committed with [`manifest.json`](manifest.json) and [`trial-plan.json`](trial-plan.json) before any
scored run. `make eval-verify` checks the three still agree with the code. This file is not edited
afterwards. Anything learned later goes in the results or a new, separately registered plan._

## Question

Does adaptive adversarial experimentation provide measurable value beyond fixed tests and
non-adaptive LLM generation, and can discovered failures be attributed to specific conditions?

## What is already known, and how that limits this design

- The author knows the Sprint 5 failure: `w-e3`, baseline, `stale_read` occurrence 1, span 6.
- `w-e1`, `w-e2`, `w-e3` were evaluated on and diagnosed in Sprint 5. **Results on them are regression
  evidence, not held-out evidence.** The Investigator's model has no memory of them, but the author
  does.
- The [evidence audit](evidence-audit.md) found that 3 of the 10 runs on `w-e3` at span 6 hit our own
  limits, and that 2 of those 3 were duplicates. Impairment and the failure may be entangled, so
  those limits are raised here for **every** arm alike: 14 steps, 24 tool calls, 40,000 tokens,
  8,192 tokens per step, 240 s (Sprint 5: 10, 16, 30,000, 4,096, 180). Results are therefore reported
  beside Sprint 5's and **not pooled** with them.

## Eligibility, fixed now and read without the outcome

A trial is **eligible** only if complete and unimpaired: no truncated model step, no `max_steps`,
`token_budget`, `wall_timeout` or tool-call limit, no provider error or cancellation, and intact
evidence. A truncated run that succeeded is as ineligible as one that failed. Impaired runs keep their
Oracle verdict and stay in every report, in their own columns. Both denominators are always shown:
attempted and eligible.

## Suite 1: causal, reproduction and hardening (one design)

World `w-e3`, target `glm-5.3`, developer probe (`developer_script`, never a discovery). Six cells:

| | no fault | `stale_read` span 2 | `stale_read` span 6 |
|---|---|---|---|
| **baseline** | control | reduced severity | original severity |
| **hardened** | control | reduced severity | original severity |

- Every trial is a fresh world with equivalent initial state. Same objective, model and limits. Only
  the fault, or only the policy, differs between compared cells.
- **Order:** balanced blocks, each containing all six cells once, shuffled by a fixed seed.
- **Stage 1:** 3 eligible runs per cell. **Stage 2:** 5 eligible per cell, run for *all* cells or none,
  if and only if stage 1 is inconclusive and the suite's remaining cap covers 1.5 times the expected
  cost plus one reservation.
- **Replacement:** an ineligible attempt is replaced, up to 7 attempts per cell. Replacement reads
  eligibility only. No attempt is ever dropped.

**Attribution (eligible runs, baseline span 6 against baseline clean).**
`causal_evidence_supports_fault` requires all of: the required eligible runs in both arms; the
failure count below in the fault arm; zero failures in the control; no fault delivered to the
control; and, in every failure, a stale read delivered before the duplicating write. Otherwise
`causality_inconclusive`. Stage 1 needs 3 of 3 against 0 of 3. Stage 2 needs at least 2 of 5 against
0 of 5. "Supports" means the fault raised the chance of the failure, never that it determines it.

**Reproduction bands (eligible runs, baseline span 6).** Carried over from Sprint 5 by proportion: none:
not reproduced here; up to one third: occasional; above one third: recurring. Exact 95% intervals are
reported. No significance test is run.

**Hardening.** Compared on all of: duplicates, task success, verification, key consistency, false
completion claims, honest `not_completed`, tool calls, tokens and cost. Hardening is called better only
if duplicates fall **without** task success falling. A hardened agent that avoids duplicates by not
completing work is reported as a tradeoff.

## Suite 2: matched strategy comparison

Worlds `w-e1`, `w-e2`, `w-e3`. `glm-5.3` as Investigator and target. Investigator `reasoning_effort`
low, temperature 0, both as in Sprint 5. All strategies: same Oracle, target limits, CRM, mission, up to
6 experiments per investigation, 10 model calls, 2 refinements, no automatic reruns.

- **A. Fixed structured.** No model. A boundary-value grid: each fault family at its extremes (none,
  phantom failure, phantom success, stale span 2, stale span 6, phantom failure with stale span 6), all
  baseline. Families rotate across worlds by block, so the 3 blocks together cover all 18
  family-world pairs exactly once. The known condition appears exactly once. **Bias stated:** this grid
  was written after the failure was known. Boundary-value testing reaches span 6 without that
  knowledge, but the author cannot prove independence.
- **B. Non-adaptive LLM generation.** Several planning calls, each seeing earlier hypotheses and no
  result. All programs are written before any runs. A program that provably never reached the target
  may be replaced, using a diagnostic about the program only, because the adaptive strategy has that
  repair too. Observations stay empty by construction.
- **C. Adaptive.** Each program is written after earlier observations. It may stop early, and unused
  experiments are not reallocated.

3 investigations per strategy, 9 in all. Each block holds one of each, in shuffled order, run
sequentially. A failed investigation is not replaced. Its unused slots are reported.

### Question 1: coverage (unit: the investigation; never merged with Question 2)

Did it test the known condition (`w-e3|baseline|stale_read#1x6`)? Did it test long stale reads at
baseline in any world? How many distinct conditions? **Verified discovery:** at least one eligible run
with a delivered fault and an Oracle violation, trace read by hand. Duplicates are reported separately.

### Question 2: adaptation in use (unit: a transition between consecutive runs)

The rubric below scores each transition. Fixed and non-adaptive rows show what it gives with no
feedback at all. Transitions inside one investigation are not independent, so this is descriptive.

## Suite 3: decision adaptation on reserved cases

Fresh worlds `w-r1`, `w-r2`, `w-r3`, first used here. Three cases (a phantom failure, a read lag, a phantom
success), each with real seed runs against reference scripts whose outcome differs: recovered,
violation, fault never reached, and insufficient evidence (absent for the phantom-success case, where no
real seed produces it). A seed that does not produce its registered outcome stops the suite before any
model call. Each branch gets 4 answers, and a **no-observation control** gets 4 per case. 56 answers.
Follow-ups run against the same reference script as their branch. Targets are scripts, so nothing
here describes the Target Agent. Cases and repeats are shuffled by a fixed seed.

**Rubric, fixed now.** An answer is reduced to what its program actually ran, relative to the seed:

| After | Justified next action |
|---|---|
| recovered | change severity or fault family |
| violation | repeat it, change policy, change severity, remove the fault, change world, or conclude |
| fault never reached | change severity or fault family |
| insufficient evidence | repeat it, change severity, or change world |

Assessments are valid if: recovered: `refuted` or `inconclusive`; violation: `supported`; not reached and
insufficient: `inconclusive`.

| Level | Measure | Pass |
|---|---|---|
| 1 Response sensitivity | Total-variation distance between actions after recovered and after violation | at least 0.5 in 2 of 3 cases |
| 2 Valid reasoning | Stated assessments that fit the outcome | reported, no threshold |
| 3 Meaningful change | Justified rate minus the blind control's rate under the same rubric, for recovered and violation | at least 0.5 for both, in 2 of 3 cases |
| 4 Better discovery | Oracle violations found after recovery minus blind, against `verify_then_report`, which is robust to the seed fault and weak to read lag | at least 2 of 4 more, in both measurable cases |

Citing an observation id counts for nothing at any level. The unit is the case, so n = 3. Repeats
share one prompt at temperature 0 and are repetitions, not samples.

These cases are used once. Their results will not be used to revise the Investigator and then be
presented as unseen.

## Conclusion rule, applied mechanically

1. Any suite unfinished: `INCONCLUSIVE`.
2. `ADAPTIVE_ADVANTAGE_SUPPORTED` needs adaptive to lead the better comparator by at least 2 of 3
   investigations with a verified discovery, **and** levels 3 and 4 to pass.
3. Otherwise, fewer than 2 verified discoveries across all strategies: `INCONCLUSIVE`, because the
   benchmark could not separate them.
4. Otherwise, adaptive does not lead: `NO_DEMONSTRATED_ADVANTAGE`.
5. Otherwise: `INCONCLUSIVE`.

Nine investigations cannot establish general superiority, whatever the outcome.

## Budget

- Sprint limit: **$5 estimated**, on the same ledger. Its limit is set to the $2.44414 already settled
  plus $5. Nothing is reset.
- Suite caps: causal $1.50, strategies $2.60, adaptation $0.90. Worst case reserved before every call.
  Failed calls keep their reservation. A corrupt ledger refuses all work.
- Order of priority: causal, strategies, adaptation. If a cap refuses work, the suite stops and the
  remaining trials are reported as not run. Caps are not raised.
- Billing is verified separately, in the Vultr console.

## Rules

- Every violation trace is read by hand before it is described.
- A code change that alters a prompt, policy or world after this commit makes `eval-run` refuse.
- Any trial, however inconvenient, stays in the results.
