# Validation strategy and results

## Test layers

| Layer | Location | Needs | Proves | Uses fakes? |
|---|---|---|---|---|
| Unit | `tests/unit` | nothing | contracts, config, API envelopes, request ids, health semantics, adapter wire contract, error classification, bounded retries, Docker-unavailable path | Yes, labeled: `FakeSandboxRunner` for API tests; `httpx2.MockTransport` **fixtures** for the Vultr wire format. The Docker-unavailable tests use the **real** runner against a nonexistent socket. |
| Experiment runtime | `tests/experiment` | nothing (real SQLite worlds) | protocol parsing and authorization (including Hypothesis), coordinator state machine, classification, budgets, evidence tampering, crash recovery | Yes, labeled: `ScriptedSandbox` test double; provider fixtures. Never evidence of containment or model behavior. |
| Investigator | `tests/investigator` | nothing (real SQLite worlds) | state machine, contracts, limits, bounded refinement, shared budget, corrupt ledger, Oracle authority, reproduction, injection and leak boundaries, evidence linkage, the paired test's ability to tell adaptation from noise | Yes, labeled: scripted model and sandbox. Never evidence of containment or model behavior. Hostile generated programs run on real Docker in `tests/security/test_generated_code.py`. |
| Explorer | `tests/explorer` | nothing | evidence API contracts against the real committed bundles, ordering, tampering, traversal, bounds, Oracle and run-outcome separation, export determinism, sanitizing, operator refusal, concurrency, cancellation, real SIGKILL of a running job and restart classification | Scripted model and sandbox for jobs (labeled). The recorded evidence is real. |
| External agents | `tests/external` | nothing (real processes, real SQLite worlds) | the adapter across a real process boundary: bundle, bootstrap, SDK, example agents, driver, handshake, bad lines, scopes, quotas, cancellation, crashes, forged results, the Oracle, evidence, recovery, the real API | Yes, labeled: `LocalProcessRunner` stands in for the sandbox and contains nothing; `ScriptedModel` for the model path. **Never evidence of containment or model behavior.** Containment is in `tests/security/test_external_agent_containment.py` |
| Integration | `tests/integration` (`-m docker`) | Docker | real execution: success, Python error, exit code, timeout + kill, memory/PID/CPU limits, output truncation, cleanup after every test, `/sandbox/smoke` + `/ready` against real Docker | No |
| Security | `tests/security` (`-m docker`) | Docker | inside the container: uid 65534, zero capabilities, NoNewPrivs, loopback-only network, read-only rootfs, noexec `/tmp`, no host-env leakage (canary), no Docker socket or host mounts | No |
| Evaluation | `tests/evaluation` | nothing (real SQLite worlds) | manifests and frozen plans, eligibility, attribution, adaptation scoring, journals, reports, budget refusal, leakage, planning isolation | scripted sandbox and reference targets (labeled) |
| Target Agent | `tests/agent` | nothing (real SQLite worlds) | agent loop, tool validation, budgets, termination, cancellation, claim parsing, policy selection, prompt isolation, Oracle integration and assessment, eval harness, live-command preflight, exactly-once execution through the real adapter under SDK retries | Yes, labeled **provider fixtures** (`ScriptedModel`, `provider="fixture"`; HTTP fixtures via `MockTransport`). Never evidence of model behavior. |
| World Engine | `tests/world` | nothing (real SQLite files in temp dirs) | CRM validation and transactions, pre-commit rollback, CHECK constraints, append-only evidence, `mode=ro` Oracle access, fault semantics and targeting, Oracle verdicts, tamper resistance, isolation, reset, deterministic replay, CLI | No. Executors are deterministic **scripts** (`world/reference.py`), labeled as not LLM agents. |
| E2E | `frontend/e2e` | Docker, uv, Chromium, the pinned image | real browser → Next.js production server → FastAPI: identity, status, and the full explorer on real recorded evidence; every verdict on screen compared with the API; tampered, missing and unreachable states; unauthorized requests; a rehearsal on real Docker, worlds and Oracle; cancellation; bundle and cookie checks | No request mocking. Corrupt-record and over-limit-ledger inputs are built by `e2e/prepare.mjs`, labeled. A rehearsal is a fixture and a script by design. |
| Design | `frontend/e2e-design` | uv, Chromium, WebKit | copy and state rules on the committed bundles; every recorded run in a real browser; the investigation journey on every case; navigation, axe and overflow with disclosures open, contrast, touch targets, headings, keyboard; WebKit layout. Local only, not in CI |
| External UI | `frontend/e2e-external` | uv, Chromium; Docker with `MOODY_E2E_EXTERNAL_DOCKER=1` | external runs on the real pages, in a real browser: the agent's name, script not model, verdict, evidence, hidden from visitors. Local only, not in CI | Default seed uses the labeled double. Real containers with the flag |
| Live provider | `make vultr-smoke`, `make agent-run`, `make agent-eval` | a valid Vultr inference key | real inference, tool calling, multi-turn round trip, real agent trajectories | No. (`make vultr-models` hits an unauthenticated endpoint and verifies nothing about the key.) |

