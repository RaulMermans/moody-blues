# Sprint 6 plan addendum: reproducing `exp_719f74f5b150` (registered before these runs)

_Committed before any run below. Added after the strategy suite, so this is a follow-up to a seen
result, not part of the frozen manifest. It has no effect on the registered conclusion rule._

## Why

Adaptive investigation `inv_d0bc87de6010` produced an eligible Oracle violation in
`exp_719f74f5b150`: `w-e1`, baseline, `phantom_success` occurrence 1 with `stale_read` occurrence 2,
span 6. Read by hand, it differs from the known failure: no idempotent replay was involved, the agent
dropped its key on a later create, and it claimed `completed`. The benchmark disabled automatic reruns
for fairness, so this finding has one run and no reproduction status.

## Test

- Rerun the original generated program unchanged, exactly **5 times**, each in a fresh world, with
  the manifest's target limits: `make eval-repro EXPERIMENT=exp_719f74f5b150 RUNS=5 CONFIRM=1`.
- All 5 are reported, with no replacement. The original is reported separately, because it was
  selected for being a violation.
- **Reproduced:** an Oracle violation sharing a code with the original under the same conditions.
- **Bands, by eligible runs:** none: not reproduced here; up to one third: occasional; above one third:
  recurring. Impaired runs are listed and not counted either way.
- This is a rate check only. It has no clean-control arm, so it supports no causal claim.
- **Budget:** inside the $5 sprint limit, on the same ledger. Expected under $0.25.
