# Sprint 13: Final Product Polish

- **Date:** 2026-11-06
- **Branch:** `sprint/13-final-product-polish`, from `main` `4060c8f`, which holds Sprint 12 and the KI-51 merge. Merged by PR #18 as `88d3363`.
- **Deployed:** `6405817` on 2026-11-06, at the owner's request. Its tree equals `main`.
- **Working folder:** `~/Desktop/GitHub/Moody-Blues`, by the owner's decision. See KI-61.
- **Outcome:** `DEPLOYED`. No person has used it yet.
- **Inference spend this sprint:** $0. No model was called. No backend, Oracle, contract, evidence, infrastructure or rule-copy file changed.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C13-0 Production and submission preflight | **PASS** | Every blocker identified, with a plan that does not depend on this sprint: [release-sprint-13.md](../deployment/release-sprint-13.md) |
| C13-A Visual consistency | **PASS, with limits** | Containment and the list moved onto the shared system. The team's judgement from renders; the owner has yet to review |
| C13-B Overview | **PASS** | Outcome and next action on the first screens, tested on all 5 cases |
| C13-C Investigator readability | **PASS by inspection. Comprehension untested** | Phone page 3,826 → 3,352 px, no recorded text changed. Whether a reader can follow it is C13-F |
| C13-D Timeline performance | **PASS** | Measured adequate, so no code changed. Every record reachable, tested on all 5 bundles |
| C13-E Landing clarity | **PASS** | No setting name on the page or in `/api/status`. Whether a stranger understands it is untested |
| C13-F Usability validation | **NOT_RUN** | `HUMAN_TEST_NOT_RUN`. No participant was available. Script and heuristic evaluation: [usability-session.md](../testing/usability-session.md) |
| C13-G Accessibility | **Automated PASS. Manual NOT_RUN** | axe, keyboard, headings, motion and contrast pass. VoiceOver and real Safari were not performed |
| C13-H Release readiness | **PASS** | `make check` exit 0, deployed, hosted suite 14 passed with 2 NOT_RUN. See Deployment |

## C13-0 Preflight, 2026-11-06

| Item | Finding |
|---|---|
| Public application | **Up.** `/` and `/containment` return 200, `/api/status` reports ready |
| Production revision | `d592879` by the Sprint 9 record, equal to `967dc88`. CSS hash `f5120e40…c91` unchanged. Inferred, not read from the host. Backend uptime was 15.7 hours at 08:42 UTC |
| GitHub CI | **Failing, no signal.** Every recent run ends in 3–4 s with no job started. Consistent with the account billing block. Not rechecked at the billing page |
| Repository | **Public**, verified with `gh`. The Sprint 12 record said private. The methodology link now returns 200 |
| Hackathon submission | **UNKNOWN.** The lablab form needs the owner's sign-in. No record says it was submitted. Treat as outstanding |
| KI-51 | **Still live** on `inv_4e32358d2ff9`. Fixed on `main`. The isolated fix is commit `6dafdda`, not the hotfix branch, which merged `main` |
| Credentials to rotate | `VULTR_API_KEY` (account) and `MOODY_VULTR_API_KEY` (inference). Both names are still in the Desktop `.env`, which iCloud syncs, and which is now the working folder. Rotation is not confirmed. Values were not read. See [key-rotation.md](../security/key-rotation.md) |
| Video and deck | Match the deployed site. They would **not** match `main` or this branch |

`backend` and `infra` on `main` are identical to the deployed release. Apart from the frontend, only `evidence/live/` differs, and
it is not served. A deploy of this branch is a frontend change.

## Audit, before fixes

From renders at 390, 768 and 1440 px and browser use. [Before images](../design/screenshots/sprint-13/before/).

