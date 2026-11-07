# Sprint 19 preregistration, revision 2

Written after the revision 1 pilot and before any main trial. Revision 1 stands as it was frozen, with its pilot on the record. The frozen
form is [spec-r2.json](spec-r2.json) with [plan-r2.json](plan-r2.json). Everything in [revision 1](preregistration.md) carries over except:

## Why

The pilot (2 units, 6 trials, never counted) ran every strategy and its evidence verified. It also found three faults in the method, which
is what it was for.

| # | Found | Evidence | Correction |
|---|---|---|---|
| 1 | The menu never said what an observation id was. The model cited `c04` and `w2` as observations, was rejected, and in one trial ran nothing: 12 of 12 proposals rejected, on `motivated_by` | `inv_pilot-queue-job_single_read-adaptive-1801`, `inv_pilot-crm-blind_retry-adaptive-1801` | `MENU_PROTOCOL` now says these fields hold ids such as `obs_1`, are empty before the first experiment, and that `hypothesis_id` is `next_hypothesis_id` |
| 2 | Primary metric artifact. Eligibility shrinks the denominator, so wasting budget on undelivered faults can raise the rate: random found 2 at 2 eligible (rate 10.0), fixed found 3 at 5 eligible (rate 6.0) | `pilot-crm-blind_retry-*` | The primary metric is unchanged. A claim of advantage for either side now also needs the same margin per 10 attempted, which has no such effect. This only makes a claim harder |
| 3 | Time to first violation counted sandbox time alone, which favored the Investigator | analysis code | It now includes the model time spent up to that choice |

## What was deliberately left alone

- The model reusing `h3` after `h4` is model behavior, and it stays. No wording was added to steer which candidate to pick.
- Candidates, units, seeds, budget, limits, the model and thresholds are unchanged. No main trial has run, and the pilot units remain never
  counted.
- The wording in correction 1 was tuned on a pilot unit, so that much of the prompt has seen those two units. It says nothing about any
  failure or any candidate.

The pilot is rerun under this revision with seed 1802, in a new directory. Revision 1's raw pilot is preserved.
