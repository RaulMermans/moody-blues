# Sprint 1: Foundation, infrastructure and first vertical slice

- **Dates:** 2026-11-03
- **Branch:** `sprint/01-foundation`
- **Outcome:** `LOCALLY_ACCEPTED_WITH_EXTERNAL_BLOCKERS`

## Goal

Go from an empty directory to a tested local foundation: backend, sandbox, Vultr adapter,
frontend and CI. Make every external dependency's verification status explicit.

## Delivered

- **Repository:** git (`main` plus a sprint branch), uv and pnpm lockfiles, Makefile,
  `.env.example`, `AGENTS.md` (canonical rules), `CLAUDE.md` (pointer), and docs.
- **Backend:** FastAPI app factory; pydantic-settings config; JSON logging with request ids;
  error envelopes; `/health` (configuration state), `/ready` (live Docker ping) and
  `/sandbox/smoke` (fixed program only). Contracts cover experiments, sandbox, inference,
  status and error categories.
- **Inference:** `VultrInferenceClient` (OpenAI SDK) with timeouts, bounded retries, error
  classification, usage and model metadata; live smoke commands; offline contract tests.
- **Sandbox:** `SandboxRunner` protocol and `DockerSandboxRunner` (details in
  [overview](../architecture/overview.md#sandbox-sandbox)), verified against a
  real daemon.
- **Frontend:** Next.js 16 status page, server-side `/api/status` proxy, and Playwright E2E
  against real services.
- **CI:** `ci.yml` (Python, frontend, real-Docker sandbox, Playwright) and `vultr-live.yml`
  (manual only).
- **CLI:** `moody-blues doctor | docker-smoke | vultr-smoke | vultr-models`.

## Acceptance gates

| Gate | Requirement | Status | Evidence |
|---|---|---|---|
| S1-A | Reproducible repository foundation | PASS | lockfiles, `make setup`, `make doctor` |
| S1-B | FastAPI backend functioning locally | PASS | 60 unit tests; `make dev` served `/health` and `/ready` |
| S1-C | Vultr adapter implemented and tested; live status explicit | PASS (offline) / BLOCKED_BY_CREDENTIALS (live) | 25 adapter contract tests (fixtures); `vultr-smoke` exits 2 |
| S1-D | Actual local sandbox execution verified | PASS | 16 real-Docker tests, `docker-smoke` |
| S1-E | Next.js frontend connected to FastAPI | PASS | `/api/status` via `make dev`; E2E |
| S1-F | Playwright local E2E passing | PASS | 4/4 |
| S1-G | Lint, type checks, tests and build passing | PASS | `make check` exit 0 |
| S1-H | Documentation and troubleshooting updated | PASS | `docs/` |

GitHub Actions: NOT_RUN (no remote configured; pushing needs approval).

## Defects found and fixed

1. 500 responses lacked `X-Request-ID` (KI-4). Fixed in middleware; regression test added.
2. Lint violation `react-hooks/set-state-in-effect` in the status panel (KI-7). Refactored.
3. A flawed E2E assertion matched the *name* `MOODY_VULTR_API_KEY` in a help string. It was
   replaced with a stronger check: a canary key value and the internal backend URL must not
   appear in any browser-visible response.

## Not done (by design)

The Investigator, CRM world engine, Phantom Success/Failure, truth oracle, replay and
evaluation, authentication, Vultr deployment and REEPROV integration.

## Prerequisites for Sprint 2 (World Engine)

- Optional for the World Engine itself, but needed for the Investigator: Vultr credentials,
  followed by `make vultr-models` and `make vultr-smoke`.
- Decide where world state lives (in-memory vs SQLite) and how the truth oracle reads it
  independently of the agent.
- Add a job model for long-running sandbox/experiment runs (the current runs are synchronous).
- Push the branch and confirm the CI workflows run green.
