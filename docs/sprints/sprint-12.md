# Sprint 12: Investigation Experience

- **Date:** 2026-11-06
- **Branch:** `sprint/12-investigation-experience`, from `origin/main` `e2c9a41`. Its tree equals Sprint 11's tip `9b34e4e`. Pushed to `origin` on the owner's instruction. Not merged or deployed.
- **Outcome:** `ACCEPTED LOCALLY`, pending the owner's review of the renders. No person has used it yet.
- **Inference spend this sprint:** $0. No model was called. No backend, Oracle, CRM, fault, contract, evidence or infrastructure file changed.

The Investigator and Timeline are redesigned around the recorded evidence flow, an Overview joins the views, and the
phone tabs no longer clip. Specification: [investigation-experience.md](../design/investigation-experience.md).

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C12-0 Production correctness | **PASS** | KI-51 is fixed on `main` and still live. Isolated hotfix prepared, unpushed. See below |
| C12-A Investigator clarity | **PASS** | Four stages per hypothesis. Every run's claim, verdict, faults and discrepancies match the API on all 5 cases, tested. All generated decisions read against the record |
| C12-B Timeline clarity | **PASS** | 23 milestones of 127 records. Order and completeness tested on every bundle. Each event gives its explanation, record and links |
| C12-C Navigation | **PASS** | Five views. Run kept and named across views, back button, deep links, tabs on screen at 320 and 390 px, tested |
| C12-D Landing | **PASS** | Proposition, CTA and a real case in the first desktop screen. Four stages. Whether a stranger understands it is untested |
| C12-E Evidence fidelity | **PASS** | No new LLM call. Reasons are verbatim and labeled. Motive-word rule over all generated text. 2 truth defects found and fixed |
| C12-F Visual coherence | **PASS, with limits** | The team's judgement from the renders; the owner has yet to review. The investigation list and system status are unchanged and read older |
| C12-G Accessibility and usability | **Automated PASS. Human NOT_RUN** | axe 0 across 12 screens × 3 widths with disclosures open. VoiceOver, real Safari and a user test were not performed |
| C12-H Regression safety | **PASS** | `make check` exit 0. `frontend/e2e` unmodified. Live CSS hash unchanged |

## KI-51 and the release

The brief assumed `main` might still hold the defect. It does not: **PR #15 merged Sprint 11 this morning**, with the
fix. So `main` and production have parted.

| | State |
|---|---|
| `main` `e2c9a41` | Fixed. `disclosureLine` needs the Oracle's `false_completion_claim` |
| Production | **Still wrong.** The public page for `run_e9f3ebda139d` read "That makes this a wrong status" on 2026-11-06 |
| Live CSS | SHA-256 `f5120e40…c91`, the pre-Sprint 11 release |
| Deployed code | `d592879` by the Sprint 9 record. `967dc88` has identical `frontend`, `backend` and `infra`. The live landing copy rules out the older `cb28311`. Not read from the host: an SSH check was refused by the permission layer |

A hotfix from `main` would be empty, and deploying `main` ships the restyle. So the hotfix is cut from the deployed line.

**`hotfix/ki-51-disclosure-wording`, commit `6dafdda`, from `967dc88`.** Two files, 15 lines: the wording rule and its
regression test. The new assertion failed before the fix. All 33 product e2e tests pass with it. Lint, types and build
pass. It never needs merging: `main` already has the fix. Pushed to `origin`, not deployed.

## Verification

| Check | Result |
|---|---|
| ESLint, `tsc`, Next.js production build | PASS |
| Backend, `make test` | PASS, 870 |
| Docker integration and containment, `make test-integration` | PASS, 72 |
| Product e2e, `make test-e2e` | PASS, 34, specs unmodified |
| Design, rules, axe and WebKit, `make test-design` | PASS, 118: 110 Chromium and no-browser, 8 WebKit |
| Live site, read-only | `/` 200, CSS hash unchanged from Sprint 10 |
| Hosted tests | NOT_RUN: nothing was deployed |
| VoiceOver, NVDA, real Safari, Firefox | NOT_RUN |
| User testing | NOT_RUN. No tester was available, and no simulated reader stands in for one |

`make check` ran on `d9c5109`. One reduced-motion CSS rule followed it, and design and product e2e were rerun after that.

**Test changes.** `frontend/e2e` and `frontend/e2e-hosted` are unchanged. The design suite grew from 71 to 118. Two checks
got stricter: axe and overflow now open every disclosure first. Screenshots now go to `sprint-12/`.

