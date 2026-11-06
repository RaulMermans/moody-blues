# Sprint 14: Product experience rescue

- **Branch:** `sprint/14-product-experience-rescue`, from `main` at `57da526`, which contains Sprint 13 (`6405817`) and the
  release command. Local only: not pushed, merged or deployed.
- **Worked in:** `~/dev/Moody-Blues`, as the brief and AGENTS.md say. The session started in the Desktop copy, whose local
  `main` was behind.
- **Outcome:** the redesign is built and every automated gate passes. Whether a first-time reader understands it is
  **not yet shown**: no human test ran.

North star: test an agent, understand what happened, investigate why.

## Release preflight, 2026-11-06

| Item | Finding |
|---|---|
| Hackathon submission | **UNKNOWN, treat as critical.** The lablab form needs the owner's sign-in. No record says it was submitted. Working deadline 2026-11-08 22:00 UTC |
| Production | **Up, unchanged.** `/` 200, `/api/status` ready, live inference `not_configured`. Serves the Sprint 13 release |
| KI-51 | **Fixed live.** The honest case's page holds no "wrong status" and says "no false claim" |
| Repository | **Public.** **No LICENSE file**, and GitHub reports none. If the rules need an open license, this is an owner decision |
| Credentials | Rotation of `VULTR_API_KEY` and `MOODY_VULTR_API_KEY` is **not confirmed**. No values were read or printed |
| CI | The last three runs on `main` and the release branch **succeeded**. This branch has no CI run, because it is not pushed |

## UX audit (Sprint 13 build, real browser, 390, 768 and 1440 px)

| Screen | Words | Height at 390 px | Problem |
|---|---|---|---|
| Landing | 748 | 5.3 screens | Poster hero and engineering vocabulary. One action, and it skipped anything you could try |
| Operator | 154 | 1.3 | Bare password box for a visitor, with no idea what the tests are. Mission text in worlds and fixtures |
| Result (default) | 1,112 | 8.5 | Twelve stacked sections, all open |
| Timeline | 996 | 3.5 | Sound, but a fifth concept to learn before finding the result |
| Investigator | 672 | 4.0 | Sound once you know the vocabulary |
| Raw evidence | 294 | 3.3 | Correct at its level |
| Containment | 574 | 5.2 | Reference page. Not redesigned |

Principal findings:

1. **Hierarchy, not verbosity.** Everything sat at one level, so nothing read as the answer. Smaller type would not fix it.
2. **Repetition.** Status appeared in the headline, the strip, the first row, the explanation and the about block.
3. **Linear by construction.** One long column, and the ledger and records came before any summary of what they meant.
4. **Five tabs needed a glossary** before a reader could choose one.
5. **Rehearsals were mislabeled.** A script was "the agent", Python was "written by the model", the outcome read "none", and
   the task read "not in this record". These broke an AGENTS.md rule (KI-63).
6. **The first action skipped the product:** nothing said what could be run.

## New information architecture

**Choose a test → Run the test → See what happened → Explore the evidence.** The map, levels, story rules and state
table are in [product-experience-architecture.md](../design/product-experience-architecture.md). The decision is
[ADR 0011](../adr/0011-result-first-information-architecture.md).

| Before | After | Address |
|---|---|---|
| Overview | Result, now the default | `?view=overview`, unchanged |
| Reality Comparison, the default | What happened | `?view=reality`, unchanged |
| Investigator | Investigation | `?view=investigator`, unchanged |
| Raw evidence | Evidence | `?view=evidence`, unchanged |
| Timeline | Inside Evidence | `?view=timeline`, unchanged |
| Operator | "Run a test" / Choose a test | `/operator`, unchanged |

## What changed

New: `design/outcome.ts`, `design/sequence.ts`, `design/components/story-sequence.tsx`, `components/test-card.tsx`,
`lib/test-catalog.ts`, `e2e-design/experience.spec.ts`.

Rewritten or restructured: `app/page.tsx`, `app/operator/page.tsx`, `app/investigations/[id]/page.tsx`,
`components/overview-view.tsx`, `components/reality-view.tsx`, `components/operator-console.tsx`,
`components/hash-focus.tsx`, `components/investigation-list.tsx`.

