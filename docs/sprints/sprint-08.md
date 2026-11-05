# Sprint 8: Vultr deployment, hosted containment and production acceptance

- **Date:** 2026-11-05
- **Branch:** `sprint/08-vultr-deployment`, from `origin/main` `d4c8c30`, whose tree equals Sprint 7 HEAD
  `71eace8`. Pushed, as [PR #9](https://github.com/RaulMermans/moody-blues/pull/9).
- **Outcome:** `NOT YET ACCEPTED`. **MOODY BLUES is live on Vultr** with hosted containment evidence and a real
  browser pass. One live model run on the VM is still outstanding, pending the owner's approval of that spend.
- **Public URL:** <https://45-63-119-197.sslip.io>
- **Inference spend this sprint:** $0. No provider call was made.
- **VM:** `vc2-4c-8gb`, Frankfurt, `45.63.119.197`, $0.055/hour, running. API id `0ecc6366-233e-4d27-b843-c4dc18b228cd`;
  the metadata service reports the same VM as `113687293`.

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C8-A Repository integrity | **PASS** | `git fsck` clean, evidence verified, secret scan clean, CI green on PR #9, billing read |
| C8-B Infrastructure plan | **PASS** | [Provisioning plan](../deployment/sprint-8-provisioning-plan.md), executed as written |
| C8-C Secure hosted architecture | **PASS** | Valid Let's Encrypt certificate; 8000, 3000, 2019 and 2375 closed from outside; two service users; `Secure` cookie observed |
| C8-D Sandbox containment | **PASS** | 8 of 8 attempts blocked on the VM, 19 of 19 restrictions confirmed from inside: [report](../../evidence/containment/vultr-report.json) |
| C8-E Containment demonstration | **PASS** | [/containment](https://45-63-119-197.sslip.io/containment) shows `VULTR HOST`. [Screenshot](sprint-08-screenshots/04-containment.png) |
| C8-F Budget governance | **PASS** | Ledger migrated hash-identical; live off, no key on the VM; survived crash and reboot unchanged. Corrupt-ledger refusal tested offline, not on the VM's real ledger |
| C8-G Hosted browser validation | **BLOCKED_BY_APPROVAL** | 15 of 15 against the public URL, including a rehearsal in Vultr sandboxes. The live test has not run |
| C8-H Operational durability | **PASS** | See [Hosted failure tests](#hosted-failure-tests) |
| C8-I Release readiness | **BLOCKED_BY_APPROVAL** | Needs the live run ID and a public repository. Video and slides are Sprint 9 |

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
- **CI:** pinned to Ubuntu 24.04, plus secret scan and deployment lint. On PR #9 the Playwright suite
  passed on GitHub for the first time. The move to 24.04 exposed one test that assumed an image store (KI-44).

## Billing

Read from the Vultr account API on 2026-11-05. Credit applied: $200. Pending charges: $3.91 before the VM and
$3.97 after about 40 minutes of it. The ledger's $6.50 is therefore a real over-estimate, which is the safe
direction: its prices are ceilings. The ledger is unchanged, because it remains the conservative figure.

## Hosted containment

Report `5041f2bc...` from release `cb28311`: Ubuntu 24.04.5, x86_64, kernel 6.8.0-147, Docker 29.1.3, cgroup v2,
`systemd` driver, runc, AppArmor and seccomp. gVisor is not installed and was not evaluated.

| Attempt | Observed | Exit |
|---|---|---|
| Network, including the metadata service | `ENETUNREACH`; only `lo` | 0 |
| Protected filesystem writes | `EROFS` | 0 |
| Memory past 128 MB | OOM killed | 137 |
| 500 threads | 62 started, then refused | 0 |
| Ten-minute sleep | Killed at about 3.3 s | 137 |
| Shell through the protocol | `unauthorized_action`, no target ran | n/a |
| Environment and Docker socket | 0 of 2 secrets found; no socket | 0 |
| Forged Oracle PASS | Oracle verdict stayed VIOLATION; 0 protected files seen | n/a |

## Hosted failure tests

All on the VM, and none replayed a job.

| Test | Result |
|---|---|
| Redeploy, rollback, return | Each served, with the ledger hash unchanged |
| Cancel a running job | `cancelled`, no sandbox left |
| Deploy during a job | Refused; the job completed |
| SIGKILL before the first experiment | Back in 10 s; `interrupted_before_start` |
| SIGKILL mid-experiment | Back in 10 s; `interrupted_no_target_run_open`; next mission ran cleanly |
| Reboot | Site back in about 40 s; firewall active; ledger unchanged |

The `outcome_uncertain` path, a kill while a target run is open, was not hit on the VM: reference runs last
milliseconds. It stays covered by the local test. Resources after these tests: 667 MB of 8 GB used, load 0.19,
disk 10%, about 1 MB of evidence, 14 MB of journal, 0.26 to 0.38 s per detail page from Spain.

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

Every deploy script has since run on the VM, except `live-switch.sh` and `provision.sh destroy`.

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
6. **A killed backend could leave a sandbox forever** (KI-45). Found on the VM, fixed and confirmed there.
7. **The secret count was overstated.** An unset key counted as compared, so the first report said 0 of 3.
8. **The first health check ran during restart** and was marked failed. It now starts after a release is proven.
9. **A test assumed one image store** (KI-44), exposed by the move to Ubuntu 24.04.
10. **A commit landed broken** (`1405f2f`, a missing import) because a chained command did not stop on failure.
   Fixed forward in `1b9cbc4`, since history is not rewritten.

## Limits

- Containers share the host kernel, and no attempt tests a kernel exploit. gVisor was not evaluated.
- The backend user is root-equivalent through Docker.
- Rate limiting counts connections, not requests.
- One VM, with no redundancy.
- `NO_DEMONSTRATED_ADVANTAGE` stands. Nothing here changes it.

## Readiness for Sprint 9

Close. Remaining, in order: one live investigation on the VM (needs the owner's direct approval), commit its run
ID, make the repository public, then the demo video and slides. The event page gives a deadline of
2026-11-08 22:00 UTC. The exact submission form sits behind sign-in and has not been checked.

Destroy the VM after judging: only destruction stops billing.
