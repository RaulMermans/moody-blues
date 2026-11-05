# Sprint 8: Vultr deployment, hosted containment and production acceptance

- **Date:** 2026-11-05
- **Branch:** `sprint/08-vultr-deployment`, from `origin/main` `d4c8c30`, whose tree equals Sprint 7 HEAD
  `71eace8`. Not pushed.
- **Outcome:** `NOT ACCEPTED`. **Deployment is prepared and rehearsed. Nothing is deployed.** Work stopped at
  the provisioning boundary for owner approval.
- **Live spend this sprint:** $0. No provider call was made. No Vultr resource exists.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C8-A Repository integrity | **PASS**, one item blocked | Outside iCloud, 0 dataless files, `git fsck` clean, recorded evidence verified, full-history secret scan clean, pinned image has a linux/amd64 entry. **Billing not inspected:** no account credential here |
| C8-B Infrastructure plan | **PASS** | [Provisioning plan](../deployment/sprint-8-provisioning-plan.md), `make vultr-plan` reads live prices, refusal paths tested |
| C8-C Secure hosted architecture | **BLOCKED_BY_APPROVAL** | Rehearsed locally only |
| C8-D Sandbox containment | **BLOCKED_BY_APPROVAL** | Eight attempts held on local Docker. That is not Vultr evidence |
| C8-E Containment demonstration | **BLOCKED_BY_APPROVAL** | Page and report built. It shows `LOCAL DEVELOPMENT, NOT HOSTED` |
| C8-F Budget governance | **BLOCKED_BY_APPROVAL** | Controls tested offline. Migration and billing comparison not run |
| C8-G Hosted browser validation | **BLOCKED_BY_APPROVAL** | Suite written; dress rehearsal only |
| C8-H Operational durability | **NOT_RUN** | Needs the VM. Sprint 7's local restart tests still pass |
| C8-I Release readiness | **BLOCKED_BY_APPROVAL** | No URL, hosted evidence or live run ID yet |

## What the brief had out of date

- **Sprint 7 had been pushed and merged:** PR #8, into `main`. The Sprint 7 record says otherwise because it was
  written first.
- **GitHub CI had run, and failed:** the Playwright job, on PR #8 and on `main` (KI-40). It failed installing
  system packages, before any test. Python, frontend and Docker jobs passed. The Playwright suite has
  therefore never passed on GitHub.
- **$0.06/hour buys a 1 GB disk** (KI-43).

Confirmed as stated: 793 / 71 / 28 tests with none skipped, before any change. `inv_ab4479c3fe80` matches its
record. The ledger shows $6.500182 settled, 814 entries, none open.

## What was built

- **Infrastructure** ([guide](../deployment/vultr-deployment.md), [ADR 0008](../adr/0008-single-vm-hosting.md)):
  provisioning, bootstrap, atomic releases, automatic rollback, ledger migration, Caddy, systemd.
- **Secure cookie:** `MOODY_PUBLIC_ORIGIN` replaces the request URL and Host header.
- **Ledger floor:** a lost ledger refuses spending, where it used to look like a fresh start.
- **`containment-report`** and the Containment page. Only the instance metadata service can mark a report hosted.
- **`/sandbox/smoke`** is not mounted in production.
- **Hosted Playwright suite**, which starts no server, so a pass cannot come from a local one.
- **CI:** pinned to Ubuntu 24.04, plus secret scan and deployment lint. Not yet run.

## Dress rehearsal

The release from `git archive`, built with `--no-dev` in a fresh Ubuntu 24.04 container, as the two service
users, with production settings, the real Caddyfile on a private certificate, and real sandboxes. arm64, in a
container, without systemd. **This is not hosted evidence.**

| Check | Result |
|---|---|
| Hosted suite, `local-tls-proxy` | 13 passed; 3 not run (2 need the real host, 1 needs live authorization) |
| Rehearsal through TLS: sign-in, progress, evidence, sign-out | Passed; the cookie is Secure, httpOnly, Strict |
| `investigator-preflight` as the service user | PASS, 19 checks |
| Containment attempts | 8 of 8 held |
| Listeners | 8000 and 3000 on loopback only |
| Ledger below floor | Refused |
| Smoke route in production | 404 |
| `systemd-analyze verify`; ufw rule; `dockerd --validate` | Passed |

**Never executed:** `bootstrap.sh`, `remote-install.sh`, `remote-switch.sh`, `deploy.sh`, `rollback.sh`,
`migrate-ledger.sh`, `live-switch.sh` and `provision.sh apply` or `destroy`. They passed shellcheck, and their
steps were mirrored by hand. Expect first-run fixes on the VM.

## Problems found and fixed

1. **Every deploy would have rolled itself back** (KI-41): `investigator-preflight` wrote into the read-only
   release. Only the rehearsal found this.
2. **CLI commands used a second, empty ledger** on a host (KI-41): the same cause, and exactly the silent reset
   this sprint had to prevent.
3. **Three ledgers bypassed settings**, so they would have skipped the floor. A test now forbids direct
   construction.
4. **E2E runs rewrote committed screenshots.** They are now opt-in.
5. **A secret scan reported clean after reading 0 bytes** (KI-42). The real scan found one false positive,
   recorded by fingerprint.
6. **A commit landed broken** (`1405f2f`, a missing import) because a chained command did not stop on failure.
   Fixed forward in `1b9cbc4`, since history is not rewritten.

## Limits

- Containers share the host kernel, and no attempt tests a kernel exploit. gVisor was not evaluated.
- The backend user is root-equivalent through Docker.
- Rate limiting counts connections, not requests.
- One VM, with no redundancy.
- `NO_DEMONSTRATED_ADVANTAGE` stands. Nothing here changes it.

## Readiness for Sprint 9

Not ready: there is no URL yet. Remaining dependencies, in order: owner approvals, deployment, hosted evidence,
one live run, then a public repository, demo video and slides. The event page gives a deadline of
2026-11-08 22:00 UTC. The exact submission form sits behind sign-in and has not been checked.
