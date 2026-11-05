# Components

All live in [`frontend/src/design/components/`](../../frontend/src/design/components/). All are server
components, so they add no client JavaScript. Their contract is
[`frontend/src/design/model.ts`](../../frontend/src/design/model.ts).

## The rule that governs them

A component is told what to draw. `model.ts` copies named evidence fields into typed states. It reads no
free text for meaning and detects nothing, so a fracture cannot appear without a recorded reason.

| Component | Input | Purpose | Never |
|---|---|---|---|
| `RealityFrame` | `reality: "agent" \| "actual"` | One side of a comparison, with the side's shape and label | Hold business logic |
| `DivergenceField` | `state: DivergenceState` | The two planes. Only `violation` cuts them | Cut a plane without a violation |
| `DivergenceDivider` | `state`, optional `detail` | The boundary and its label | Depend on animation to be understood |
| `Crack` | `state`, `orientation` | The drawn line alone, for custom layouts | Carry text |
| `RealityEcho` | `children` | Empty displaced outlines | Hold text or data, or sit near a record |
| `OracleSeal` | `state: SealState` | The verdict | Rotate, offset, echo or wrap inside a word |
| `FractureMarker` | `discrepancy: Discrepancy`, `tone` | One recorded discrepancy | Appear without a record |
| `DisplayType` | `text: string`, `effect` | Editorial type | Take a recorded value |
| `RecordSlab` | `record: RecordView` | One committed row | Be drawn for anything but a real row |

## `DivergenceState`

From `divergenceFrom(run)`:

| State | Comes from | Draws |
|---|---|---|
| `violation` | Oracle `VIOLATION` | Jagged crack, cut planes, moiré, echoes, ghosted titles |
| `delivery` | Oracle `PASS` with recorded discrepancies | Straight dash-dot line, neutral markers, "Distorted, state held" |
| `unresolved` | Oracle `INCONCLUSIVE` | Straight dotted line, "Unresolved" |
| `none` | Oracle `PASS`, no discrepancies | One plain hairline |

`delivery` exists because every recorded PASS run has at least one discrepancy. "Has a discrepancy" must not
mean "broke": a fault the agent recovered from is real and is not a failure.

## `SealState`

The contract has three Oracle verdicts. The brief's `FAILED` and `UNVERIFIED` are not verdicts, so the type
keeps them apart:

| Kind | Values | Meaning | Form |
|---|---|---|---|
| `verdict` | `PASS`, `VIOLATION`, `INCONCLUSIVE` | The Oracle spoke | Solid, with ✓ ✕ ? |
| `incomplete` | `failed`, `cancelled`, `budget_exhausted` | The run did not finish, so no verdict exists | Hollow double rule, — |
| `unverified` | `no_target_run`, `outcome_uncertain`, `integrity_failed` | Nothing can be said | Hollow dashed rule, ∅ |

A `verdict` carries an optional `qualifier`. `state_correct_claim_missing` is an Oracle PASS, so it renders
PASS with "State correct, but no valid claim. Not a success." beneath it. An impaired run says so the same way.

## Using them

```tsx
const model = comparisonFrom(detail, runs, run);

<DivergenceField state={model.divergence}>
  <RealityFrame reality="agent">…</RealityFrame>
  <DivergenceDivider state={model.divergence} />
  <RealityFrame reality="actual">
    {model.newRecords.map((r) => <RecordSlab key={r.customer.customer_id} record={r} />)}
  </RealityFrame>
</DivergenceField>
<OracleSeal state={model.seal} />
```

`DivergenceField` needs a grid from its caller. See `.rf-comparison-field` in `prototypes.css`.

## Editorial type

`DisplayType` has three effects: `plain`, `slice` and `misregister`. The text is read once by assistive
technology; the layers are `aria-hidden`. Inside a field without a violation the layers switch off.

Large evidence words use `.rf-evidence-word` or `.rf-count-number`: big, single-layer, and in the recorded
spelling. `completed` stays lowercase because that is what the agent filed.

## What the browser tests enforce

`frontend/e2e-design/design.spec.ts`, against all five recorded cases:

- Seal, claim, count, discrepancy count, findings and disclosure match the API.
- `RecordSlab` ids equal the run's new records exactly.
- The planes are cut only for `VIOLATION`, and a PASS run shows no fracture tone, ghost or echo.
- Every decorative layer is `aria-hidden` and holds no id or number. No echo touches a record.
- No verdict wraps, and nothing covers a recorded value.
