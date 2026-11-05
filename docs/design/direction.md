# Design direction

## Concept: Beautifully Wrong

The product shows the gap between what an agent reported and what happened. It looks like a premium
scientific instrument with an editorial voice, and it is slightly wrong in exactly the places the evidence
is wrong.

The working balance is 80% clear product design, 15% expressive type and composition, and 5% distortion.
It is a way of judging a screen, not a measurement.

**Forensic Brutalism is the foundation. Reality Fracture is the exception.**

## What changed from Sprint 10, and why

Sprint 10 picked Reality Fracture as the dominant aesthetic. Reviewing the renders, the owner reversed that
hierarchy: [the Sprint 10 fold](screenshots/05-comparison-fold.png) was memorable, but the effects competed
with the evidence.

| Sprint 10 | Sprint 11 | Why |
|---|---|---|
| Violet and amber territories | Graphite ground; lavender and sand appear only as a label and a rule | Colour is an accent, not a surface |
| A jagged crack through cut planes | A thin seam, which breaks only at rows with a recorded difference | The seam carries data. The crack carried mood |
| Moiré, echoes, sliced and misregistered type | Removed | They said nothing the seam does not |
| Oracle as a full-width paper slab | Oracle as one small paper seal per screen | Light keeps its emphasis when it is rare |
| Compressed black display type | Archivo at 82% width, semibold | It stays expressive and stops shouting |
| Fixed study of one signature case | Every state designed from the evidence | A calm case now looks calm by construction |

Sprint 10's owner decision is settled: the headline says **reported**, not believed. In the signature run the
agent's message names both records, so "believed" was never accurate.

## The idea in one glyph

Each row of a comparison ends in a plain symbol: `=` the two sides agree, `≠` they differ, `?` one side holds
nothing to compare. A reader needs no knowledge of the design to read it, and a screen reader hears it as a
sentence. Down a ledger of tool calls, the glyphs make the shape of a run visible at a glance.

## The distortion budget

There are three displacements in the whole system. Each is a small fixed offset, and each needs an Oracle
`VIOLATION`:

| Offset | Where | Exact condition |
|---|---|---|
| The seam steps sideways and leaves a gap | A comparison or ledger row | The row holds a recorded difference and the verdict is `VIOLATION` |
| The second headline line sits out of register | The headline | `false_completion_claim`: report and reality disagree |
| The extra record slips out of line | A record slab | Flagged duplicate, left out of the structured claim, in a claim that named another flagged record |

An honest report of a real duplicate is the test of this design. The record still slips, because the
duplicate is real. The headline stays flush and the outcome row reads `=`, because report and reality agree.

## Visual principles

1. **The information is the art.** If an effect does not carry a recorded fact, it goes.
2. **Distortion is earned.** Only an Oracle `VIOLATION` displaces anything. A calm case is calm by rule.
3. **Evidence is never treated.** Ids, numbers, verdicts and controls are never layered, skewed or sliced. A
   record may move only as a whole, and nothing is drawn around it.
4. **The Oracle does not move,** and it is the only light object on a screen.
5. **Shape before colour.** The agent's side has a broken rule, the authoritative side a solid one. Each status
   has its own glyph and word.
6. **Absence looks like absence.** A missing verdict is hollow. It never resembles a result.
7. **Result, explanation, investigation, raw evidence.** Each step is one move from the last.
8. **It must survive removal.** With every offset off, the page must read the same:
   [proof](screenshots/sprint-11/after-violation-effects-off.png), and a test asserts the text is unchanged.

## Evidence findings that shaped the design

- **A status can be accurate alongside a violation.** `run_e9f3ebda139d` holds a real duplicate and a true
  `not_completed`. Sprint 10's disclosure line called that a "wrong status": a defect, now fixed.
- **A run is not its investigation.** `inv_5c9f95de6c09` is Inconclusive and its primary run is a PASS. A scope
  note says so instead of letting the two disagree silently.
- **Under-reporting exists.** `run_422f9afbb127` said `not_completed` while the objective was met. It differs
  from the state, it is `INCONCLUSIVE`, and it must look neither like a failure nor like a success.
- **Selected is not delivered.** Some faults have the effect `not_applied_nothing_to_hide`. Counts come from
  delivery records.
- **Causal evidence exists, and is not in the bundle.** See
  [Reality Comparison](reality-comparison.md#causality).