| # | Finding | Severity | Now |
|---|---|---|---|
| 1 | `MOODY_VULTR_API_KEY`, a request id and `development` on the public landing. `/api/status` also returned uptime and error reasons | P1 | Fixed at the proxy, KI-60 |
| 2 | Overview had no next action. Four equal links closed the page | P1 | One primary action, one for the path |
| 3 | The reason for an experiment sits in the previous cycle, so opening h5 lands past it | P1 | Link back to that Decision |
| 4 | About and limits fully open on the Overview, 700 px on desktop | P2 | Folded, as on the other views. The recorded note stays visible |
| 5 | Run progression buried in long hypothesis sentences | P2 | Verdict tally, titles clamped, shown run emphasised |
| 6 | Model prose outweighed outcomes in the Investigator | P2 | Clamped with a control. Hairline marks the model's words |
| 7 | Stage labels did not say whose words followed | P2 | They do now |
| 8 | Landing list boxed, unlike every other surface. "Inconclusive Inconclusive" on one row | P2 | Rules only, tag deduplicated |
| 9 | Containment in a narrower column, with boxed cards and older headings | P2 | Shared width, headings and rules |
| 10 | Oracle seal alone on its own row in each Observation | P3 | Beside the facts from 1,100 px |

Left alone: the Comparison, the Raw Evidence view and the landing order, which already matched the brief. "Recorded investigation"
stays on every list row because `frontend/e2e` pins it.

## Defects found

| Problem | Found by | Now tested |
|---|---|---|
| KI-58: an unknown run id read "No target run took place", on a case with five runs | Reading the code | Yes |
| KI-59: "Show the full text" on text that already fit | New test | Yes |
| KI-60: server details in public status. Still in the deployed release | Audit | Yes |
| KI-62: PASS on an Inconclusive case with no scope note on the Overview | Reading a screenshot | Yes |
| Doubled tag on one list row | Audit | Yes |

## Changes that did not ship

- **Plain anchors in Timeline records.** Built on a theory that `next/link` caused the phone's long task. An interleaved A/B
  showed no change, so it was reverted. An earlier reading of 143 → 96 ms was noise from a test suite on the same machine.
- **Lazy mounting.** Its best case was measured and not built: [timeline-performance.md](../design/timeline-performance.md).

## Before and after

| | Before | After |
|---|---|---|
| Overview | ![](../design/screenshots/sprint-13/before/overview-desktop.png) | ![](../design/screenshots/sprint-13/after/overview-desktop.png) |
| Investigator, phone | ![](../design/screenshots/sprint-13/before/investigator-mobile.png) | ![](../design/screenshots/sprint-13/after/investigator-mobile.png) |
| Landing | ![](../design/screenshots/sprint-13/before/landing-desktop.png) | ![](../design/screenshots/sprint-13/after/landing-desktop.png) |
| Containment | ![](../design/screenshots/sprint-13/before/containment-desktop.png) | ![](../design/screenshots/sprint-13/after/containment-desktop.png) |

All screens at 390, 768 and 1440 px: [before](../design/screenshots/sprint-13/before/), [after](../design/screenshots/sprint-13/after/).
Also [the inconclusive case](../design/screenshots/sprint-13/after/inconclusive-overview.png) and
[the link back to a decision](../design/screenshots/sprint-13/after/why-link.png).

## Measurements

Local production build, `inv_d0bc87de6010`, Chromium. Timings are local and do not predict hosted performance.

| | Sprint 12 | Sprint 13 |
|---|---|---|
| Client JavaScript | 609,160 B | 608,715 B |
| Product CSS | 44,824 B, 9,080 B gzipped | 46,096 B, 9,238 B gzipped |
| Dependencies added | | None |
| Landing, phone height | 4,366 px | 4,142 px |
| Overview, phone / desktop height | 3,308 / 1,879 px | 2,442 / 1,460 px |
| Investigator, phone / desktop height | 3,826 / 2,616 px | 3,352 / 2,469 px |
| Timeline HTML | 712,333 B, 39,018 B gzipped | 712,333 B, 39,017 B gzipped |
| Investigator HTML | 169,606 B | 173,450 B |
| Horizontal overflow, 8 routes × 3 widths | 0 | 0 |
| CLS | 0 | 0, except 0.024 on a phone deep link into a cycle, when the text control appears after hydration |

