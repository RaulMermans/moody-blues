# Sprint 11: Beautifully Wrong

- **Date:** 2026-11-05
- **Branch:** `sprint/11-beautifully-wrong`, from Sprint 10 HEAD `d2e4439`. Local only: not pushed, merged or deployed.
- **Outcome:** `ACCEPTED LOCALLY`, pending the owner's review of the renders.
- **Inference spend this sprint:** $0. No model was called. No backend, Oracle, CRM, fault or evidence file changed.

The Reality Comparison is rebuilt around Result, Explanation, Investigation, Raw evidence, and every product
screen takes the new theme. Direction: [direction](../design/direction.md). Screen specification:
[Reality Comparison](../design/reality-comparison.md).

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C11-A Clarity | **PASS** | Task, report, outcome and verdict are inside the first screen on all 20 runs at 390, 768 and 1440 px, tested. No user test was run |
| C11-B Refined art direction | **PASS** | Three displacements in the system, each gated on `VIOLATION`. The team's judgement from the renders; the owner has yet to review |
| C11-C Reality Comparison | **PASS** | [Violation](../design/screenshots/sprint-11/after-violation-desktop-full.png), paired rows and the `=` `≠` `?` seam |
| C11-D Evidence integrity | **PASS** | Every field on all 20 runs matches the API. 2 truth defects found and fixed. Backend and evidence unchanged |
| C11-E Progressive disclosure | **PASS** | Run kept across tabs, call to journal and back, hypothesis link, Raw evidence view, deep links, tested |
| C11-F Accessibility | **PASS, with limits** | axe 0 violations across 7 screens × 3 widths; 44px, keyboard, contrast and reduced motion tested. Screen reader and real Safari are `NOT_RUN` |
| C11-G Visual quality | **PASS** | Four rounds of screenshot review. Defects below were found by eye |
| C11-H Regression and release safety | **PASS** | `make check` passes with `frontend/e2e` unmodified; the live site's CSS hash is unchanged |

## Verification

| Check | Result |
|---|---|
| ESLint, `tsc`, Next.js production build | PASS |
| Backend, `make test` | PASS, 870 |
| Docker integration and containment, `make test-integration` | PASS, 72 |
| Product e2e, `make test-e2e` | PASS, 34, specs unmodified |
| Design, rules, axe and WebKit, `make test-design` | PASS, 71: 67 Chromium and no-browser, 4 WebKit |
| Hosted tests | NOT_RUN: nothing was deployed |
| Screen reader, real Safari, Firefox | NOT_RUN |
| User testing | NOT_RUN |
| Live site, read-only | `/` 200, `/design-lab` 404, CSS SHA-256 `f5120e40…c91`, the same as the Sprint 10 baseline |

**Cases covered, all from recorded evidence.** Verified violation (`run_cc34d7a6e314`), honest violation
(`run_e9f3ebda139d`), correct recovery and delivered fault without a violation (`inv_8058b370bc59`), negative result
(`inv_c803b47c336a`), inconclusive with a missing claim (`run_8145a6bc00d7`), inconclusive under-report
(`run_422f9afbb127`), and a PASS run inside an inconclusive case. Corrupt and missing evidence use the tampered
bundle and absent ids. States no run reaches use labeled derived fixtures in `rules.spec.ts`.

**Test changes.** `frontend/e2e` and `frontend/e2e-hosted` are unchanged. `design.spec.ts` was rewritten, because
the lab prototypes it tested are retired. Its truth and access checks moved to the product routes. Checks for
retired effects (cut plane, crack count, echoes, sliced headline, ghosted titles) are replaced by a check that no
decorative layer exists.

## Before and after

| | Before | After |
|---|---|---|
| Landing | ![](../design/screenshots/sprint-11/before/landing-desktop-fold.png) | ![](../design/screenshots/sprint-11/after-landing-desktop.png) |
| Verified violation | ![](../design/screenshots/sprint-11/before/violation-desktop-fold.png) | ![](../design/screenshots/sprint-11/after-violation-desktop.png) |
| Clean recovery | ![](../design/screenshots/sprint-11/before/recovery-desktop-fold.png) | ![](../design/screenshots/sprint-11/after-recovery-desktop.png) |
| Inconclusive | ![](../design/screenshots/sprint-11/before/inconclusive-noclaim-desktop-fold.png) | ![](../design/screenshots/sprint-11/after-inconclusive-no-claim-desktop.png) |
| Phone | ![](../design/screenshots/sprint-11/before/violation-mobile-fold.png) | ![](../design/screenshots/sprint-11/after-violation-mobile.png) |

Others: [honest violation](../design/screenshots/sprint-11/after-honest-violation-desktop.png),
[under-report](../design/screenshots/sprint-11/after-inconclusive-under-report-desktop.png),
[effects off](../design/screenshots/sprint-11/after-violation-effects-off.png),
[WebKit](../design/screenshots/sprint-11/engine-webkit-1440.png).

