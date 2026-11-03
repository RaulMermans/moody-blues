# MOODY BLUES

**The Reality Distortion Lab for AI Agents.** MOODY BLUES is an autonomous adversarial
experimentation system. It changes the conditions inside isolated synthetic environments,
observes how a target agent behaves, and compares what the agent *reports* with what
*actually* happened.

Built for the Vultr Agent Rush Hackathon, *Blast Radius Zero* (Nov 3–8, 2026).

> **Status: Sprint 1, foundation.** Built so far: the backend, the sandbox, the Vultr
> adapter and a status page. Not built yet: the Investigator, the synthetic world engine and
> the truth oracle. See [docs/sprints/sprint-01.md](docs/sprints/sprint-01.md).

## What works today

| Capability | State |
|---|---|
| FastAPI backend: `/health`, `/ready`, `/sandbox/smoke` | Implemented and tested |
| Docker sandbox: no network, non-root, read-only, resource-limited, auto-cleanup | Implemented and verified against a real daemon |
| Vultr Serverless Inference adapter (OpenAI SDK) | Implemented and tested offline. **Live verification pending credentials.** |
| Next.js status page connected to the backend | Implemented and verified with Playwright |

## Prerequisites

Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20.9+, pnpm 10, and a Docker daemon
(Docker Desktop, Colima or OrbStack). `make doctor` checks all of these.

## Quick start

```bash
make setup            # uv sync, pnpm install, Playwright Chromium
cp .env.example .env  # optional; defaults work offline
make doctor           # verify prerequisites (no chargeable calls)
make dev              # backend :8000 + frontend :3000
```

Open http://localhost:3000.

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install Python and Node deps from lockfiles, plus the Playwright browser |
| `make dev` | Run the backend (:8000, reload) and frontend (:3000) together |
| `make dev-backend` / `make dev-frontend` | Run one side only |
| `make lint` | `ruff format --check`, `ruff check`, ESLint |
| `make format` | Auto-format and auto-fix Python |
| `make typecheck` | Pyright (strict) and `tsc` |
| `make test` | Unit tests (offline: no Docker, no network) |
| `make test-integration` | Real-Docker sandbox integration and containment tests |
| `make build` | Production frontend build |
| `make test-e2e` | Build, then Playwright against the real backend and frontend |
| `make check` | All of the above. The local acceptance gate. |
| `make doctor` | Check the toolchain, Docker, Playwright and config. Makes no chargeable calls. |
| `make docker-smoke` | Run the fixed smoke program in a real disposable container |
| `make vultr-models` | **Live:** list models visible to your key |
| `make vultr-smoke` | **Live, chargeable:** basic inference plus tool calling |
| `make sandbox-clean` | Remove any leftover sandbox containers |
| `make clean` | Remove caches and build output |

Live smoke output is written to `.artifacts/` (git-ignored). Without a key, the live commands
exit `2` with `BLOCKED_BY_CREDENTIALS`.

## Configuration

All settings come from `MOODY_*` environment variables or `.env`. See
[.env.example](.env.example). The Vultr key stays on the server; the browser never sees it.

## Documentation

- [Architecture overview](docs/architecture/overview.md) · [ADR 0001](docs/adr/0001-architecture.md)
- [Sprint 1 record](docs/sprints/sprint-01.md) · [Validation](docs/testing/validation.md)
- [Known issues](docs/troubleshooting/known-issues.md) · [Vultr preflight](docs/deployment/vultr-preflight.md)
- Contributor rules: [AGENTS.md](AGENTS.md)

## License

**Pending.** No license has been chosen yet. Until one is, all rights are reserved by the
authors.
