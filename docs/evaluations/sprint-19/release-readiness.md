# Release readiness for v0.1.0, developer alpha

Audited on `sprint/19-reliability-benchmark`, 2026-11-06. Priority: **P0** blocks release, **P1** should land in it, **P2** can follow.

## Blockers

| # | Priority | Area | Finding | What it needs | Owner |
|---|---|---|---|---|---|
| 1 | **P0** | License | None. GitHub reports `licenseInfo: null` on a public repository, so nobody may legally use the code | Choose a license and add `LICENSE`, also to `sdk/python` | **Owner decision** |
| 2 | **P0** | Credentials | Rotation of the Vultr key is unconfirmed since Sprint 9 | Rotate and confirm | **Owner action** |
| 3 | **P0** | Product claims | README, landing page and submission lead with the Investigator as the core story. Sprint 19 does not support that as a primary capability | Reposition around deterministic testing and verification, with the Investigator labeled experimental | Sprint 20 |
| 4 | **P0** | Secret scan | Gitleaks was not run locally: not installed, and its image is not pulled. CI runs it on `main` | Confirm the latest CI gitleaks result, and run it over the full history before release | Sprint 20 |
| 5 | P1 | CI reliability | The last PR run failed on `test_evidence_names_the_real_environment`, then `main` passed. That is a flaky Docker test, undiagnosed | Reproduce and fix; do not rerun until green | Sprint 20 |
| 6 | P1 | Public demo | The hosted site runs an older deployment, without Job Queue World, external agents or Sprint 19 | Decide: redeploy or say what version it shows. Destroy the VM after judging | **Owner decision** |
| 7 | P1 | Installation | `make setup` needs uv, pnpm and Docker, and a digest-pinned sandbox image pulled by a long one-liner. Not tested on a clean machine, and only macOS with Colima and the GitHub runner have run it | One `make` target for the image, and a clean-machine test on Linux and macOS | Sprint 20 |
| 8 | P1 | Sandbox security | Containers share the kernel, with no gVisor or Kata. Hosted containment is untested, and external agents have not run on the VM. The docs say so, but a developer running untrusted agents must see it first | A clear statement of the trust model in the quickstart | Sprint 20 |
| 9 | P1 | SDK | `moody-blues-sdk` is not published, so it is installed from a checkout, and `sdk_version` does not distinguish before and after `record_id` (KI-78) | Bump the version, and decide on publishing | Sprint 20 |
| 10 | P1 | World registration | Adding a world means editing the source, by design, and only two similar worlds exist. "Pluggable" should not be claimed as a stable contract | Say "contract may change", or add a third unlike world first | Sprint 20 |
| 11 | P2 | Artifacts | Fixed for free commands (KI-79). `make dev` still reads `.artifacts` by default, so a rehearsal needs the directory set to appear on the pages | Keep the quickstart step, and consider a `make` default | Sprint 20 |
| 12 | P2 | Documentation | Sprint-era files and hackathon copy are mixed with developer docs, and `README` is a submission first | Separate them | Sprint 20 |
| 13 | P2 | Investigator | Selection needs repair at the prompt level for small models: most rejections are one field | Only if the Investigator stays in the alpha | Sprint 20 |

## Claims

| Claim | Supported? | Evidence |
|---|---|---|
| The Oracle verifies state independently of agent claims | **Yes** | Tamper tests; 0 disagreements |
| Faults are injected deterministically and delivery is recorded | **Yes** | 575 experiments with validity recorded |
| Verified failures reproduce on deterministic targets | **Yes**, for scripts | 28 of 28 |
| External agents run contained in local Docker | **Yes**, locally | `make external-containment`; hosted is `NOT_RUN` |
| Two worlds share one runtime | **Yes** | Golden file, both worlds benchmarked |
| A real local model can drive a queue agent | **Yes**, as integration | 7 runs |
| Autonomous investigation finds more than simpler testing | **No** | `INCONCLUSIVE` here; `NO_DEMONSTRATED_ADVANTAGE` in Sprint 6; fewer found per investigation here |
| The Investigator's conclusions can be relied on | **No**, for this model | 25 of 40 contradicted the verified findings. Rely on the Oracle |
| Works with any agent framework | **Not shown** | Python, through the SDK |

## Owner actions, independent of this sprint

1. **Confirm the lablab submission.** Deadline 2026-11-08 22:00 UTC. It cannot be seen from here, and nothing in this sprint should delay it.
2. Rotate the Vultr key. 3. Choose a license. 4. Destroy the VM after judging, from `~/dev/Moody-Blues`, which holds its state.
