# Sprint 5: Autonomous Investigator and adaptive experimentation

- **Date:** 2026-11-04
- **Branch:** `sprint/05-autonomous-investigator`, from Sprint 4 HEAD `56f956e`. Not pushed.
- **Outcome:** `ACCEPTED` locally. All ten checkpoints pass, some with stated limits. GitHub Actions
  has not run.

## Goal

Answer: can MOODY BLUES independently choose, execute and refine adversarial experiments based on
evidence, and distinguish verified failures from correct recovery? Design:
[investigator.md](../architecture/investigator.md), [ADR 0005](../adr/0005-autonomous-investigator.md).
Results: [sprint-05-investigator.md](../evaluations/sprint-05-investigator.md).

**Answer:** yes for choosing, executing, refining and distinguishing, within tested limits. Whether
feedback improves discovery is not yet established.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C5-A Generated-code safety | **PASS** (real Docker) | Digest-pinned image; 19-check preflight observed from inside; 15 hostile-program tests. gVisor unavailable, so the shared-kernel risk stands |
| C5-B Typed state and linkage | **PASS** | State machine; `verify_investigation` links proposal, source, evidence and report; tampering detected |
| C5-C Real generated experiment | **PASS** (live) | 36 proposals by `glm-5.3`, 25 executed through the coordinator |
| C5-D Feedback-driven adaptation | **PASS, narrowly** (live) | Registered confirmation: `hardened` 0/12 after PASS, 11/12 after VIOLATION. The registered per-case test **failed** on held-out worlds (0/3) |
| C5-E Bounded recovery | **PASS** (live) | Refinement after invalid output worked live; limit enforced; originals preserved |
| C5-F No leaked outcomes | **PASS** | Neutral ids and titles, no descriptions; prompts tested for seeds, faults and protected material |
| C5-G Baselines and adaptation evidence | **PASS** as an initial comparison | 3 strategies, 2 trials, registered first. Superiority **not** shown |
| C5-H Finding verification | **PASS** (live) | Every violation trace read by hand; one false alarm caught; reproduction recorded |
| C5-I Shared budget | **PASS** | One ledger, per-investigation scope, failed calls kept, corrupt ledger refuses; 40 model calls and 40 target runs governed live |
| C5-J Authority boundaries | **PASS** (offline and Docker) | Injection via claim text, claimed id, summaries, stderr and diagnostics absent from prompts by type. An adversarial live target was not tried |

## Problems found and fixed

1. **Hidden reasoning consumed all output** (KI-27). Fixed with `reasoning_effort: low`, which cut
   inference from 159 s to 11 s per investigation in one comparison of live runs.
2. **Nested tool arguments arrived as strings** (KI-28). Flat schema; output is never decoded.
3. **A provider failure was filed as an agent shortfall.** New `impaired_run` class.
4. **The target was cut off at 1,024 tokens** exactly when a hard world made it think (KI-29).
5. **A false violation** (KI-30): the agent declined to duplicate an identical record and said so,
   no fault fired, and the Investigator credited the faults. Worlds clarified; `fault_attributable`
   added. This was caught only by reading the trace.
6. **A corrupt ledger crashed the report** of the refusal it caused.
7. **A correct refinement was refused** for reusing its hypothesis id.
8. **The one-shot baseline lost two of three proposals** by reusing `h1`, which was unfair to it.
9. **A transient HTTP 502** ended an investigation with retries at 0. Retries are now 1.
10. **CI would have skipped `tests/investigator`** and lacked the pinned image.
11. **Host sleep stalled and dropped live calls** (KI-26).

A property test sampled every `FaultKind` against a model covering only write faults. It was
narrowed to those kinds, and `stale_read` got its own properties, so no coverage was lost. One test
and one probe of mine were wrong and were corrected; the probe's apparent secret leak was verified
as self-reference before it was dismissed.

## Budget

Sprint 5 used 1,043,673 tokens: **about $2.33 of the $5 limit**, at assumed ceiling prices. That
includes full reservations kept for failed calls. Project total about $2.94 of the $200 credit.
**Confirm actual billing in the Vultr console.** The estimate is not a provider figure.

## Remaining risks

- Shared kernel; no gVisor. Image digest pinned but no signature verified.
- Same model as Investigator and target, one author for worlds and Investigator, small samples.
- Causal claims are only partly checked: a persuasive wrong story can still pass the code checks.
- `fault_attributable` shows a fault fired, not that it caused the violation.
- The Target Agent still runs in the trusted process.

## Readiness for Sprint 6

Ready to build on. Suggested first steps: a same-condition comparison, giving all strategies six
stale reads in `w-e3`, to separate feedback from harshness; more repetitions; a different target
model; and testing whether the hardened policy prevents the duplicate.
