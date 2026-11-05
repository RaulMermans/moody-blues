# ADR 0006: Registered evaluation with eligibility and controlled attribution

- **Status:** accepted (Sprint 6, 2026-11-04)
- **Context:** Sprint 5 could not say whether adaptation helped, because strategies never tested the
  same condition. It also could not say how often the failure occurred, because impaired runs sat
  among clean ones, or whether the fault caused it, because `fault_attributable` only records
  delivery.

## Decisions

1. **Eligibility is a flag beside the Oracle's verdict, not a change to it.** A truncated duplicate is
   still a duplicate. It leaves the rate, not the record. *Rejected:* reclassifying impaired violations,
   which edits truth to tidy a statistic, and which an existing test rightly forbids.
2. **Eligibility is read without the outcome.** A truncated run that succeeded is as ineligible as one
   that failed. Otherwise excluding runs could shape the result.
3. **A registration is data, and it is checked.** A manifest fixes conditions, counts, stopping rules
   and budgets; a plan is derived from it by a fixed seed. Fingerprints of prompts, policies, worlds and
   models make `eval-run` refuse if code drifted, and it refuses uncommitted registrations. *Rejected:*
   a prose plan alone, which nothing enforces.
4. **One 3x2 design answers causation, reproduction and hardening.** Clean, short and long stale reads
   against baseline and hardened. Separate studies would cost more and compare less.
5. **The highest attribution level needs a contrast.** One run can show `fault_delivered` and
   `violation_observed`, never `causal_evidence_supports_fault`. *Rejected:* temporal order as evidence
   of cause, and significance tests on samples this small.
6. **Sequential extension is all-or-nothing and pre-registered.** Extending only interesting cells would
   choose a denominator.
7. **Adaptation is scored on what ran, against a blind control.** Citing an observation earns nothing.
   An answer is credited only beyond what the same rubric gives answers written with no observation.
   *Rejected:* an LLM judge, which adds a second unmeasured model to the measurement.
8. **Journals are append-only and hash-chained.** A broken chain stops a suite and its report. A trial
   that started and never finished stays attempted and is not retried under its id.
9. **The sprint budget sits on the same ledger.** Its limit is settled spend at freeze plus the sprint
   budget, so nothing is reset. Suite caps use the existing scope.
10. **Non-adaptive programs may be replaced in the matched comparison only.** Adaptive runs always had
    this repair. It is opt-in, so Sprint 5 behavior stays as tested, and planning still sees no
    observation, by construction.

## Consequences

- A prompt change after registration needs a new manifest id, which is the point.
- Results are recomputed from journals by `eval-report`, so they can be regenerated but not edited.
- Evidence stays in `.artifacts/` (not committed). Committed results link to it by id and hash, so a
  reader without the local artifacts can inspect records but not re-verify raw evidence.
