# MOODY BLUES

**The Reality Distortion Lab for AI Agents.** MOODY BLUES is an autonomous adversarial
experimentation system. It changes the conditions inside isolated synthetic environments,
observes how a target agent behaves, and compares what the agent *reports* with what
*actually* happened.

Built for the Vultr Agent Rush Hackathon, *Blast Radius Zero* (Nov 3–8, 2026).

> **Status: Sprint 7, product experience.** You can open a real investigation in a browser and compare
> what an agent claimed with what actually happened. Every result shown comes from a real execution or
> is labeled as a rehearsal. **The registered benchmark found no demonstrated adaptive advantage:** fixed
> testing found a verified failure in 2 of 3 investigations, adaptive in 1 of 3, non-adaptive generation
> in 0 of 3, on a small sample. See the [report](docs/evaluations/sprint-06/report.md) and
> [docs/sprints/sprint-07.md](docs/sprints/sprint-07.md).

![The Reality Comparison](docs/sprints/sprint-07-screenshots/04-reality-comparison.png)

## What works today

| Capability | State |
|---|---|
| FastAPI backend: `/health`, `/ready`, `/sandbox/smoke` | Implemented and tested |
| Docker sandbox: no network, non-root, read-only, resource-limited, auto-cleanup | Implemented and verified against a real daemon |
| Vultr Serverless Inference adapter (OpenAI SDK) | Implemented; **verified live** on `glm-5.3` |
| Next.js status page connected to the backend | Implemented and verified with Playwright |
| World Engine: per-world SQLite CRM, tool gateway, Phantom Success and Phantom Failure faults | Implemented and tested against real SQLite (`tests/world`) |
| Truth Oracle: `PASS` / `VIOLATION` / `INCONCLUSIVE` from authoritative state only | Implemented and tested, including tamper resistance |
| `make world-demo`: 10 reference cases (deterministic scripts, **not** LLM agents) | Real runs; offline; free |
| Multi-turn tool-calling contracts (tool-call ids preserved, `role=tool` results) | Implemented and tested offline (fixtures) |
| Target Agent: bounded LLM tool loop, baseline/hardened policies, Oracle-evaluated run reports | Implemented; tested offline with labeled fixtures; **verified live on `glm-5.3`** ([results](docs/evaluations/sprint-03-glm-5.3.md)) |
| `make agent-run` / `make agent-eval`: live single runs and baseline-vs-hardened evaluation | Implemented and run live |
| Experiment runtime: sandbox → trusted coordinator → Target Agent → CRM → Oracle | Implemented; containment tested on real Docker; **verified live** on `glm-5.3` ([design](docs/architecture/experiment-runtime.md)) |
| Investigator: one model writes and revises Python experiments inside a deterministic workflow | Implemented; hostile programs tested on real Docker; **run live** on `glm-5.3` ([design](docs/architecture/investigator.md)) |
| Registered evaluation: frozen manifests, eligibility, causal contrasts, adaptation scoring | Implemented; **run live** on `glm-5.3` ([design](docs/architecture/evaluation.md)) |
| Investigation Explorer: overview, timeline, Reality Comparison, Investigator view | Implemented; **real recorded evidence**; verified with Playwright ([design](docs/architecture/product-experience.md)) |
| Evidence API: read-only, validated, hash-pinned ([contracts](docs/architecture/evidence-api.md)) | Implemented and tested |
| Operator missions: token-gated, one at a time, SSE progress, restart classification | Rehearsals verified on real Docker; **one live mission run** from the browser on `glm-5.3`. Refused by the ledger as shipped until the owner raises the limit |
| Spend ledger: worst-case reservation and a $5 sprint limit | Implemented. An estimate at assumed prices, **not** a provider billing limit ([policy](docs/deployment/live-budget.md)) |

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

Open <http://127.0.0.1:3000>. The recorded investigations need no provider key and spend nothing.

To use the Operator page, set `MOODY_OPERATOR_TOKEN` in `.env` (see `.env.example`) and restart. Rehearsal
missions are free but need Docker and the pinned image; `make investigator-preflight` checks both.
Chargeable missions also need `MOODY_LIVE_RUNS_ENABLED=true` and a ledger with room:
[budget policy](docs/deployment/live-budget.md).

To run the production build:

