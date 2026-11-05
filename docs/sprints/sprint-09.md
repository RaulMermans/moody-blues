# Sprint 9: final release and submission

- **Date:** 2026-11-05
- **Branch:** `sprint/09-final-submission`, from `origin/main` `36cf89f`, merged as PR #11. Then `sprint/09-release-evidence`.
- **Outcome:** `NOT YET ACCEPTED`: the official submission is outstanding.
- **Inference spend this sprint:** $0.104022 by ledger estimate.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C9-A Release security and integrity | **PASS** | CI green on PR #11, secret fix verified on the VM. The account key's rotation remains an owner action |
| C9-B Hosted live investigation | **PASS** | [`inv_cbd07a262444`](../../evidence/live/README.md): no violation found |
| C9-C Product clarity | **PASS** | Deployed at `d592879` |
| C9-D Video | **PASS** | 4:30, built from the public site |
| C9-E Slides | **PASS** | 9 pages, working links |
| C9-F Public repository | see below | |
| C9-G Hosted release | see below | |
| C9-H Submission | **BLOCKED_BY_CREDENTIALS** | The lablab form needs the owner's sign-in |

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

## Hosted live run

Approved by the owner at a $7.30 limit. One job, no retry. Model calls went to `api.vultrinference.com`. 11 sandbox
executions ran on the VM with networking off. The agent used real CRM tools and recovered each time; all three
runs got an Oracle PASS. The third experiment ended `sandbox_exit_nonzero`. Afterwards live mode was off, the key
gone, the limit back at $5, and no sandbox left.

## Assets

Captured from the public site. The hosted run's view was captured signed in, because it is operator-only.

The video is real captures panned with cuts, not a live screen recording. Narration is synthetic.

## Open

- The event rules and live form were not read. The video's length and format follow the brief's defaults only.
- No license was chosen, so all rights stay reserved. Dependency licenses were reviewed: permissive, plus MPL-2.0 and one LGPL binary (`sharp-libvips`) that is not vendored.
- The hosted run is not on the public site. Showing it would need a curated export, a feature after the gate.
- KI-49 stays open.
- Destroy the VM after judging: only destruction stops billing.
