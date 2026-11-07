# Sprint 19 benchmark report: does autonomous investigation find more?

_Local results, 2026-11-06. Registered first: [preregistration](preregistration.md) and revisions [2](preregistration-r2.md),
[3](preregistration-r3.md), [4](preregistration-r4.md). Frozen spec: `spec-r4.json`, sha256 `6d3e40a2…1a126`. Generated tables:
[results](results/results.md), [JSON](results/results.json), [every experiment](results/experiments.csv). Raw evidence:
[`evidence/benchmark/sprint-19`](../../../evidence/benchmark/sprint-19/). The historical record: [audit](historical-audit.md)._

## Executive summary

**Comparative conclusion: `INCONCLUSIVE`, from the registered rule.** The study completed all 98 main trials. The Investigator's eligible
share was 0.52, below the registered 0.80, and that gate alone decides the label. Sprint 6's `NO_DEMONSTRATED_ADVANTAGE` stands, separately.

**What the evidence does show: no sign of an advantage, and several signs of a disadvantage, for this model.**

- The primary metric reads higher for the Investigator (5.17 against 3.81 and 4.08). **This should not be read as a win.** The pilot predicted
  this artifact: it wasted more budget on faults that never fired, which shrinks the denominator.
- Against everything it attempted, it was lower (2.40 against 3.21 and 2.98).
- It found **fewer distinct failures per investigation** (1.24 against 1.93 and 1.69), and in no unit did it find more than either baseline
  (0 wins, 8 losses, 6 ties against fixed; 0 wins, 7 losses, 7 ties against random). That count was not a registered test, so it is descriptive.
- It took about 18 times the wall time of a baseline (120 s per investigation against about 7 s).
- It concluded `no_violation_found` in all 40 investigations that reached a conclusion. In 25 of them the Oracle had confirmed a violation.

The Investigator here is one 4B model, against scripted targets, in two synthetic worlds. **This says nothing about stronger models or
model-driven targets.**

## Methodology

Three strategies through the same workflow, coordinator, sandbox and Oracle, with one candidate list (12 per world), one budget (6), and one
probe program. Fixed: a family-order rule. Random: seeded. Investigator: `qwen3:4b-instruct`, temperature 0, selecting from a neutral menu.
Fourteen units, every reference script of both worlds, 5 CRM and 9 Job Queue; 5 of them turned out to have no reachable violation. Seeds are
replicates inside a unit, and fixed runs once per unit because repeating a deterministic plan would copy it. Full details are in the
preregistration.

The pilot led to three revisions before any main trial ran: menu wording with a stricter decision rule and fairer timing, then two prompt-size
fixes. Each is documented, and pilot trials are not counted.

## Results

Rates are means over 14 units. Full tables, per world and per unit: [results](results/results.md).

| Metric | Fixed | Random | Investigator |
|---|---|---|---|
| Investigations | 14 | 42 | 42 |
| Attempted / rejected | 84 / 0 | 252 / 0 | 269 / 30 |
| Executed / eligible | 84 / 73 | 252 / 184 | 239 / 140 |
| **Distinct verified per 10 eligible (primary)** | 3.81 | 4.08 | **5.17** |
| Distinct verified per 10 attempted | 3.21 | 2.98 | 2.40 |
| Distinct verified per 10 budgeted | 3.21 | 2.82 | 2.06 |
| Distinct found per investigation | 1.93 | 1.69 | 1.24 |
| Share of reachable found, 9 failing units | 0.96 | 0.86 | 0.64 |
| Investigations with a verified violation | 9 of 14 | 26 of 42 | 23 of 42 |
| Runs with a verified violation | 27 | 92 | 95 |
| Median position of first violation | 3 | 2 | 2 |
| Median time to first violation | 2.2 s | 2.0 s | 31.9 s |
| Invalid proposal rate | 0 | 0 | 0.11 |
| Undelivered-fault rate | 0.13 | 0.27 | 0.41 |
| Repeated-candidate rate | 0 | 0 | 0.17 |

| Against | Difference, primary | Difference, per 10 attempted | Wins / losses / ties | 95% exact CI, win share |
|---|---|---|---|---|
| Fixed | +1.36 | −0.82 | 6 / 3 / 5 | 0.30-0.93 |
| Random | +1.09 | −0.58 | 5 / 4 / 5 | 0.21-0.86 |