## Audit of the old screen

| Finding | Before | Now |
|---|---|---|
| Answer below chrome | Verdict at y≈440 on desktop; off the first screen on a phone | Headline and verdict in the first screen everywhere |
| Duplicated message | "Two records" in title, case note and strip | Once. The case note moved to About |
| False alarm | Faulted calls drawn red in runs the Oracle passed | Coral needs a `VIOLATION`, tested |
| Run lost on tab change | Tabs dropped `run` | Kept |
| Internal detail up front | Model, strategy, runtime, cost, id in the header | About and Raw evidence |

Preserved: investigation navigation, run selection, fault list, evidence ids, records table, Oracle semantics,
recorded and live labels, public and operator boundaries, and the `data-testid`s the existing suites use.

## Problems found by inspection and by tests

| Problem | Found by | Now tested |
|---|---|---|
| **KI-51: "wrong status" on an accurate `not_completed`. This is live in the deployed release** | Reading the evidence | Yes |
| **KI-52: "Calls 0, 4 and 7 committed writes": seed rows counted as the agent's** | Reading a screenshot | Yes |
| Verdict below the fold on a phone | Screenshot | Yes |
| Ledger 1,650px of stacked controls | Screenshot | No: a judgement |
| Landing headline wrapped to four lines | Screenshot | No |
| KI-53: deep links missed streamed anchors | Screenshot | Yes |
| KI-54: a heading hung the loading check | Timeout | Avoided |
| Landing lost the product's name and description | `status.spec.ts` | Yes |
| Landing CLS 0.182 | Test | Yes |
| Status panel contrast, `dl` markup, keyboard access to tables, 22px copy button | axe, 44px check | Yes |

## Performance

| | Before | After |
|---|---|---|
| Product CSS | 19,999 B | 37,376 B, 8,023 B gzipped |
| Client JavaScript | 609,103 B | 609,160 B: `HashFocus` only |
| Font on every page | None | Archivo, 90,104 B, one self-hosted file |
| Landing, local | Not measured | CLS 0, LCP 28 ms, 256 elements |
| Comparison, local | Not measured | CLS 0, LCP 368 ms, 863 elements |
| Animations running at rest | 0 | 0 |
| New runtime dependencies | | None. `@axe-core/playwright` is development only |

The font is the real cost. Timings are one local Chromium run on loopback and do not predict hosted performance.

## Critique

The first screen is the best thing MOODY BLUES has shipped. The two-line contradiction lands before anything else,
and the recovery page reads as calm without a special case. The honest-failure page proves the system encodes
evidence rather than mood.

What is still not good enough:

- **Below the ledger the page loses its voice.** About and Evidence and limits are competent lists, and the page
  is long. They are the old content in new type.
- **Timeline and Investigator were themed, not designed.** Next to the comparison they look like an earlier product.
- **The Outcome row is lopsided on a duplicate.** One slip faces two slabs, which is true to the data, and it
  leaves empty space on the left.
- **The headline is heavy for a long sentence.** "The agent reported the task not completed." fills the column.
- **The seam is quiet at the top of a tall row.** Its `≠` is what reads; the step itself is subtle, perhaps too subtle.
- **Tabs clip at 390 px,** with "Raw evidence" scrolled off and only the cut text as a hint.

## Limitations

- Causal evidence reads "None in this record", though the Sprint 6 study holds a clean contrast. Showing it needs
  the export to carry it: [details](../design/reality-comparison.md#causality).
- `stateLine`'s "1 required" assumes this mission family, as the deployed copy did. Its rules cover only the CRM task.
- Rules were exercised on 20 runs. A run with many records has not been seen.
- Archivo is a Latin subset, so other scripts fall back to system fonts in reading text too, now that it is the body face.
- The `hero-cta` falls back to the list when no verified violation is on record. That path was not rendered.

## Release

Nothing is deployed, and production runs the `main` release. **Do not deploy before the hackathon deadline without
weighing KI-51:** the branch fixes that wording, and carries a whole-product restyle with it. If only the fix is
wanted, it is a small change to `disclosureLine` on `main`.

To deploy later, with the owner's approval: review this record, run `frontend/e2e-hosted` after deploying, and roll
back with `infra/vultr`. See `docs/deployment/vultr-deployment.md`. The change is frontend only, so rollback touches
no evidence, ledger or backend state.

## Recommended for Sprint 12

- Design the landing narrative, and the page below the ledger.
- Give Timeline and Investigator the comparison's language: `≠` marks on the timeline by `call_seq`.
- Export the registered causal contrast into the case bundle, so the page can state it.
- Run VoiceOver, real Safari and a first-time-reader test, to replace the design targets with results.
- Decide whether the `main` wording fix for KI-51 ships separately.
