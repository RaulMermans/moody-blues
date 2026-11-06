# Release plan: KI-51 hotfix and Sprint 13

**Outcome, 2026-11-06:** the owner chose Option B. `6405817` is deployed and PR #18 merged it to `main`, so Option A is no longer
needed. The rest of this file is the plan as written before that. See the [Sprint 13 record](../sprints/sprint-13.md#deployment).

## Deploying from now on

```bash
make release-check REF=origin/main   # read-only: what would ship, and what is live now
make release REF=origin/main         # asks for the short sha, deploys, checks the public site
```

It ships exactly that commit from a temporary detached tree, so the current branch and uncommitted work do not matter. It refuses
a commit that is not on GitHub, and it never runs by itself: every deployment needs the owner's approval. Merging to `main` does
**not** deploy. It uses `~/.ssh` and needs nothing from `.artifacts`. If a check fails it prints the rollback command and does not
roll back on its own.

## Starting production

| | |
|---|---|
| Site | https://45-63-119-197.sslip.io, `/` and `/containment` return 200 on 2026-11-06 |
| Release | `d59287981410c10cd532f404a5f918d02bcddc46` by the Sprint 9 record. `967dc88` has identical `frontend`, `backend` and `infra`. Inferred, not read from the host |
| Fingerprint | CSS SHA-256 `f5120e40…c91`, the pre-Sprint 11 release. Unchanged on 2026-11-06 |
| KI-51 | Live when this was written. "wrong status" was on the public `inv_4e32358d2ff9` page |

`deploy.sh` ships `HEAD` of the checkout it runs in, so the checkout decides what goes out. Run these from your own terminal:
SSH from an agent session has been refused by its permission layer. A deploy also needs `~/.ssh` access to the VM.

## Option A: KI-51 alone (recommended first)

Two files on the deployed line: the wording rule and its test. No restyle, so the site still matches the video and deck.
It was tested in Sprint 12 (33 product e2e, lint, types, build) and not again in Sprint 13.
**Do not deploy `hotfix/ki-51-disclosure-wording`.** That branch has since merged `main` and carries the restyle. The isolated
fix is commit `6dafdda`.

```bash
cd ~/Desktop/GitHub/Moody-Blues
git worktree add --detach /tmp/mb-ki51 6dafddafff7a9a4d303579864c6b458cdec12df0
cd /tmp/mb-ki51
infra/vultr/deploy.sh 45.63.119.197 45-63-119-197.sslip.io

# Must print 0, then 200.
curl -s 'https://45-63-119-197.sslip.io/investigations/inv_4e32358d2ff9' | grep -c 'wrong status'
curl -s -o /dev/null -w '%{http_code}\n' https://45-63-119-197.sslip.io/containment

# Public checks, using the same tree's test suite. Paid runs stay off: MOODY_HOSTED_LIVE is unset.
cd frontend && pnpm install --frozen-lockfile && cd ..
MOODY_HOSTED_URL=https://45-63-119-197.sslip.io MOODY_HOSTED_TARGET=vultr make test-hosted
```

Rollback: `infra/vultr/rollback.sh 45.63.119.197`. Then remove the worktree: `git worktree remove /tmp/mb-ki51`.

## Option B: Sprint 13 (the whole restyle)

Carries everything on `main` since the deployed release, plus Sprint 13. It includes the KI-51 fix and removes the public
setting name (KI-60). Sprint 13 itself changes no backend file. See the record for what else differs from production.

```bash
git push origin sprint/13-final-product-polish     # then review and merge by PR
cd ~/Desktop/GitHub/Moody-Blues && git switch main && git pull --ff-only
git status --short                                 # must be empty, deploy.sh refuses otherwise
infra/vultr/deploy.sh 45.63.119.197 45-63-119-197.sslip.io
MOODY_HOSTED_URL=https://45-63-119-197.sslip.io MOODY_HOSTED_TARGET=vultr make test-hosted
```

Rollback: `infra/vultr/rollback.sh 45.63.119.197`, or name a release with
`infra/vultr/rollback.sh 45.63.119.197 d59287981410c10cd532f404a5f918d02bcddc46`. The script keeps the three newest releases plus
current and previous. State under `/var/lib` is untouched, so evidence and the ledger are unaffected.

## Risks

| Risk | Detail |
|---|---|
| **The video and deck show the old site** | They were captured from the pre-Sprint 11 release. After Option B the site no longer looks like them. The landing, Investigator and Comparison scenes are all restyled, and the Overview and Timeline tabs are new. The story and evidence match; the screens do not. Rebuilding needs the operator token and `.artifacts/submission`, which is only in `~/dev` |
| The hosted suite has not run against this code | `frontend/e2e-hosted` needs a deployment. NOT_RUN |
| GitHub CI gives no signal | Every run fails in about 3 s with no job started, consistent with the account billing block. Local results are the only evidence |
| Build on the VM | `remote-install.sh` builds from the lockfile on the VM. Allow several minutes, and do not deploy close to the deadline |

## Recommendation

1. **Submit first**, using the current video and deck. Submission does not depend on any release here.
2. Deploy **Option A** when convenient, because it corrects a false statement on a public page and changes nothing else.
3. Treat **Option B** as a decision, not a default. Deploy it only if a stale video is acceptable, or the video is rebuilt, and
   with at least several hours left to run the hosted suite and roll back.