Docker-dependent pytest tests **skip** with `BLOCKED_BY_LOCAL_DEPENDENCY` when no daemon is
reachable, and **fail** when `MOODY_REQUIRE_DOCKER=1` (CI).

## Sprint 1 results (2026-11-03, macOS arm64, Colima, Docker 29.5.2)

Run with `make check` (exit 0):

| Check | Result |
|---|---|
| `ruff format --check` | PASS (40 files) |
| `ruff check` | PASS |
| `pyright` (strict) | PASS (0 errors) |
| `pytest tests/unit` | PASS (60 passed) |
| `pytest tests/integration tests/security -m docker` | PASS (16 passed, real Docker) |
| ESLint (`--max-warnings=0`) | PASS |
| `next typegen && tsc --noEmit` | PASS |
| `next build` | PASS |
| Playwright E2E (Chromium) | PASS (4 passed) |
| `make docker-smoke` | PASS (exit 0, uid 65534, cleaned_up true) |
| `make doctor` | PASS (required checks); WARN: no `.env`, Vultr key not set |
| `make vultr-models` | BLOCKED_BY_CREDENTIALS (not run) |
| `make vultr-smoke` basic inference | BLOCKED_BY_CREDENTIALS (exit 2) |
| `make vultr-smoke` tool calling | BLOCKED_BY_CREDENTIALS (exit 2) |
| GitHub Actions | NOT_RUN (no remote; YAML parses) |

## Sprint 2 results (2026-11-03, same host)

Run with `make check` (exit 0):

| Check | Result |
|---|---|
| `ruff format --check` / `ruff check` | PASS (62 files) |
| `pyright` (strict) | PASS (0 errors) |
| `pytest tests/unit tests/world` | PASS (174 passed: 60 unit + 114 world) |
| ↳ world breakdown | domain 36, faults 20, oracle 23, scenarios/reproducibility 25, Hypothesis 7, CLI 3 |
| ↳ Hypothesis | Model-based state machine (60 examples × ≤25 steps, random fault plans) plus 6 properties × 40 examples |
| `pytest tests/integration tests/security -m docker` | PASS (16 passed, real Docker) |
| ESLint, `tsc`, `next build` | PASS |
| Playwright E2E | PASS (4 passed) |
| `make world-demo` | PASS (8 reference cases; real runs; see [sprint-02.md](../sprints/sprint-02.md)) |
| Mutation check (4 injected bugs) | All detected (7, 11, 5 and 15 failing tests) |
| `make vultr-smoke` | BLOCKED_BY_CREDENTIALS (not run) |
| GitHub Actions | NOT_RUN |

## Selected evidence (Sprint 1)

