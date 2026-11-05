# Sprint 9: final release and submission

- **Date:** 2026-11-05
- **Branch:** `sprint/09-final-submission`, from `origin/main` `36cf89f`. Local only: not pushed.
- **Outcome:** `NOT YET ACCEPTED`. Assets are built locally. Nothing was pushed, deployed, published or uploaded,
  on the owner's instruction.
- **Inference spend this sprint:** $0.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C9-A Release security and integrity | **BLOCKED_BY_APPROVAL** | Fixes are local. `main` CI is still red until the race fix is pushed. The account key is still in iCloud |
| C9-B Hosted live investigation | **BLOCKED_BY_APPROVAL** | Not run. Readiness checks passed; see below |
| C9-C Product clarity | **BLOCKED_BY_APPROVAL** | Built and tested locally; not deployed |
| C9-D Video | **BLOCKED_BY_APPROVAL** | Built from the local release candidate; needs recapture after deployment |
| C9-E Slides | **BLOCKED_BY_APPROVAL** | Built; the Limits card must be updated after the live run |
| C9-F Public repository | **BLOCKED_BY_APPROVAL** | Private. No license chosen. Secret scan clean |
| C9-G Hosted release | **NOT_RUN** | Only the read-only preflight was done |
| C9-H Submission | **NOT_RUN** | The event rules and form were not read |

## What the brief had out of date

- `main` held PR #10 as well as PR #9, and CI failed on its merge (KI-46).
- The ledger's limit is $5 and settled is $6.500182, so spending stays refused until the limit is raised.

## Preflight on 2026-11-05

- Site, `/containment`: 200. Let's Encrypt certificate valid to 2027-02-03. Ports 3000, 8000, 8080, 5432, 2375 closed.
- VM on release `cb28311`; services active; live off; no key; `ledger-verify` above floor; `recorded-verify` PASS; 0 sandboxes.
- Vultr account: $200 credit, $3.97 pending. That matches Sprint 8 despite more VM hours, so it may lag.
- `glm-5.3` listed by the provider. One instance on the account.
- gitleaks over all refs: 78 non-merge commits, 3.37 MB. One finding, a made-up constant in a new test, recorded by fingerprint.

## What changed

- **Live switch** (KI-47): see `infra/vultr/live-env.py`.
- **Bootstrap** removes the image's open SSH rule (KI-48).
- **Restart test** race fixed (KI-46).
- **Landing page:** tagline, problem, five stages near the top, the task from the run's own record, and a repository link.
- **Inference status** reads "Off between authorized runs" when no key is set. The backend's detail is unchanged.
- **Verdict strip** says "2 records committed, 1 required". "2 duplicate records" suggested two extras.
- **Submission pack:** [docs/submission](../submission/README.md). Rotation checklist: [key-rotation.md](../security/key-rotation.md).

## Assets

The public site still runs the earlier UI, so captures came from a local production build of this branch, with no
provider key, serving the committed evidence and the committed Vultr containment report.

The video is real captures panned with cuts, not a live screen recording. Narration is synthetic. It holds no
hosted live footage, because no hosted live run exists.

## Open

- The event rules and live form were not read. The video's length and format follow the brief's defaults only.
- No license. Commit history exposes the owner's email address if the repository goes public.
- Third-party dependency licenses were not reviewed.
- KI-49 stays open.
- Destroy the VM after judging: only destruction stops billing.