Words only: `components/timeline-view.tsx`, `investigator-view.tsx`, `raw-evidence.tsx`, `design/journey.ts`, `story.ts`.

`backend`, `evidence`, `infra` and `tests` are untouched: `git diff 57da526 --stat` over them is empty.

## Measured change

| Screen | Words | Phone height (screens) | Desktop height (screens) |
|---|---|---|---|
| Recorded violation, default address | 1,112 → 380 | 8.5 → 3.0 | 4.6 → 1.5 |
| Rehearsal, default address | 570 → 273 | 5.3 → 2.5 | 3.2 → 1.3 |
| Comparison view | 1,112 → 485 | 8.5 → 4.0 | 4.6 → 2.2 |
| Landing | 748 → 564 | 5.3 → 4.2 | 3.3 → 2.9 |

No page at any of the three widths overflows sideways.

### Performance

Median of 7 interleaved runs, both production builds against one local backend, 1440 px, nothing else running. Raw data:
[perf.json](sprint-14-screenshots/perf.json).

| Page | HTML KB | DOM nodes | LCP ms | CLS |
|---|---|---|---|---|
| Investigation, default | 164.5 → 75.4 | 875 → 351 | 380 → 384 | 0 → 0 |
| `?view=reality` | 164.6 → 166.5 | 875 → 891 | 384 → 388 | 0 → 0 |
| Landing | 56.7 → 53.8 | 252 → 227 | 36 → 44 | 0 → 0.0005 |
| Tests, signed out | 17.9 → 32.7 | 46 → 111 | 36 → 40 | 0 → 0 |

- **Costs:** client JavaScript 470.1 → 474.7 KB and CSS 45 → 51.6 KB on every page. The signed-out tests page is bigger
  because it now holds the catalog.
- **`?view=reality` got no lighter:** folded evidence is still in the HTML, deliberately, so that links and the browser's
  find-in-page reach it.
- LCP did not improve. A tab click took 137 → 135 ms, which is noise. Long tasks are noise at this size.

## Regression results

| Check | Result |
|---|---|
| Python, `make test` | PASS, 871 |
| Docker, `make test-integration` | PASS, 72 |
| Ruff and Pyright, `make lint typecheck` | PASS |
| ESLint, TypeScript, production build | PASS |
| Product E2E on real Docker | PASS, 37 (was 34) |
| Design suite | PASS, 225: Chromium, 8 WebKit, 8 Firefox (was 175) |
| Axe | PASS on landing, tests, Result, inconclusive Result, What happened, and What happened with every fold open |
| Hosted suite | NOT_RUN: nothing was deployed |
| Paid inference | None. Local stacks ran with no provider key and live runs off, or with the suite's canary key and over-limit ledger |

### Tests that changed, and why

Evidence assertions were not weakened. These changed because behaviour changed on purpose:

- **Default address:** comparison tests now name `?view=reality`, so they still cover that view. New tests cover Result.
- **Folds:** tests open the fold with a click before asserting on a call or record.
- **Verdict test id:** Result's seal is `oracle-verdict`, where Overview's was `strip-verdict`.
- **Tabs:** names and count follow the new labels. Timeline is reached through Evidence.
- **Landing:** new proposition and four journey steps. `hero-cta` and `hero-how` are gone.
- **Rehearsal start:** one more click for the confirmation, including in `e2e-hosted`.
- **"Comparison reads in order":** now names the Outcome row, whose label changed.

The suite caught my own mistakes, and those were fixed in the code, not the tests: `rules.spec` rejected reading a live
run's missing outcome as recovery, and `final-polish` needed the followed-run line kept on Result. New tests found KI-62
and a heading-order failure.

## Acceptance gates

"Built" is what automated checks and internal review can establish. "Understood" needs a person.

