# Validation strategy and results

## Test layers

| Layer | Location | Needs | Proves | Uses fakes? |
|---|---|---|---|---|
| Unit | `tests/unit` | nothing | contracts, config, API envelopes, request ids, health semantics, adapter wire contract, error classification, bounded retries, Docker-unavailable path | Yes, labeled: `FakeSandboxRunner` for API tests; `httpx2.MockTransport` **fixtures** for the Vultr wire format. The Docker-unavailable tests use the **real** runner against a nonexistent socket. |
| Integration | `tests/integration` (`-m docker`) | Docker | real execution: success, Python error, exit code, timeout + kill, memory/PID/CPU limits, output truncation, cleanup after every test, `/sandbox/smoke` + `/ready` against real Docker | No |
| Security | `tests/security` (`-m docker`) | Docker | inside the container: uid 65534, zero capabilities, NoNewPrivs, loopback-only network, read-only rootfs, noexec `/tmp`, no host-env leakage (canary), no Docker socket or host mounts | No |
| E2E | `frontend/e2e` | Docker, uv, Chromium | real browser → Next.js production server → FastAPI: identity renders, UI states equal backend-reported states, no key material or backend URL reaches the browser (canary key), genuine backend-down state | No (no request mocking) |
| Live provider | `make vultr-smoke`, `make vultr-models` | Vultr key | real inference + tool calling, Pydantic-validated arguments, requested/reported model | No |

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

## Selected evidence

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