**Cases covered, from recorded evidence.** Verified violation, honest violation with an inconclusive rerun, one-shot
recovery, adaptive negative result, and inconclusive with refused programs. A nonexistent run, a tampered bundle, and
stopping for budget or failure are also tested. The empty investigation exists in no bundle, so it was rendered from a
labeled scratch fixture, not committed: [images](../design/screenshots/sprint-12/fixture-empty-investigator-desktop.png).

## Audit of the Sprint 11 journey

| Finding | Kind | Now |
|---|---|---|
| Investigator 11,664 px on a phone: every field of every hypothesis at one weight | Hierarchy | 3,826 px. One open cycle, the rest a ladder |
| The process was absent: no view said what followed what, or why | Hidden | Decision stage. `revises`, `motivated_by` and `motivation` were recorded and unused |
| `motivation` and `rationale` shown twice per hypothesis, the second labeled "Experiment objective", which it is not | Redundant, wrong | Once, as the stated reason |
| "Refuted" in green and "Supported" in red read as verdicts | Misleading | Plain words, labeled the model's, beside the Oracle's tag |
| One-shot experiments looked adaptive: nothing said they were written first | Misleading | "This result did not choose it" |
| Timeline showed 52 "key" steps, each fault a row of equal weight | Density | 23 milestones, a run is one row |
| Enum text on screen: `final_claim`, `no_violation_found` | Terminology | Plain text. Tool and fault names stay exact |
| Raw JSON as the only event detail | Hidden | A sentence and labeled values |
| About and Evidence and limits repeated under every view | Redundant | One row on three views |
| "Raw e" clipped at 390 px | Navigation | All five visible |
| Timeline and Investigator did not show which run was followed | Orientation | A line names it, with a way out |
| Experiment's fault configuration only in Raw evidence | Hidden | Experiment stage |
| Five How it works stages that matched no screen | Inconsistent | Four, in Investigator order |

Preserved: the Comparison's layout, default view, run selection, call-to-journal links, Oracle semantics, recorded and
live labels, public and operator boundaries, and the `data-testid`s the suites use.

An early capture showed "Evidence service unreachable" on the phone landing. That was this audit's server starting, not
a finding. It was retaken.

## Before and after

| | Before | After |
|---|---|---|
| Investigator | ![](../design/screenshots/sprint-12/before/investigator-desktop-full.png) | ![](../design/screenshots/sprint-12/after-investigator-desktop-full.png) |
| Timeline | ![](../design/screenshots/sprint-12/before/timeline-desktop.png) | ![](../design/screenshots/sprint-12/after-timeline-desktop.png) |
| Landing | ![](../design/screenshots/sprint-12/before/landing-desktop-full.png) | ![](../design/screenshots/sprint-12/after-landing-desktop-full.png) |
| Investigator, phone | ![](../design/screenshots/sprint-12/before/investigator-mobile.png) | ![](../design/screenshots/sprint-12/after-investigator-mobile.png) |
| Timeline, phone | ![](../design/screenshots/sprint-12/before/timeline-mobile.png) | ![](../design/screenshots/sprint-12/after-timeline-mobile.png) |
| Landing, phone | ![](../design/screenshots/sprint-12/before/landing-mobile.png) | ![](../design/screenshots/sprint-12/after-landing-mobile.png) |

Others: [overview](../design/screenshots/sprint-12/after-overview-desktop-full.png),
[verified violation](../design/screenshots/sprint-12/after-violation-desktop.png),
[clean recovery](../design/screenshots/sprint-12/after-timeline-recovery-desktop.png),
[inconclusive](../design/screenshots/sprint-12/after-investigator-inconclusive-desktop.png),
[WebKit](../design/screenshots/sprint-12/engine-webkit-390.png).

## Problems found by inspection and by tests

| Problem | Found by | Now tested |
|---|---|---|
| KI-55: opening a tool call widened a phone page 4,449 px. Predates this sprint and is on `main` | Stricter overflow check | Yes |
| KI-56: refused programs read "First experiment" | Screenshot | Yes |
| Invalid `dl` in opened events | axe with disclosures open | Yes |
| The conclusion's paragraph printed three times | Screenshot | No: a judgement |
| An inconclusive case opened on the refusal, not its INCONCLUSIVE run | Screenshot | Yes |
| The Overview said one thing three times | Screenshot | No |
| How it works sat inside the evidence block, so its hero link would break with the service down | Review | Partly |
| A nested disclosure broke the single-`details` shape `frontend/e2e` pins | Tests | Yes |
| The product description was dropped from the landing | `status.spec.ts` | Yes |
| The list counter bled into a note: "4 What a verdict does not show" | Screenshot | No |
| "The 0 milestones of 0 records" on an empty case | Scratch fixture | No |
| The honest case's rerun was missing from its Decision | Reading output | Yes |