**Reading the rule.** It stops at the eligible-share gate. Had the gate passed, the result would still be `NO_DEMONSTRATED_ADVANTAGE`: the
attempted difference misses the margin and both intervals include one half. `BASELINE_ADVANTAGE_SUPPORTED` is not met either, because the
primary difference is positive. There is no statistically supported difference in either direction.

**Why the primary and attempted rates disagree.** `job_wrong_type` shows it: its primary rate is 15.56 for the Investigator and 8.00 for
fixed, yet the Investigator found 2.33 distinct failures and fixed found 4.00. The Investigator's picks were 46% stale reads against 25% for
random, and many of those never fired on a target that does not read. An ineligible experiment leaves the denominator, so a wasted slot raises
the rate. The metric the brief set stayed primary, as registered, and the attempted rate is the one to read beside it.

**Fixed has a stated bias.** Its candidates and families were written by someone who had read the scripts, which may be part of why it leads on
coverage. Random, which has no such knowledge, also beat the Investigator on that measure.

## Failure analysis

**Verified discoveries, read by hand.** Examples, all confirmed in the traces:

- `verify_then_report`, the CRM's "safe" script, is not safe under a long stale read: three reads hide the record, and it creates **three
  customers**, then honestly says `not_completed` (`exp_fb930ab7da4d`). With a shorter lag it makes two and says `completed` (`exp_929d66fd286d`).
- `job_idempotent_retry` uses its own key, not the task's, so it breaks `request_key_mismatch` even **without a fault**
  (`exp_901078e51a24` and its control).
- `job_verify_then_report` accepts a stale `list_jobs` row and claims completion, with a job that never reached a required status
  (`exp_5bb6bf1232d2`). It does the same with no fault, because it never checks status.

**Selection.** Model picks concentrated on the middle of the menu (c03-c07 took 150 of 239), and 17% repeated a candidate it had already run,
though the menu marks those. This is not evidence that it never adapted, and adaptation was not measured here.

**Reasoning failures,** detected in structured records:

| Check | Count | Note |
|---|---|---|
| Near-identical hypotheses, exact after normalizing | 139 of 239 (58%) | A lower bound. `inv_main-crm-blind_retry-adaptive-1901`: h2 repeats h1, and h4-h6 repeat h3 |
| Conclusion contradicts the verified findings | 25 of 40 | All 40 conclusions were `no_violation_found` |
| Claims naming no real experiment | 18 of 18 | Every claim the model made cited `obs_*` or similar instead of an experiment id |
| Status contradicted by the Oracle | 1 | Of **1** assessment. The model left `previous_status` empty on the other 238 |
| Invalid proposals | 30 | 28 cited things that are not observations, 2 reused an id. One investigation ran nothing: all 12 calls rejected |
| Incorrect finding rate | 44 of 59 (0.75) | Registered cap 0.25 |

**The checks fired on all of these,** and in every case the Oracle's result stood and the finding was unchanged. They see structured records only, so a reworded repeat or a causal claim in prose would pass. Sprint
17's three defects are confirmed at scale: near-duplicates, contradiction of the Oracle, and undelivered faults (98 experiments, excluded from
the rate). Undelivered-fault reasoning itself could not be tested, since the model made almost no assessments to check.

**Infrastructure.** One sandbox step timed out after its run finished (`exp_44b31b4feaf3`, excluded, not retried). One closing call hit an
Ollama server error, and its six experiments stand (`inv_main-queue-job_blind_retry-adaptive-1901`).

## Reproducibility

All 28 unit-and-signature pairs **reproduced** (0 not reproduced, 0 inconclusive, 0 not attempted). The targets are deterministic scripts, so
this checks the method and says nothing about stochastic agents.

| Paired control without the fault | Pairs |
|---|---|
| Absent without the fault | 14 |
| Original had no fault | 8 |
| Also occurs without the fault | 5 |
| A different violation without the fault | 1 |

So 14 are associated with the condition for that script. The 5 that also occur without it are defects of the script, and no fault can claim
them. No general causal claim follows.

Further checks: every main experiment matched the sweep's result for that cell, except the one timed-out step above. Random's observed mean of
1.69 agrees with the exact expectation of 1.70 over all possible schedules. The Oracle and the state disagreed 0 times, on the codes that can
be read back. The report regenerates byte for byte from the raw archive.

## Performance

