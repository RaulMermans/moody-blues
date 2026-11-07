# Publication plan for v0.1.0

Everything here is **prepared, not done**. Each action is external or irreversible, and needs the owner's explicit approval at
the time. A general instruction to work on the sprint is not approval.

## Order

| # | Action | Blocked on |
|---|---|---|
| 0 | Confirm the hackathon submission | Owner. Deadline 2026-11-08 22:00 UTC. Independent of everything below |
| 1 | ~~Choose a license and apply it~~ Done: MIT, 2026-11-07 | [Decision](license-decision.md) |
| 2 | Confirm credential handling | Owner. See below |
| 3 | Run the [independent developer test](../testing/independent-acceptance.md) | A participant |
| 4 | Fix what it finds, then rerun the affected checks | 3 |
| 5 | Push the branch and open a pull request | Owner approval |
| 6 | Merge | Owner approval |
| 7 | Tag and create the GitHub release | Owner approval |
| 8 | Change the repository description | Owner approval |
| 9 | Decide the public demo | Owner approval. Below |

Publishing the SDK to a package index is not part of v0.1.0: it installs from a checkout.

## Credential verification

Do not paste keys into a tool, a log or an issue. In the Vultr console:

1. Open the API settings. Confirm the account key's creation date is after 2026-11-05, when it was recorded as exposed to iCloud.
2. Confirm the old key is revoked, and the access-control list is what you expect.
3. Do the same for the inference key.
4. Confirm neither `VULTR_API_KEY` nor `MOODY_VULTR_API_KEY` remains in `~/Desktop/GitHub/Moody-Blues/.env`.
5. Tell the release owner "rotated", or give the date. Procedure: [key rotation](../security/key-rotation.md).

## Release commands

Run only after approval, from the merged commit on `main`:

```sh
git tag -a v0.1.0 -m "MOODY BLUES v0.1.0, developer alpha" <commit>
git push origin v0.1.0
gh release create v0.1.0 --prerelease --title "MOODY BLUES v0.1.0, developer alpha" --notes-file docs/release/v0.1.0.md
gh repo edit RaulMermans/moody-blues --description "Test what agents do. Verify what actually happened. Controlled faults, independent verification and reproducible evidence for AI agents."
```

Source archive: GitHub generates it from the tag. To make one locally and record its checksum:

```sh
git archive --format=tar.gz --prefix=moody-blues-0.1.0/ -o moody-blues-0.1.0.tar.gz v0.1.0
shasum -a 256 moody-blues-0.1.0.tar.gz
```

SDK, from a checkout of the tag: `uv build sdk/python`, or `pip install ./sdk/python`.

## Public demo: two options

**Decided 2026-11-07: Option B, at the owner's request.** `9a3f263` was deployed with `make release`, replacing `6405817`.
The hosted tests passed (14 passed, and 2 skipped: operator sign-in and the paid live run). Rollback: `infra/vultr/rollback.sh 45.63.119.197`.

### Option A: keep the hackathon deployment unchanged (recommended until judging ends)

It shows the five recorded investigations, the containment report, and the Sprint 13 design. It does **not** have Job Queue World,
external agents, the Sprint 14 to 20 interface work, experiment validity or the new copy. Live mode is off, and no provider key
is on the VM. It stays billing until destroyed, from `~/dev/Moody-Blues`, which holds its state. Nothing the judges were shown changes.

### Option B: deploy v0.1.0 after approval

Only after judging, because the submission video and deck show the site as it is.

| Requirement | State |
|---|---|
| Release gates passed | See the [Sprint 20 record](../sprints/sprint-20.md) |
| Infrastructure configuration verified | `make deploy-lint`, `make release-check REF=<commit>` |
| Database and artifact compatibility | Evidence schemas 1 to 3 stay readable; the VM's ledger stays canonical and must not be replaced |
| No secret exposure | Gitleaks on the release commit |
| Rollback | `infra/vultr/rollback.sh 45.63.119.197`, which returns to the previous release |
| Manual approval | Owner. `make release REF=<commit>` asks for a typed confirmation |
| Production smoke | `make test-hosted`, then `curl .../api/status`, which then reports `revision` |
| Accurate public claims | Check the landing page against [limitations](../evaluation-and-limitations.md) |

Never enable public paid inference, and never open agent execution to unauthenticated visitors.