```text
docker-smoke   status=succeeded exit=0 stdout="hello from sandbox: python 3.12.16 uid=65534"
               stderr="stderr channel ok" duration_ms=303 cleaned_up=true
timeout        sleep(30) with a 10s limit -> status=timed_out exit=137 duration_ms=10205 cleaned_up=true
memory         256MB alloc with a 64MB limit -> status=failed exit=137 oom_killed=true
network        interfaces inside sandbox: ['lo']
privileges     CapEff=0000000000000000 NoNewPrivs=1
leftovers      0 containers labeled io.moody-blues.sandbox after the full suite
```

## Rules

See [AGENTS.md](../../AGENTS.md#rules). In short: a skip or a block is never reported as a
pass, and fixtures never count as evidence of a live integration.

## Sprint 3 results (2026-11-03, same host)

Run with `make check` (exit 0, no skipped tests):

| Check | Result |
|---|---|
| `ruff format --check` / `ruff check` | PASS (77 files) |
| `pyright` (strict) | PASS (0 errors) |
| `pytest tests/unit tests/world tests/agent` | PASS (271 passed: 79 unit + 131 world + 61 agent) |
| `pytest tests/integration tests/security -m docker` | PASS (16 passed, real Docker) |
| ESLint, `tsc`, `next build` | PASS |
| Playwright E2E | PASS (4 passed) |
| `make world-demo` | PASS (10 reference cases; the 8 Sprint 2 verdicts are unchanged) |
| Mutation check (4 injected bugs) | All detected (6, 47, 3 and 2 failing tests) |
| `make vultr-models` | Returns 35 models, but the endpoint is unauthenticated (200 with no key or a bogus key). Not a credential check. |
| `make vultr-smoke` | FAIL: 401 `Invalid API key` for every chat completion (`glm-5.3`, `qwen3.8-27b`, `deepseek-v4.1-flash-1017`) → **BLOCKED_BY_CREDENTIALS** |
| `make agent-run` (live) | Exercised up to the provider: 401 → `BLOCKED_BY_CREDENTIALS`, attributed to infrastructure. The default `kimi-k2-instruct` is refused before any call (not in the catalog). |
| `make agent-eval` (live) | BLOCKED_BY_CREDENTIALS (not run past the preflight; it would stop at the first 401) |
| GitHub Actions | NOT_RUN |

## Sprint 4 results (2026-11-04, same host; Colima, kernel 6.8.0, Docker 29.9.0)

Run with `make check` on the finished code (exit 0, no skipped tests):

| Check | Result |
|---|---|
| `ruff format --check` / `ruff check` | PASS |
| `pyright` (strict) | PASS (0 errors) |
| `pytest tests/unit tests/world tests/agent tests/experiment` | PASS (394: 81 unit, 131 world, 61 agent, 121 experiment) |
| `pytest tests/integration tests/security -m docker` | PASS (52: 14 sandbox, 10 experiment runtime, 7 containment, 21 experiment containment) |
| ESLint, `tsc`, `next build` | PASS |
| Playwright E2E | PASS (4) |
| `make experiment-containment` | PASS (31, a subset of the 52) |
| `make experiment-demo` | PASS (7 paths; deterministic reference executors) |
| `make world-demo`, `make docker-smoke` | PASS |
| Mutation check (9 injected bugs) | All detected |
| `make vultr-smoke` on `glm-5.3` | PASS (3/3, live) |
| `make agent-run` | PASS (2 runs, live) |
| `make experiment-live` | PASS (6 runs, live; see [sprint-04.md](../sprints/sprint-04.md)) |
| `make agent-eval` | NOT_RUN (deliberately; Sprint 3 results stand) |
| GitHub Actions | NOT_RUN |

The experiment layer in `tests/experiment` uses a labeled scripted sandbox and proves logic
only. Containment evidence comes only from the real Docker tests, and model behavior only from
the live commands.

## Sprint 5 results (2026-11-04, same host)

| Check | Result |
|---|---|
| `ruff format --check` / `ruff check`, `pyright` (strict), ESLint, `tsc`, `next build` | PASS |
| `pytest` offline (`make test`) | PASS (563) |
| `pytest tests/integration tests/security -m docker` | PASS (67, including 15 generated-code tests) |
| Playwright E2E | PASS (4) |
| `make investigator-preflight` | PASS (19 checks on real Docker) |
| `make investigator-demo`, `make experiment-demo`, `make world-demo`, `make docker-smoke` | PASS |
| Mutation check (20 injected bugs) | All detected, after adding 2 tests for bugs that first survived |
| `make investigator-live`, `make investigator-eval`, `make investigator-repro` | Run live; see [results](../evaluations/sprint-05-investigator.md) |
| GitHub Actions | NOT_RUN |

`make check` last ran in full (562 offline) before the final test and CI edits. The offline suite,
lint and types were rerun afterwards.

## Sprint 6 results (2026-11-05, same host)

Run on code commit `4a648a4`, from a `git archive` export outside iCloud (KI-34). Later commits change
only documentation.

| Check | Result |
|---|---|
| Baseline before changes, at `cfe74f5` | PASS: 563 offline, 67 Docker, 4 Playwright |
| `ruff format --check` / `ruff check`, `pyright` (strict), ESLint, `tsc`, `next build` | PASS |
| `pytest` offline (`make test`) | PASS (692, including 117 evaluation tests) |
| `pytest tests/integration tests/security -m docker` | PASS (70, including 3 evaluation boundary tests) |
| Playwright E2E | PASS (4) |
| `make investigator-preflight`, `make docker-smoke` | PASS |
| Evidence hashes, Sprint 6 trials | 114 of 114 match; 5 rerun records have no stored hash |
| Journal chains | 4 of 4 verify; no unfinished trial |
| `git fsck --connectivity-only` | PASS |
| `make eval-run`, `make eval-repro` | Run live; see the [report](../evaluations/sprint-06/report.md) |
| GitHub Actions, this branch | NOT_RUN: pushing needs the owner's approval |

Sprint 5's GitHub Actions line above is superseded: PR #6 passed CI on `cfe74f5` and on its merge to
`main`, including the Docker and Playwright jobs.

## Sprint 7 results (2026-11-05, macOS arm64, Colima, Docker 29.5.2)

Run with `make check` (exit 0) from `~/dev/Moody-Blues`:

| Check | Result |
|---|---|
| `ruff format --check`, `ruff check` | PASS (163 files) |
| `pyright` (strict) | PASS (0 errors) |
| ESLint, `tsc` | PASS |
| `pytest` offline, including `tests/explorer` | PASS (793 passed, 0 skipped) |
| `pytest -m docker` | PASS (71 passed, real Docker) |
| `next build` | PASS |
| Playwright E2E, production build | PASS (28 passed) |
| `make recorded-verify` with source | PASS, byte-for-byte rebuild |
| `make eval-verify` | PASS |
| All 30 investigations and 372 experiments | Intact |
| Clean clone with no `.env` or `.artifacts` | PASS: 5 cases served, operator routes 403 |
| Live mission against the real ledger | Refused (409), ledger byte-identical |
| Real model-driven journey from the app | PASS, once: `inv_ab4479c3fe80`, $0.097352, evidence intact |
| GitHub Actions | **NOT_RUN** |

## Sprint 15 results (2026-11-06, macOS arm64, Colima, Docker 29.5.2)

`make check` exit 0: 1,000 offline, 97 real Docker, 37 browser. `frontend/e2e-design` 217, `frontend/e2e-external`
6, `make external-eval` 16 of 16, `make recorded-verify` PASS. No live provider call. Full record:
[Sprint 15](../sprints/sprint-15.md). External scripted runs are **not** evidence of model behavior.
