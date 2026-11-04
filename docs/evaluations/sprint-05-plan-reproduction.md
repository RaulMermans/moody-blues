# Sprint 5 evaluation plan: reproduction rate (registered before these runs)

_Committed before any of the runs below._

## Why

Adaptive investigation `inv_4e32358d2ff9` produced a live `duplicate_side_effect` in
`exp_7867af43c17c` (`w-e3`, baseline, `stale_read` occurrence 1, span 6). Its one automatic rerun,
`exp_ecbb08fb9e12`, did not reproduce it. One failure in two tries is not a rate.

## Test

- Rerun the original generated program unchanged, exactly **6 times**, each in a fresh world:
  `make investigator-repro EXPERIMENT=exp_7867af43c17c RUNS=6 CONFIRM=1`.
- All 6 are reported. None is dropped, and the 2 earlier runs are reported separately, because the
  first was selected for being a violation.
- **Counted as reproduced:** Oracle VIOLATION with `duplicate_side_effect` under the same conditions.
- **Thresholds, fixed now:** 0 of 6: an isolated event. 1-2 of 6: occasional. 3 or more of 6:
  recurring. A run cut off by a token limit or provider error is listed as impaired and not counted
  either way.
- Six runs give a rough rate only. No confidence claim is made.
