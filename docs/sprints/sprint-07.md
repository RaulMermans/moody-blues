# Sprint 7: Investigation Explorer, product experience and local release

- **Date:** 2026-11-05
- **Branch:** `sprint/07-product-experience`, from Sprint 6 HEAD `da5c18a`. Not pushed.
- **Outcome:** recorded product and operator lifecycle `ACCEPTED` locally. **C7-D is not a pass: no real
  model-driven investigation was started from the application.** GitHub Actions has not run.
- **Live spend this sprint:** $0.00.

## Goal

Let a judge open MOODY BLUES, understand an investigation, compare what the agent believed against what
really happened, and inspect verified evidence, without reading source code.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C7-0 Stable repository | **PASS** | Moved to `~/dev/Moody-Blues`. 3,187 files hash-matched, `git fsck` clean, 0 dataless files. Disk is still 98% full; the Desktop original is kept |
| C7-A Investigation journey | **PASS** | Playwright follows `inv_d0bc87de6010` from hypothesis to Oracle verdict |
| C7-B Evidence API | **PASS** | Pydantic contracts over persisted evidence; the UI holds no result objects |
| C7-C Recorded investigations | **PASS** | 5 live `glm-5.3` cases, 728 KB, rebuilt byte for byte from source |
| C7-D Controlled live investigation | **BLOCKED_BY_BUDGET** | The full path works with a free rehearsal on real Docker. The real ledger refuses a live mission ($6.40 settled of $5.00), which is correct. Running one needs the owner's authorization |
| C7-E Product usability | **PASS**, with a limit | Keyboard, 390 px, error and empty states tested. The 30-second goal was not measured with a person |
| C7-F Budget governance | **PASS** | Ledger byte-identical before and after a refused live request; no test calls a provider |
| C7-G Automated and browser testing | **PASS** | 793 offline, 71 Docker, 28 Playwright, 0 skipped. Real live journey **NOT_RUN** |
| C7-H Local release readiness | **PASS** for recorded and rehearsal use | Production build, clean-clone startup, restart. [Blockers for hosting](../deployment/sprint-8-readiness.md) |

GitHub CI: **NOT_RUN**. `ci.yml` changed (Explorer tests, pinned image for E2E) and has not executed.

## What was built

- **Evidence projection** (`explorer/projection.py`): verified records become a public bundle. Each
  timeline entry comes from one journal record and carries its hash.
- **Recorded export** (`explorer/recorded.py`, `make recorded-export`, `make recorded-verify`).
- **Evidence API** and **operator API**: [contracts](../architecture/evidence-api.md).
- **Job worker** (`explorer/jobs.py`): one in-process worker, state on disk, journal-tailed progress,
  SSE with replay, polling fallback, restart reconciliation.
- **Missions** (`explorer/missions.py`): two free rehearsals and one bounded live mission.
- **Frontend**: Overview, Reality Comparison, Timeline, Investigator and Operator.

[Design](../architecture/product-experience.md) · [ADR 0007](../adr/0007-investigation-explorer.md) ·
[Threat model](../security/threat-model.md) · [Screenshots](sprint-07-screenshots/)

## Problems found and fixed

1. **The evidence scan refused every bundle** (KI-36): it read escaped JSON. It now reads decoded strings.
2. **Sandbox steps appeared after the run they requested**, because completion time sorted them. They now
   use their recorded start.
3. **A rehearsal said a model concluded** (KI-37) when no model ran. Fixture runs now say fixture
   throughout. This was found by looking at a screenshot, not by a test.
4. **No run said what its target was.** A reference script and a live model looked alike on the comparison
   page. Each run now states it.
5. **The detail page hid the comparison** below a screen of metadata. Context moved beneath it.
6. **Screenshots showed a loading panel** while assertions passed, since streamed content can precede its
   swap (KI-38). The helper now waits for the loading text to leave.
7. **An unread sign-in response stayed open.** Reading the trace showed the event stream was fine, and this
   request was the leak.
8. **Job record updates could undo each other** between cancellation and the worker. Updates now apply to
   the latest record under a lock.
9. **Each in-flight refresh reloaded the status** when a job ended. It now happens once.

## Budget

No provider call was made. Ledger: $6.402831 settled, unchanged. Estimated project total: about $6.90,
because Sprint 3's $0.50 predates the ledger. **Actual billing has not been checked.**

## Resource usage

Measured on the local production build after 200 page loads:

| Measure | Value |
|---|---|
| Backend RSS | about 48 MB |
| Next.js RSS | about 207 MB |
| Detail page response | 13 ms |
| Evidence API response | 1.4 ms, 31 KB |
| Browser static assets | 664 KB |
| Recorded evidence | 728 KB |
| Rehearsal, start to evidence | about 4 s |
| Leftover sandbox containers | 0 |

## Limits

- The reachable-by-people claim is unmeasured: no judge has used this.
- `offline_fixture` rehearsals prove the job path, not model behavior.
- The restart test on real Docker kills the server while running, at whatever point it has reached. The
  specific case of a target run left open is proven by a separate SIGKILL test with a scripted sandbox.
- One server process only. See [ADR 0007](../adr/0007-investigation-explorer.md).

## Readiness for Sprint 8

Ready for hosted preflight, in this order: authorize one local live verification, read actual billing, then
work through [the checklist](../deployment/sprint-8-readiness.md). Exposing the backend directly is the one
thing that must not happen, because `/sandbox/smoke` needs no token.
