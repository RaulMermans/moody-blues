# Sprint 18: Pluggable Truth Oracle and multi-world reliability testing

- **Branch:** `sprint/18-pluggable-truth-oracle`, from `origin/main` at `e44393a` (PR #24). Committed locally: not pushed, merged
  or deployed.
- **Worked in:** `~/dev/Moody-Blues`, as the brief says.
- **Outcome:** two genuinely different synthetic environments now run through one coordinator, gateway pipeline, fault boundary,
  Oracle path and evidence format, with independent world-specific verification. The CRM is unchanged, by measurement.
- **Not shown:** anything about a real model in the second world. Every agent here is a script or a labeled fixture.

Decision: [ADR 0015](../adr/0015-world-plugins.md). Contract: [world plugins](../architecture/world-plugins.md). Guide:
[Job Queue World](../external-agents/job-queue-example.md). Results: [evaluation](../evaluations/sprint-18/README.md).

## Preflight, 2026-11-06

| Item | Finding |
|---|---|
| Local | `~/dev/Moody-Blues` clean, on `sprint/17-local-llm-validation`. The Desktop copy was left alone |
| GitHub `main` | `e44393a`, PR #24, as the brief says |
| Hackathon submission | **UNKNOWN, critical owner action.** Cannot be seen from here. Deadline 2026-11-08 22:00 UTC. Nothing here depends on Sprint 18 |
| Production | **Up, unchanged.** Read-only `/api/status`: ready, inference `not_configured`. No revision endpoint |
| License | **None.** GitHub returns 404 on a public repository. Owner decision |
| Vultr keys | Rotation **not confirmed**. No values were read |
| Ledger | `.artifacts/live-spend/ledger.jsonl`, 814 entries, verifies, unchanged |
| Docker | Colima, 4 CPUs, 8 GB, three unrelated containers running throughout and never touched. 21 GiB free |
| Ollama | Installed, not running, **no models** |

## Gates

| Gate | Status | Evidence |
|---|---|---|
| C18-A Pluggable World Architecture | **PASS** | `mb-world/1`, explicit registry; unknown world, contract and version refused |
| C18-B CRM Compatibility | **PASS** | Golden file from the code before the refactor: 10 fingerprints, 14 scenario hashes, tools, policies, prompts identical. Recorded bundles rebuild byte for byte. Every raw historical experiment verifies, and `eval-verify` passes |
| C18-C Job Queue World | **PASS** | Own SQLite schema, tools, worker and transitions; 8 scenarios |
| C18-D Independent Oracle | **PASS** | Both through `verify_world`, each with its own deterministic verifier |
| C18-E Fault Injection | **PASS** | All three existing kinds, no new ones; effect and observation shown apart in the queue |
| C18-F Experiment Validity | **PASS** | `not_exercised` runs are no evidence either way. Real Sprint 17 errors reproduced. Checked with real text and scripted runs, not a live model |
| C18-G External-Agent Compatibility | **PASS** | Queue agents through the existing SDK in real Docker. `mb-agent/1` unchanged for existing agents |
| C18-H Evidence Integrity | **PASS** | Provenance complete, verification and tampering in both worlds, history unwritten |
| C18-I Product Experience | **PASS** | 16 Playwright tests on real-container evidence. No CRM word on any view of a queue run |
| C18-J Regression and Security | **PASS** | Below |
| C18-K Release Safety | **PASS** | No push, merge, deploy, paid inference, spending change or production change. See the correction below |

## Regression, final code

| Check | Result |
|---|---|
| Ruff, Pyright strict, ESLint, TypeScript | PASS, 0 errors |
| Offline Python (unit, world, agent, experiment, investigator, evaluation, explorer, external) | 1277 passed. Baseline 1149 |
| Real Docker integration and security | 115 passed |
| Sandbox containers left behind | 0 |
| `recorded-verify`, `eval-verify`, `ledger-verify` | PASS |
| Frontend build | PASS |
| Playwright: design 217, e2e 37, external 8, worlds 16 | 278 passed |
| `make local-ui`, hosted e2e, `make local-eval` | **NOT_RUN** |
| `make evidence-audit` | **NOT_RUN**, on purpose: it can overwrite snapshots |

## Results

| Case | Oracle |
|---|---|
| Correct scheduling | PASS, 1 job |
| Misleading error, safe verification | PASS, 1 job |
| Misleading error, unsafe retry | VIOLATION, 2 jobs |
| Misleading success, false claim | VIOLATION, 0 jobs |

All four ran in real containers, as did the CRM equivalents. A repeat within the task's own limit is a PASS, and an honest
`not_completed` is INCONCLUSIVE.

## What testing found

- **A recorded export would have been refused** (KI-75), caught by the byte-for-byte test.
- **Hard-coded "1 required"** (KI-76), found by reading a screenshot after every test had passed. Three places assumed the CRM's
  objective. The copy and the label are fixed, with a regression test on the label.
- **`customer_id: null` in raw evidence** on a queue run, caught by widening the no-CRM-words test to every view.
- **`WORLD_TIERS`** would have invalidated registered manifests if extended. Caught reading `evaluation/manifest.py`.

## Correction: one command wrote to canonical artifacts

While checking the CLI I ran `external-run` once without `MOODY_ARTIFACTS_DIR`, so it wrote one investigation, two experiments and
one job record into `.artifacts/`. The brief forbids that. Nothing existing was overwritten and the ledger did not move, which a
listing of everything changed under `.artifacts` confirmed. Those four new directories were moved out by id, and the check was
repeated in a disposable directory. Every later run used one.

## Limitations

- **No real model has run in Job Queue World**, and no real model has run with the validity checks. Fixture Investigator only.
- **Two synthetic worlds are not general compatibility.** Both are single-write, record-shaped tasks. A world with multi-step
  workflows or no natural record may need more from the contract.
- The internal Target Agent is CRM-only. `world-run` and `world-demo` are too. Operator missions name no queue world, so Job Queue runs
  from the command line only, and it is not deployed.
- Crash recovery in the queue is tested with a target that dies and a truncated journal. The real SIGKILL test remains CRM-only.
- New panels are tested at desktop width on real evidence. The accessibility and phone-width suites run against recorded CRM bundles.
- KI-77, KI-78, and the CRM-era metric names in queue run reports (ADR 0015).

## Sprint 19 prerequisites

1. Owner: confirm the submission, rotate the Vultr key, choose a license. None of these can be done from here.
2. Owner decision: install a local model for one bounded Job Queue investigation, comparing it with the scripted baseline.
3. A real SIGKILL recovery test in the queue, and phone-width and axe coverage of the world panels.
4. A third world unlike these two, multi-step, before calling the contract stable.
5. A controlled benchmark before any claim about adaptive advantage. A new registered manifest must settle KI-77 first.
