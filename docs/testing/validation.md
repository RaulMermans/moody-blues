# Validation strategy and results

## Test layers

| Layer | Location | Needs | Proves | Uses fakes? |
|---|---|---|---|---|
| Unit | `tests/unit` | nothing | contracts, config, API envelopes, request ids, health semantics, adapter wire contract, error classification, bounded retries, Docker-unavailable path | Yes, labeled: `FakeSandboxRunner` for API tests; `httpx2.MockTransport` **fixtures** for the Vultr wire format. The Docker-unavailable tests use the **real** runner against a nonexistent socket. |
| Integration | `tests/integration` (`-m docker`) | Docker | real execution: success, Python error, exit code, timeout + kill, memory/PID/CPU limits, output truncation, cleanup after every test, `/sandbox/smoke` + `/ready` against real Docker | No |
| Security | `tests/security` (`-m docker`) | Docker | inside the container: uid 65534, zero capabilities, NoNewPrivs, loopback-only network, read-only rootfs, noexec `/tmp`, no host-env leakage (canary), no Docker socket or host mounts | No |
| Target Agent | `tests/agent` | nothing (real SQLite worlds) | agent loop, tool validation, budgets, termination, cancellation, claim parsing, policy selection, prompt isolation, Oracle integration and assessment, eval harness, live-command preflight, exactly-once execution through the real adapter under SDK retries | Yes, labeled **provider fixtures** (`ScriptedModel`, `provider="fixture"`; HTTP fixtures via `MockTransport`). Never evidence of model behavior. |
| World Engine | `tests/world` | nothing (real SQLite files in temp dirs) | CRM validation and transactions, pre-commit rollback, CHECK constraints, append-only evidence, `mode=ro` Oracle access, fault semantics and targeting, Oracle verdicts, tamper resistance, isolation, reset, deterministic replay, CLI | No. Executors are deterministic **scripts** (`world/reference.py`), labeled as not LLM agents. |
| E2E | `frontend/e2e` | Docker, uv, Chromium | real browser → Next.js production server → FastAPI: identity renders, UI states equal backend-reported states, no key material or backend URL reaches the browser (canary key), genuine backend-down state | No (no request mocking) |
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