## Performance

| False completion case, local | Sprint 11 | Sprint 12 |
|---|---|---|
| Product CSS | 37,376 B, 8,005 B gzipped | 44,824 B, 9,080 B gzipped |
| Client JavaScript | 609,160 B | 609,160 B, unchanged |
| Dependencies | | None added |
| Landing HTML, elements | 57,454 B, 257 | 58,890 B, 257 |
| Comparison HTML, elements | 166,441 B, 863 | 168,308 B, 875 |
| Investigator HTML, elements | 140,254 B, 495 | 169,450 B, 784 |
| **Timeline HTML, elements** | **317,308 B, 1,393** | **711,837 B, 4,052** |
| CLS | 0 everywhere | 0 everywhere |
| LCP | 80–490 ms | 80–390 ms |

**The Timeline got heavier, and that is the cost of this design.** Folded records stay in the page so a run opens with
no request and no client code. About 45 KB gzipped on this case. Timings are one local Chromium run and do not predict
hosted performance. The Investigator and Overview also fetch every run, one request each, server side.

## Critique

The Investigator is the sprint's best work. The ladder of `h1`–`h5` with PASS PASS PASS PASS VIOLATION tells the story
before anything opens, and the one-shot page's "this result did not choose it" is the kind of honesty the product exists
for. The Timeline became calm.

What is still not good enough:

- **It is still a lot of words.** The model's prose is long and technical, and it stays verbatim, because rewriting it
  would need a model or an interpretation. "In plain terms" helps at the top of each cycle, and the Decision stage is
  still dense on a phone.
- **Hypothesis titles are engineer's sentences.** `Agent's final claim consistency after a create_customer…` is what was
  recorded. It is the weakest line on the page, and it is the ladder's main text.
- **The Overview is competent, not memorable.** It is a good summary, and it lacks the Comparison's force.
- **The landing below How it works is unchanged.** The list is the "excessive cards" the brief warns of, and System
  status shows a raw setting name, `MOODY_VULTR_API_KEY`, to the public.
- **The Timeline's two-column head wastes space** for rows with a long model sentence, and Hypothesis and Experiment
  rows often say nearly the same thing.
- **Below the Comparison's ledger, Sprint 11's critique still stands.** About and limits were not redesigned.
- **Comprehension is unproven.** Question 4, why the next experiment was chosen, is the hardest, and no reader has tried it.

## Limitations

- `hardened`, budget and cancelled decisions appear in no recorded case. Their rules are tested on derived fixtures, never rendered from real evidence.
- The fault line under Experiment repeats recorded `occurrence` and `span` without explaining them, because their meaning is not plain from the run.
- Decisions compare a cycle with the next one in record order. Rules were exercised on 5 investigations.
- `≠` marks the verdict row only, not each call.
- `Evaluation methodology` links to GitHub, and the repository is private: it 404s for a visitor until the owner changes that.
- The recovery case's journal spans 14 minutes against a recorded runtime of 81 s. The page shows both as recorded. The gap was not investigated.

## Release

Both branches are pushed. Nothing was merged or deployed.

1. **KI-51:** the owner chooses. Hotfix branch for the wording alone, or a deploy of `main` or this branch.
2. **This branch:** review the renders, open a PR, and deploy only with time to run `frontend/e2e-hosted` before the deadline, 2026-11-08 22:00 UTC. It is frontend only, so rollback touches no evidence, ledger or backend state. Anything showing the old site, such as the submission video, would no longer match it.
3. **Still outstanding from Sprint 9:** repository visibility (verified private today), the lablab submission, and rotating the Vultr account key.

## Recommended for Sprint 13

- Run the first-reader test and VoiceOver, and fix what they find, before more design.
- Decide on the causal export: [proposal](../design/investigation-experience.md#causal-evidence).
- Redesign the investigation list and move System status off the public landing.
- Fetch folded Timeline records on demand if larger investigations appear.
- Add a short recorded label to hypotheses, in a future export, to replace the engineer's sentence in the ladder.
- Explain or correct the recovery case's runtime gap.
