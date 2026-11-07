# Sprint 10: Reality Fracture design foundation

- **Date:** 2026-11-05
- **Branch:** `sprint/10-reality-fracture-design-system`, from `main` `967dc88`. Local only: not pushed, merged or deployed.
- **Outcome:** `ACCEPTED LOCALLY`, pending the owner's review of the visual direction.
- **Inference spend this sprint:** $0. No model was called.

Everything in this sprint is a local prototype. The product and the live site are unchanged.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C10-A Creative direction | **PASS** | Three studies rendered from one recorded run, and inspected: [A](../design/screenshots/01-direction-a-reality-fracture.png), [B](../design/screenshots/02-direction-b-mirror-corruption.png), [C](../design/screenshots/03-direction-c-forensic-brutalism.png) |
| C10-B Selected identity | **PASS** | A, with C's Oracle treatment: [direction](../design/direction.md) |
| C10-C Design tokens | **PASS** | [`tokens.css`](../../frontend/src/design/styles/tokens.css), [reference](../design/tokens.md) |
| C10-D Visual components | **PASS** | 9 primitives on a typed contract: [components](../design/components.md) |
| C10-E Landing prototype | **PASS** | [Screenshot](../design/screenshots/04-landing.png), reads the real run |
| C10-F Reality Comparison prototype | **PASS** | All 5 recorded cases match the API in `make test-design`. [Screenshot](../design/screenshots/05-comparison-fold.png) |
| C10-G Accessibility and performance | **PASS** | [Results](../design/accessibility-and-motion.md). No screen reader or axe audit was run |
| C10-H Regression and release safety | **PASS** | Production assets byte-identical to a clean `main` build; `/design-lab` is 404 live |

## Verification

| Check | Result |
|---|---|
| ESLint, `tsc` | PASS |
| Backend, `make test` | PASS, 870 |
| Docker integration and containment, `make test-integration` | PASS, 72 |
| Product e2e, `make test-e2e` | PASS, 34: the existing 33 plus one |
| Design lab browser tests, `make test-design` | PASS, 22 |
| Frontend unit tests | NOT_RUN: the project has no frontend unit runner, and adding one was out of scope |
| Hosted tests | NOT_RUN: nothing was deployed |
| Live site, read-only | `/` 200, `/design-lab` 404 |

**Release proof.** A clean `main` was built in a temporary worktree. All 13 static assets from this branch match
it byte for byte, leaving out the three manifests that carry the build id. The product CSS is 19,999 bytes,
SHA-256 `f5120e40…c91`, on both. `design-lab` strings and the font are absent from `.next`.

## Performance

| | Result |
|---|---|
| Product bundle | No change |
| Client JavaScript added by the lab | None: every design component is a server component |
| Lab-only CSS | 29,943 bytes uncompressed |
| Lab-only font | 90,104 bytes, one file, self-hosted |
| New dependencies | None |
| Landing, local | CLS 0.019, LCP 348 ms, 109 elements |
| Comparison, local | CLS 0, LCP 380 ms, 283 elements |
| Running animations at rest | 0 |

The timings come from one local Chromium run against a loopback backend. They show no regression in kind and
do not predict hosted performance.

## What the brief had out of date

- **The agent did not believe there was one record.** Its message names both. The left side shows what it
  filed, and the disclosure stays visible: [details](../design/direction.md#evidence-findings-that-shaped-the-design).
- **`FAILED` and `UNVERIFIED` are not Oracle verdicts.** The contract has three. They render hollow, as
  absence of a verdict. `cancelled` and `budget_exhausted` keep their own labels.
- **Every recorded PASS run has a discrepancy.** So "has a discrepancy" could not drive the fracture. A
  `delivery` state exists for faults the agent recovered from.
- **`FractureMarker` needs no detection work:** `Discrepancy` is already a typed record.

## Problems found by inspection

Tests passed through several of these. Each now has a test where one can catch it.

| Problem | Found by | Now tested |
|---|---|---|
| `VIOLATION` broke mid-word in the seal | Screenshot | Yes |
| Study B's seal covered a record id | Screenshot | Yes |
| Coral markers and ghosted titles on a PASS run implied a failure | Screenshot | Yes |
| The sliced headline was hidden from screen readers | Test | Yes |
| Mobile headline lost its gutter | Screenshot | Yes |
| Production build failed, and product CSS grew (KI-50) | Baseline comparison | `product.spec.ts` covers the routes; the hash check is manual |
| The plane's entry shift uncovered the plane beneath it for 320 ms | Screenshot | No |

## Limitations

- Prototypes only. The product's screens are unchanged.
- The hero is built for a violation. It has not been designed for another case.
- `tone` on `FractureMarker` and the comparison layout were exercised on 5 cases. A run with many records has not been seen.
- Archivo is a Latin subset. Evidence is safe, because it uses system fonts, but display type would fall back for other scripts.
- The moiré is decorative, and contrast was not computed for text near it.
- Chromium only. Safari has different `clip-path`, `font-stretch` and `mask` behavior and needs checking.
- Keeping the production CSS identical is a manual check, not a gate.

## Deferred to Sprint 11

- Replace `RealityView` with the new composition, and keep all of its `data-testid`s.
- Promote the tokens and retire the product's cyan for Actual Reality.
- Keep `RunPicker`, the mission text, the fault list and the full records table in the new layout.
- Decide the headline: "believed" or "reported".
- Apply the theme to the Investigation header, tabs, Timeline and Investigator views.

## Recommended for Sprints 12 and 13

- **12:** Investigator logic for non-engineers, using `FractureMarker` on the timeline by `call_seq`. A designed
  hero for clean cases. Add axe, and a Safari run.
- **13:** The crack drawing in, the perceived-to-actual transition, and interrupted borders, within
  [the motion rules](../design/accessibility-and-motion.md#motion). Automate the production CSS check.