```bash
make build
uv run uvicorn moody_blues.main:app --host 127.0.0.1 --port 8000
pnpm --dir frontend start --hostname 127.0.0.1 --port 3000
```

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install Python and Node deps from lockfiles, plus the Playwright browser |
| `make dev` | Run the backend (:8000, reload) and frontend (:3000) together |
| `make dev-backend` / `make dev-frontend` | Run one side only |
| `make lint` | `ruff format --check`, `ruff check`, ESLint |
| `make format` | Auto-format and auto-fix Python |
| `make typecheck` | Pyright (strict) and `tsc` |
| `make test` | Unit, World Engine, Target Agent, experiment, Investigator, evaluation and Explorer tests (offline: real SQLite, labeled fixtures, no network) |
| `make world-demo` | Run the World Engine reference cases: agent-visible responses, committed state, Oracle verdicts |
| `make test-integration` | Real-Docker sandbox integration and containment tests |
| `make build` | Production frontend build |
| `make test-e2e` | Build, then Playwright against the real backend and frontend |
| `make check` | All of the above. The local acceptance gate. |
| `make doctor` | Check the toolchain, Docker, Playwright and config. Makes no chargeable calls. |
| `make docker-smoke` | Run the fixed smoke program in a real disposable container |
| `make vultr-models` | **Live:** list the catalog. The endpoint is unauthenticated, so this does **not** verify the key. |
| `make vultr-smoke` | **Live, chargeable:** basic inference, tool calling, and a multi-turn tool round trip |
| `make agent-run SCENARIO=… CONFIG=baseline\|hardened MODEL=…` | **Live, chargeable:** one Target Agent run, rendered trace, JSON report in `.artifacts/agent-runs/` |
| `make agent-eval TRIALS=3 MODEL=… CONFIRM=1` | **Live, chargeable batch:** bounded scenarios × configs × trials, summary in `.artifacts/agent-eval/`. Refuses without `CONFIRM=1`. |
| `make experiment-demo` | Seven real paths on Docker: real sandbox, coordinator, world and Oracle, with **deterministic reference executors**. No model; free. |
| `make experiment-test` | Offline experiment runtime tests |
| `make experiment-containment` | Real-Docker experiment runtime and containment tests |
| `make experiment-live CASE=… CONFIG=… CONFIRM=1` | **Live, chargeable:** one sandboxed experiment driving the real Target Agent. Refuses without `CONFIRM=1`. |
| `make experiment-recover` | Remove orphan sandboxes and close experiments whose coordinator died |
| `make investigator-preflight` | Verify the generated-code sandbox on this host. Free. |
| `make investigator-demo` | **Fixture** model with real sandboxes, worlds and Oracle. Free. |
| `make investigator-test` / `make investigator-containment` | Offline tests / hostile programs on real Docker |
| `make investigator-live TIER=… STRATEGY=… CONFIRM=1` | **Live, chargeable:** one investigation. Refuses without `CONFIRM=1`. |
| `make investigator-eval TIER=… PART=… EVAL_TRIALS=… REPEATS=… CONFIRM=1` | **Live, chargeable:** paired tests and strategy comparison. Refuses without `CONFIRM=1`. |
| `make investigator-repro EXPERIMENT=… RUNS=… CONFIRM=1` | **Live, chargeable:** rerun one generated program unchanged, in fresh worlds (at most 8). |
| `make evidence-audit` | Reclassify existing live evidence by eligibility. Reads only; free. |
| `make eval-verify` / `make eval-report` | Check the registration against the code / recompute results from journals. Free. |
| `make eval-run SUITE=… CONFIRM=1` | **Live, chargeable:** one registered suite. Refuses unless the registration is committed and matches the code. |
| `make eval-repro EXPERIMENT=… RUNS=… CONFIRM=1` | **Live, chargeable:** a registered rerun under the manifest's limits. |
| `make recorded-verify` / `make recorded-export` | Check the recorded investigations / rebuild them from local records. Free. |
| `make live-budget` | Show the estimated spend ledger. Makes no calls. |
| `make sandbox-clean` | Remove any leftover sandbox containers |
| `make clean` | Remove caches and build output |

`make world-demo` writes JSON run reports to `.artifacts/world-demo/`. To run a single case,
use `uv run moody-blues world-run --scenario phantom-failure --executor blind_retry [--json]`.
Live smoke output is written to `.artifacts/` (git-ignored). Without a key, the live commands
exit `2` with `BLOCKED_BY_CREDENTIALS`.

## Configuration

All settings come from `MOODY_*` environment variables or `.env`. See
[.env.example](.env.example). The Vultr key stays on the server; the browser never sees it.

## Documentation

- [Product experience](docs/architecture/product-experience.md) · [Evidence API](docs/architecture/evidence-api.md) · [Recorded investigations](docs/architecture/recorded-investigations.md) · [Threat model](docs/security/threat-model.md) · [ADR 0007](docs/adr/0007-investigation-explorer.md) · [Sprint 7 record](docs/sprints/sprint-07.md) · [Hosted readiness](docs/deployment/sprint-8-readiness.md)
- [Architecture overview](docs/architecture/overview.md) · [World Engine](docs/architecture/world-engine.md) · [Target Agent](docs/architecture/target-agent.md) · [Experiment runtime](docs/architecture/experiment-runtime.md) · [Investigator](docs/architecture/investigator.md)
- [ADR 0001](docs/adr/0001-architecture.md) · [ADR 0002](docs/adr/0002-world-engine.md) · [ADR 0003](docs/adr/0003-target-agent.md) · [ADR 0004](docs/adr/0004-experiment-runtime.md) · [ADR 0005](docs/adr/0005-autonomous-investigator.md)
- [Sprint 6 report](docs/evaluations/sprint-06/report.md) · [Registered evaluation](docs/architecture/evaluation.md) · [ADR 0006](docs/adr/0006-registered-evaluation.md) · [Sprint 6 record](docs/sprints/sprint-06.md)
- [Sprint 1](docs/sprints/sprint-01.md) · [Sprint 2](docs/sprints/sprint-02.md) · [Sprint 3](docs/sprints/sprint-03.md) · [Sprint 4](docs/sprints/sprint-04.md) · [Sprint 5](docs/sprints/sprint-05.md) · [Evaluation methodology](docs/evaluations/methodology.md) · [Validation](docs/testing/validation.md)
- [Known issues](docs/troubleshooting/known-issues.md) · [Vultr preflight](docs/deployment/vultr-preflight.md) · [Live budget](docs/deployment/live-budget.md)
- Contributor rules: [AGENTS.md](AGENTS.md)

## License

**Pending.** No license has been chosen yet. Until one is, all rights are reserved by the
authors.