| Gate | Built | Understood | Note |
|---|---|---|---|
| C14-0 Submission protection | **BLOCKED** | n/a | Production risks are known and nothing was changed. Submission status needs the owner's sign-in |
| C14-A Clear product entry | PASS | NOT_RUN | Both entries fit the first laptop viewport |
| C14-B Guided test selection | PASS | NOT_RUN | Held to the server's catalog by a test |
| C14-C Outcome comprehension | PASS | NOT_RUN | |
| C14-D Visual story | PASS | NOT_RUN | Every step checked against the API for all five recorded cases |
| C14-E Progressive disclosure | PASS | n/a | Evidence complete; deep links open their folds |
| C14-F Evidence fidelity | PASS | n/a | |
| C14-G UX and accessibility | PASS, automated | NOT_RUN | VoiceOver, keyboard by a person and real Safari are NOT_RUN. WebKit here is Playwright's |
| C14-H Regression and release safety | PASS | n/a | No backend change, cost or production change |

Usability: **NOT_RUN.** The script is ready: [usability-sprint-14.md](../testing/usability-sprint-14.md).

## Honest visual critique

- **Better:** Result finally has an answer on it, and the sequence explains a run at a glance.
- **The landing is good above the fold, ordinary below.** The list of investigations is still a long list.
- **What happened is heavier than Result** and still repeats the verdict strip's facts in places. On a phone a violation runs
  4 screens, mostly the agent's long message, which must stay visible.
- **The six-step story is tight at 1440 px.** Step text wraps to four lines, and the labels carry it more than the icons do.
- **The result band has a lot of small labels** for an editorial layout.
- **Investigation and Timeline were not redesigned.** They got wording fixes only, so the jump into them is abrupt.
- **Vocabulary remains at levels 2 and 3:** invariant, world, policy and `run outcome`.

## Remaining limitations

1. **A public visitor cannot run a sample test.** Starting anything needs the operator token, by rule. "Try a sample test" leads
   to the catalog, says so, and offers recorded runs instead. This is the largest gap against the sprint's central design test.
2. No recorded rehearsal exists for visitors to open: `offline_fixture` can never be exported as recorded.
3. The "no target run" state is exercised by no committed bundle, so it is verified as code only.
4. On a phone the inconclusive case's seal starts at 789 px of 844: visible, but only just.
5. Rehearsal task text comes from the catalog, because the record holds none.
6. The landing's CLS rose from 0 to 0.0005, far below any threshold.

## Release risk

| Risk | Level | Note |
|---|---|---|
| Submission outstanding | **Critical** | Independent of this branch. Do not wait for it |
| Video and deck | High if deployed | Stale since Sprint 13, and this moves further: the default view and landing both change |
| Bookmarks to a bare investigation address | Low | Land on Result, same run |
| Hosted suite | Low | Its operator test now expects the confirmation, so it fails against the old release if run with a token before a deploy |
| Backend or data | None | Frontend only |

Recommendation: keep this off production until the submission is confirmed and a person has run the usability script. Nothing
in the submission depends on it.

## Sprint 15 prerequisites

Proposals, none implemented:

1. **Owner decision:** how visitors try a test. Options are a public recorded rehearsal, which needs an AGENTS.md change and a new
   export label, or a rate-limited free route, which needs a security review.
2. Record the mission id and task text in rehearsal evidence, removing the catalog fallback. Backend change.
3. Give reference runs a real `run_outcome`, removing the special case in `story.ts`. Backend change.
4. Run the usability script, then VoiceOver and real Safari, and fold in what they find.
5. A labeled fixture for the "no target run" state.
6. Bring-your-own-agent stays a proposal. It needs a contract and a sandbox review before any UI.
7. Bring Investigation and Timeline into the same structure, if the human test says so.
8. Re-record the video and deck.

## Screenshots

[sprint-14-screenshots/](sprint-14-screenshots/): `before/` holds the Sprint 13 build, `after/` the final build. Names:
`landing`, `tests`, `tests-confirm`, `tests-public`, `rec-*` safe recovery, `blind-*` blind retry, `viol-*` real AI violation,
`honest-*`, `recov-*` real AI recovery, `neg-*`, `inc-*`, and `viol-evidence-open` for expanded evidence, each at its width.