The Investigator's HTML grew because each long text now crosses to a client component as a prop.

## Verification

Run on the committed code.

| Check | Result |
|---|---|
| ESLint, `tsc`, Next.js production build | PASS |
| Backend, `make test` | PASS, 870 |
| Docker integration and containment, `make test-integration` | PASS, 72 |
| Product e2e, `make test-e2e` | PASS, 34, specs unmodified |
| Design, rules, axe and browsers, `make test-design` | PASS, 175: 8 WebKit, 8 Firefox, the rest Chromium and no-browser |
| `make recorded-verify` | PASS |
| Hosted tests, after deploying | PASS, 14. 2 NOT_RUN: operator journey (no token given) and the live model run (not authorized) |
| VoiceOver, real Safari, stock Firefox, a real phone | NOT_RUN |
| User testing | NOT_RUN |

**Evidence integrity.** `git diff` from `main` is empty for `backend`, `evidence`, `tests`, `infra`, `frontend/e2e`,
`frontend/e2e-hosted`, `story.ts`, `journey.ts` and `model.ts`. New tests compare the page with the API for every recorded text,
every timeline record and hash in order, and every verdict count. `NO_DEMONSTRATED_ADVANTAGE` still comes from the study record.

**Test changes.** Nothing existing was weakened. `final-polish.spec.ts` is new. `MOODY_E2E_FIREFOX=1` adds an opt-in browser.

## Critique

The Overview is the sprint's clearest gain: it now ends in a decision about where to look. The link back to a Decision matters
more than its size suggests, since that question is the hardest one the product asks of a reader.

What is still not good enough:

- **Nobody has used it.** Every judgement here is the team's. This is the largest gap, and no amount of polish closes it.
- **Hypothesis titles are still engineer's sentences.** Clamping shortens them and does not improve them. A better title needs a
  recorded label in a future export, because rewriting them would misquote the record.
- **Recorded names stay opaque:** `w-e1`, `phantom_success`, `obs_5`.
- **"Oracle" is undefined until How it works.**
- **The list on the landing is still long**, with one tag repeated five times because a test pins it.
- **The tablet width got the least attention.** No overflow, and renders were captured, but only phone and desktop were read closely.

## Deployment

The owner chose the most up-to-date version over the wording fix alone, so `6405817` shipped, replacing `d592879` by `deploy.sh` from
a detached tree. Checked from outside the VM afterwards:

| Check | Result |
|---|---|
| `/`, `/containment`, `/operator`, Overview, Timeline, Investigator | 200 |
| KI-51 | Gone from the public page: 0 occurrences of "wrong status" |
| `/api/status` | Named fields only, no setting name, backend connected |
| CSS | SHA-256 `135f1acf…`, replacing `f5120e40…` |
| Hosted suite | 14 passed, 2 NOT_RUN |

Rollback, if needed: `infra/vultr/rollback.sh 45.63.119.197`. It returns to `d592879`, which still carries KI-51 and KI-60.

Deployments now go through `make release REF=<commit>`. It was tested on a scratch repository with a stub `deploy.sh`, against the
live site read-only: refusal of an unpushed commit, a wrong confirmation, the full path, a failure, and cleanup. It has not yet
carried a real deployment.

## Remaining owner decisions

1. **Submit on lablab** before 2026-11-08 22:00 UTC.
2. **Decide on the video and deck.** They show the pre-Sprint 11 site, so they no longer match it. Rebuilding needs the operator
   token and `.artifacts/submission`, which is in `~/dev`.
3. **Rotate both Vultr keys**, and remove them from the Desktop `.env`.
4. **Run the first-reader test and VoiceOver.** Enable "Allow remote automation" in Safari if real Safari should be automated.
5. **Update `AGENTS.md`**, which still says not to develop in the Desktop folder. It was left unchanged as the owner's call.