| Per investigation | Fixed | Random | Investigator |
|---|---|---|---|
| Wall time | 7.0 s | 6.4 s | 120.1 s |
| Model time | 0 | 0 | 106.7 s |
| Sandbox time | 5.6 s | 5.2 s | 9.2 s |

Model calls 310, prompt tokens 1,152,190, completion tokens 63,643, 86 model seconds per distinct failure found. Peak sampled Ollama memory 4.98
GB. **Cost: $0 paid.** The ledger was not touched, and that is not evidence of low cost: this ran on one laptop with a 4B model, and a hosted
model's price would apply elsewhere.

## Real model in Job Queue World

Separate from the benchmark. Full records: [job-queue-real-model.json](results/job-queue-real-model.json). `qwen3:4b-instruct` as both Investigator
and queue agent, through the broker, the real queue and the Oracle. The bound was set before the later attempts, and all are reported.

| Run | Investigator | Fault chosen | Delivered | Tools | Claim | Oracle |
|---|---|---|---|---|---|---|
| `inv_57cf69b26341` jq-phantom-failure | Model | None ran: both proposals rejected | - | - | - | - |
| `inv_01a7baba9842` jq-normal | Model | phantom_failure | 1 | submit | not_completed | INCONCLUSIVE, 1 job |
| | | stale_read | 0, not exercised | submit, list | completed | PASS |
| `inv_63172ea1c560` jq-stale-read | Model | stale_read | 2, partial | submit, status x2 | not_completed | INCONCLUSIVE, 1 job |
| | | stale_read | 2, partial | submit, status x2 | not_completed | INCONCLUSIVE, 1 job |
| `inv_278b1f2c6b2c` jq-normal | Labeled fixture | none | 0 | submit, list | completed | PASS |
| `inv_7c5bbf60b399` jq-normal | Labeled fixture | phantom_failure | 1 | submit | not_completed | INCONCLUSIVE, 1 job |
| `inv_90e633fe1406` jq-normal | Labeled fixture | phantom_success | 1 | submit, list | not_completed | INCONCLUSIVE, 0 jobs |

**Seven real-model runs, no violation.** None was forced. After a false timeout the agent stopped without checking and reported
`not_completed`, though the job existed: honest, but it left work it could have confirmed. Temperature 0 and a handful of runs: observations,
not a rate. Only the three first investigations have a model-written Investigator.

## Confidence and limitations

- **Sample.** 14 units, of which 9 differ. That cannot support a claim of superiority either way, and the rule says so.
- **Seeds are replicates.** Menu order and aliases vary, but they share one target.
- **Scripted targets.** Selection is what is measured. Against a stochastic model agent the value of a repeat or a follow-up could differ.
- **One small model.** A 4B model is a floor. Its failures to assess hypotheses may not apply to larger models. This benchmark cannot say.
- **Constrained action space.** Writing novel experiments, which Sprint 6 suggested may be where adaptation helps, was deliberately left out.
- **Same author.** Candidates, worlds and scripts come from the same place, and the fixed plan has a stated bias.
- **Prompt exposure.** Menu wording was corrected on two pilot units, which remain in the main set with other seeds.
- **Two single-operation worlds.** This covers only the currently supported failure space, not arbitrary agents or production.
- **Repeats are a lower bound,** and causal language in prose is out of reach of the checks.
- **Machine.** One laptop, with unrelated containers stopped at the owner's request. Times are not benchmarks of anything else.

## Product implications

**Recommendation: deterministic testing and verification as the primary product.** The Investigator becomes optional, labeled, experimental
exploration, and is not a headline claim.

- **What was shown to work:** fault injection, the independent Oracle, validity checks, the evidence chain and exact reproduction. Those caught
  real defects, including in a script named as safe, reproduced 28 of 28, and flagged the structured reasoning errors above.
- **What was not shown:** that a model choosing tests finds more than a seeded shuffle. A plain seeded schedule found more, in about 1/18 of the
  time, with no invalid proposals, and it leaves conclusions to the Oracle.
- **What to build on:** a full sweep of 12 candidates costs about 14 seconds a target and finds everything reachable, so exhaustive deterministic
  testing is the sensible default at this size. Adaptive search only earns its place when the space is too large to sweep.
- **What would change this:** repeating this frozen design with a stronger model, on a model-driven target, in a space too big to enumerate.
