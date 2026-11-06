# Components

All live in [`frontend/src/design/components/`](../../frontend/src/design/components/). All are server
components, so they add no client JavaScript. Their contract is
[`model.ts`](../../frontend/src/design/model.ts), and their words come from
[`story.ts`](../../frontend/src/design/story.ts).

## The rule that governs them

A component is told what to draw. `model.ts` copies named evidence fields into typed states. It reads no free
text for meaning and detects nothing, so a distortion cannot appear without a recorded reason.

| Component | Input | Purpose | Never |
|---|---|---|---|
| `Headline` | `first`, `second`, `outOfRegister`, `size` | The two-sentence statement | Take a recorded value, or layer text |
| `ComparisonRow` | Two labeled sides, `relation`, `tone` | One event seen from both sides | Hold business logic |
| `DivergenceDivider` | `relation`, `tone`, `glyph` | The seam and its `=` `≠` `?` | Depend on colour or motion to be understood |
| `OracleSeal` | `state: SealState` | The verdict, the one light object | Rotate, offset or wrap inside a word |
| `RecordSlab` | `record: RecordView`, `callHref` | One committed row | Be drawn for anything but a real row, or have anything drawn around it |

`VerdictStrip` (`components/verdict-strip.tsx`) composes the four summary fields and is shared by the
investigation page and the landing page.

## What happened to Sprint 10's nine

Each was judged on five questions: does it improve understanding, communicate a real state, help identity
without hurting reading, get reused, and work without motion?

| Sprint 10 | Decision | Why |
|---|---|---|
| `OracleSeal` | Kept, smaller | Passes all five. Dropped the repeated "Truth Oracle verdict" note |
| `RecordSlab` | Kept | Passes all five. Gained the slip and a link to its call |
| `DivergenceDivider` | Rewritten | The idea survives as the seam, at row level |
| `DisplayType` | Replaced by `Headline` | Its slice and misregister layers were the theatrical part |
| `RealityFrame` | Replaced by `ComparisonRow` | Two frames read one whole side at a time. A row keeps an event together, on a phone and in a screen reader |
| `DivergenceField` | Removed | Cut planes carried no information |
| `Crack` | Removed | A drawn shape standing for a fact the seam states directly |
| `RealityEcho` | Removed | Empty outlines beside evidence, close to reading as extra records |
| `FractureMarker` | Removed | Repeated the ledger. Discrepancies are a table now, and marks sit on the calls |

## `Relation` and `SeamTone`

| Relation | Glyph | Comes from |
|---|---|---|
| `equal` | `=` | A claim exists, and there is no `claim_versus_state` discrepancy |
| `differs` | `≠` | `claim_versus_state`, a located discrepancy, or a delivered fault on a call |
| `unknown` | `?` | There is no claim to compare |

| Tone | Draws | Comes from |
|---|---|---|
| `steady` | One hairline | No recorded difference |
| `distortion` | A dashed line, neutral colour | A recorded difference, verdict not `VIOLATION` |
| `break` | A coral line stepped sideways with gaps | A recorded difference, verdict `VIOLATION` |

## `DivergenceState`

From `divergenceFrom(run)`, on the comparison as `data-divergence`: `violation`, `delivery` (PASS with
discrepancies), `unresolved` (INCONCLUSIVE), `none`.

## `SealState`

The contract has three Oracle verdicts. `FAILED` and `UNVERIFIED` are not verdicts, so the type keeps them apart:

| Kind | Values | Meaning | Form |
|---|---|---|---|
| `verdict` | `PASS`, `VIOLATION`, `INCONCLUSIVE` | The Oracle spoke | Paper, with ✓ ✕ ? on a status tile |
| `incomplete` | `failed`, `cancelled`, `budget_exhausted` | The run did not finish, so no verdict exists | Hollow dashed outline, — |
| `unverified` | `no_target_run`, `outcome_uncertain`, `integrity_failed` | Nothing can be said | Hollow dashed outline, ∅ |

A `verdict` carries an optional `qualifier`: `state_correct_claim_missing` is an Oracle PASS, so it renders PASS
with "State correct, but no valid claim. Not a success." beneath it. An impaired run says so the same way.

## Styles

`styles/tokens.css` and `styles/primitives.css` are imported by `app/globals.css`, so every screen shares them.
There is one theme. Other product screens use Tailwind utilities pointed at the same tokens.

## What the tests enforce

- `frontend/e2e-design/rules.spec.ts`: every copy and state rule, on all 20 recorded runs, plus labeled derived
  fixtures for states no run reaches.
- `frontend/e2e-design/design.spec.ts`: every recorded run renders what its evidence holds, in a real browser,
  along with navigation, access, axe and contrast.
- `frontend/e2e-design/cross-browser.spec.ts`: layout in Chromium and WebKit.
