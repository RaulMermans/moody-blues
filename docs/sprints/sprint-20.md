# Sprint 20: v0.1.0 developer alpha

- **Branch:** `sprint/20-developer-alpha-release`, from `origin/main` at `53463b1` (PR #26). Pushed to `origin` at the owner's request. No pull request, and not merged, tagged, published or deployed.
- **Worked in:** `~/dev/Moody-Blues`, as the brief says.
- **Release candidate:** `c539f098b79f5e7f01d5d9005b7874b017ebda62`. This record is a docs-only commit on top of it.
- **Decision: `RELEASE CANDIDATE — BLOCKED`.** Technically validated. A license, credential confirmation, an independent developer and owner approval are outstanding.

## Decisions

**Release architecture.** No new subsystem. The release packages what exists: thin scripts over the existing commands, one read-only verifier over the existing journals, and documentation. Scope stayed frozen. The two additions that are code each answer an acceptance criterion: `evidence-verify` (section 11) and `revision` in `/health` (section 17).

**Positioning.** Controlled fault testing, independent verification, reproducible evidence and external-agent integration lead. The Investigator is "experimental AI-assisted investigation" on every surface, with its results still published. Sprint records and `docs/submission/` were left as written.

**One local dataset.** `make dev`, `make quickstart` and free `make external-*` runs share the disposable `.moody-local`, so a demonstration appears in the UI. A ledger follows its artifacts directory, so live runs are forced off there: an empty ledger must not become a fresh budget.

**SDK 0.1.1.** Resolves KI-78. Still `mb-agent/1`, and 0.1.0 agents are still accepted.

## Starting state

| Check | Result |
|---|---|
| Branch and HEAD | `53463b1` confirmed on `origin/main`, working tree clean |
| Repository | Public. `licenseInfo: null` |
| CI on `main` | Passing at `53463b1` |
| Production revision | `6405817` (Sprint 13), read from the release symlink over SSH on 2026-11-07, before and after this work. The site's status cannot show it: `/api/status` gives only `0.1.0` |
| Ledger | 814 entries, $6.500182 settled, no open reservations. Unchanged |
| Hackathon submission | **Unconfirmed.** Cannot be seen from here |
| Vultr key rotation | **Unconfirmed.** Keys were not read, used or rotated |
| AMD EVO X3 | No configured access from this machine. Not probed |

## Sprint 19 audit, reconciled

| # | Finding | State now |
|---|---|---|
| 1 | P0 License | **OPEN, owner.** [Review and steps](../release/license-decision.md) prepared. Nothing applied |
| 2 | P0 Credentials | **OPEN, owner.** [Verification procedure](../release/publication-plan.md#credential-verification) written |
| 3 | P0 Product claims | **DONE** in the repository. The public site and GitHub description change only with approval |
| 4 | P2 Secret scan | **DONE.** Clean on the release commit. Allowlist unchanged: 6 reviewed entries |
| 5 | P1 Flaky Docker test | **NARROWED, not fixed.** See below and KI-80 |
| 6 | P1 Public demo | **OPEN, owner.** [Options A and B](../release/publication-plan.md#public-demo-two-options) prepared. A is recommended until judging ends |
| 7 | P1 Installation | **DONE** on macOS arm64 and Ubuntu arm64. amd64 clean install `NOT_RUN` |
| 8 | P1 Sandbox trust statement | **DONE.** In the README, agent guide, [trust model](../security/trust-model.md) and `SECURITY.md` |
| 9 | P1 SDK | **DONE**: 0.1.1, reference, compatibility matrix. Publishing to an index is deferred, by decision |
| 10 | P1 World registration | **DONE.** Labeled alpha everywhere it is described |
| 11 | P2 Artifacts | **DONE.** `make dev` default fixed, and KI-84 found and fixed |
| 12 | P2 Documentation | **DONE.** Current guidance and history separated in [docs/README.md](../README.md). Files were not moved, so old links hold |
| 13 | P2 Investigator repair at prompt level | **NOT DONE,** deliberately. Scope freeze: it improves an experimental feature and blocks no criterion |

## Defects found by actually running it

| Issue | How it was found |
|---|---|
| KI-82: `make doctor` passed where no agent could start | Reading it against the sandbox path |
| `--fault` silently ignored without `--local-inference` | Reading `external-run` |
| KI-81: `evidence-verify` crashed on evidence that no longer parsed | Running the tamper step the quickstart recommends |
| KI-83: stopping `make dev` segfaulted bash, leaving a 24 MB `core` file. Predates this sprint | One untracked file after the clean Linux run |
| KI-84: `make investigator-preflight` overwrote a file in `.artifacts` | Hashing canonical state around the matrix |
| `make setup` needed a large browser download nobody needs for a first test | Walking the install |
| A clean `doctor` printed `BLOCKED_BY_CREDENTIALS` for a key a newcomer does not need | Reading a clean-install log |

## The flaky test

`test_evidence_names_the_real_environment` failed once in the CI history: 1 of 14 failed runs examined. **The root cause is not known.** The evidence narrows it: that run has `environment=None` and logged no adapter events, so `open_session` raised `SandboxError` before the driver started, and the next run in the same investigation was normal. The message was stored in the run's `error`, which the test did not show, and is gone.

It did not reproduce in 40 investigations idle or 48 under six-way contention (about 176 runs), nor in 25 repeats of the test on the candidate. No sleep, retry or weakening was added. What changed is that the next occurrence names its cause: `_drive` logs `sandbox_session_failed`, and the assertion prints `run.error`.

## Clean-machine results

Separate from human acceptance. Run by the coding agent, so these prove the commands work, not that a person can follow them.

| Step | macOS 26, arm64, Colima | Ubuntu 24.04, arm64, fresh DinD daemon |
|---|---|---|
| Candidate tested | `e0c71cb` | `f39f865`, then the `ede021f` Makefile fix for shutdown |
| Prerequisite detection | PASS | PASS, including a clear failure with no daemon |
| `make setup` | PASS, 5 s (warm caches) | PASS, 18 to 33 s |
| `make sandbox-image` | PASS, already present | **PASS, real pull by digest**, and idempotent |
| `make doctor` | PASS | PASS, and correctly `FAIL` before the image |
| `make quickstart` | PASS, 19 s | PASS, 11 to 13 s |
| Both worlds | PASS | PASS |
| `make evidence-verify` | PASS | PASS: 4 investigations, 8 runs |
| UI start | PASS, in a real browser, signed in with the printed token | PASS over HTTP: home 200, 5 public and 9 operator investigations |
| Cleanup | PASS | PASS, after KI-83: `SIGINT` and `SIGTERM` leave no process or core |

`NOT_RUN`: Ubuntu amd64 clean install (CI will cover it once pushed), macOS Intel, Docker Desktop, OrbStack, a physical Linux machine, AMD EVO X3. The macOS run shared this machine's caches and image.

## Test results

Full matrix on `ede021f`. After KI-84, the backend half was rerun on `12e14de` (including Docker and quickstart); then lint, types and `tests/investigator` on `c539f09`, whose only later change is one test file. **Browser suites were not rerun after `ede021f`:** nothing since touches the frontend.

| Suite | Result |
|---|---|
| Offline: unit, world, agent, experiment, Investigator, evaluation, Explorer, external, SDK | **1339 passed** |
| Real Docker: integration and containment | **118 passed**, 0 skipped |
| Flaky test, repeated | 25 of 25 |
| `make test-e2e` | 37 passed |
| `make test-design`: rules, truth, navigation, axe, WebKit | 217 passed |
| `make external-ui`, real containers | 8 passed |
| `make worlds-ui`, real containers | 25 passed |
| **Total** | **1744 test executions, 0 failures, 0 skips** |
| Ruff, ESLint, Pyright strict, TypeScript, frontend build | PASS |
| `external-eval`, `worlds-demo` (9 of 9), `external-investigator-eval`, `experiment-demo`, `investigator-demo`, `docker-smoke`, `investigator-preflight` | PASS |
| `make deploy-lint` | PASS |
| `make test-hosted`, `make local-ui`, `make local-eval` | `NOT_RUN`: nothing was deployed, and no local model is installed |
| GitHub Actions on this branch | `NOT_RUN` when this was written: see the run on GitHub |

## Evidence verification

| Target | Result |
|---|---|
| Canonical `.artifacts`, read-only: 31 investigations, 104 runs, schemas 1 to 3 | All 7 checks PASS. Tree byte-identical before and after |
| `make recorded-verify`, `eval-verify`, `bench-verify`, `ledger-verify` | PASS |
| Tampering | Edited evidence, edited reports, unparseable evidence, flipped verdicts, invented violations, miscounted faults, a script claiming model calls, mismatched worlds and changed bundles are each caught, in `tests/explorer/test_evidence_integrity.py` |

Hashes of `.artifacts` and of all committed evidence were identical across the final rerun. The ledger is unchanged.

## SDK and external agents

Builds to a wheel and sdist, and installs into an empty venv with no dependencies: 0.1.1, `mb-agent/1`. Examples import only the SDK and standard library. A new agent written only from the published guide passed preflight and behaved exactly as the guide says, through the real sandbox. Agents were scripted or fixture-driven: **no real model ran in this sprint.**

## Docker containment

All containment suites passed on real Docker, on Colima: `tests/security` and `tests/integration` are within the 118, and `leftover containers` was 0. Hosted containment of the long-lived session stays `NOT_RUN`. `make containment-report` was not run directly, because it replaces a committed report; the suite runs it to a temporary path.

## Security and secrets

Gitleaks over the full history, with CI's image and command, on the release commit: no leaks. A scan of the tree outside git reports only the 5 reviewed entries in `docs/`, and none elsewhere. No secret-bearing file is tracked, and each `MOODY_VULTR_API_KEY=` match in the tree is a placeholder, a test value or a shell expansion.

## Frontend and accessibility

Refined only: landing copy, an experimental note on the Investigator, a note that agents connect through the SDK and CLI, and the benchmark note. No redesign. axe, keyboard, reduced-motion and responsive checks are in `make test-design` and pass. Job Queue pages are covered by `make worlds-ui`. All deep links are tested there too.

**Human screen-reader testing: `NOT_RUN`.** Automated accessibility checks are not a substitute.

## Independent developer acceptance

`INDEPENDENT_DEVELOPER_ACCEPTANCE = NOT_RUN`. No participant was available. The coding agent does not count, and no LLM simulation was used. [Protocol](../testing/independent-acceptance.md).

## Versions

Product 0.1.0 · SDK 0.1.1 · `mb-agent/1` · `mb-world/1` (alpha) · evidence schemas 1, 2, 3 · Python 3.12+ · Node 20.9+ · pnpm 10. See [compatibility](../compatibility.md).

| Artifact at `c539f09` | SHA-256 |
|---|---|
| `git archive` source tarball, local | `439d709d822a322b9fcecc3cdc2e43a01d20592abf36a58a2f17f9c48c11258a` |
| `moody_blues_sdk-0.1.1-py3-none-any.whl` | `16e3af8d920c93530e9951b4de007bca55dfb1f0524de4ff7eda91596ddc2a1d` |
| `moody_blues_sdk-0.1.1.tar.gz` | `4767bd614f164646205c2c26e149e0c5bebaef55bb9de0f5194e0405d04b2cd0` |

The archive's hash will change with this record's commit and any license commit. Regenerate it from the tag.

## Acceptance gates

| Gate | State | Note |
|---|---|---|
| C20-A Product positioning | **PASS** | In the repository. GitHub description and hosted site await approval |
| C20-B Reproducible installation | **PASS** | macOS arm64 and Ubuntu arm64. amd64 `NOT_RUN` |
| C20-C First successful investigation | **PASS** | Real Oracle `PASS` and `VIOLATION`, technically. Not yet shown with a new developer |
| C20-D External-agent usability | **PASS** | Scripted agents, including one written from the guide. No real model this sprint |
| C20-E Evidence trustworthiness | **PASS** | |
| C20-F Security | **PASS** | Documented and tested locally. Hosted session containment `NOT_RUN` and stated |
| C20-G Regression and CI | **PASS** locally | GitHub CI `NOT_RUN`. KI-80's cause is still unknown |
| C20-H Product experience | **PASS** | Automated. Human screen reader `NOT_RUN`. Public site unchanged |
| C20-I Independent acceptance | **NOT_RUN** | |
| C20-J Open-source readiness | **BLOCKED** | License decision |
| C20-K Release provenance | **PASS** | Nothing tagged |
| C20-L Operational safety | **PASS** | See below |
| C20-M Owner release approval | **BLOCKED** | Not given |

**Operational safety.** No merge, tag, publish, deployment, spend, or change to any external account. The branch was pushed only after the sprint, at the owner's request. Production was read only: public status pages, and one read of the release symlink over SSH, twice. Unrelated local containers were not touched. To be plain about the one slip: running `make investigator-preflight` in the matrix overwrote the local, non-evidence file `.artifacts/investigations/preflight.json` before KI-84 was fixed. Nothing read it.

## Go/no-go

**`RELEASE CANDIDATE — BLOCKED`.** Do not tag or publish. In order:

1. **Confirm the hackathon submission** before 2026-11-08 22:00 UTC. It does not depend on this sprint.
2. Choose a license.
3. Confirm the Vultr keys were rotated.
4. Run the independent developer test, and fix what it finds.
5. Approve the push, merge, tag and release.
6. After judging, choose demo option A or B. Destroy the VM from `~/dev/Moody-Blues` when done.

## Risks and backlog

- **The biggest risk is what no human has tried.** Every setup claim here was proven by the agent that wrote the docs.
- KI-80 may recur. If it does, the log now names the reason.
- Pushing runs `make quickstart` in CI for the first time, on amd64.
- `.artifacts/investigations/preflight.json` is now stale, and is the owner's to remove.

After v0.1.0: amd64 and physical Linux installs, publishing the SDK, signed evidence, hosted session containment, gVisor or Kata evaluation, a third unlike world before calling `mb-world/1` stable, prompt-level repair for small models (audit item 13).
