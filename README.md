# MOODY BLUES

**The Reality Distortion Lab for AI Agents.** We change the world around AI agents to discover when
their decisions stop matching reality.

Built for the Vultr Agent Rush Hackathon, *Blast Radius Zero* (Nov 3-8, 2026).

**Hosted demo:** <https://45-63-119-197.sslip.io>. Reading it needs no account and spends nothing.

![The MOODY BLUES landing page](docs/submission/screenshots/01-landing.png)

## What it does

AI agents can report success while their tool calls leave the real system wrong. MOODY BLUES tests
for that inside controlled environments:

1. An AI **Investigator** forms a hypothesis about how an agent could fail and writes a Python experiment.
2. The experiment runs in an isolated **Docker sandbox** with no network.
3. Trusted code **distorts** what the agent's tools return in a synthetic CRM.
4. A real LLM **Target Agent** works the task, and every call, response and claim is recorded.
5. An independent **Truth Oracle** reads committed state and gives the verdict.

The Explorer then shows three things side by side: what the agent observed and claimed, what the
authoritative state recorded, and what the Oracle concluded.

### The strongest recorded finding

The agent was asked to create one customer. The Investigator's first four hypotheses were refuted: the
agent recovered from each. The fifth combined a fake success with stale reads. The agent created the
customer again, then again without its idempotency key, and filed `completed` with **two records
committed where one was required**. The Oracle returned `VIOLATION`.

The agent's own message names both records, so this is a wrong status, not concealment. Registered
reruns reproduced it in 4 of 4 eligible runs; 1 impaired run was not counted.

![The Reality Comparison](docs/submission/screenshots/02-reality-comparison.png)

## Hosted live run

One investigation was started through the production application on 2026-11-05: `inv_cbd07a262444`. The
Investigator wrote three experiments, which ran in sandboxes on the Vultr VM, with model calls through Vultr
Serverless Inference. Seven faults reached the agent across three runs. It recovered each time, and the Oracle
returned `PASS` for all three. The outcome is **no violation found**, a correct recovery. One generated program
exited non-zero (`sandbox_exit_nonzero`) after its target run was under way; that run still finished with a claim.
The [exact bundle](evidence/live/README.md) is committed.

## The benchmark result: `NO_DEMONSTRATED_ADVANTAGE`

Adaptive investigation did **not** beat fixed testing. In the registered comparison, fixed testing found a
verified failure in 2 of 3 investigations, adaptive in 1 of 3, non-adaptive generation in 0 of 3, on a small
sample. MOODY BLUES can find and verify real failures; this benchmark does not show that adapting finds more
of them. See the [report](docs/evaluations/sprint-06/report.md) and [methodology](docs/evaluations/methodology.md).

## Architecture

```mermaid
flowchart LR
  B[Browser] -->|HTTPS| C[Caddy]
  subgraph VM[Vultr Cloud Compute VM]
    C --> N[Next.js]
    N --> A[FastAPI, one process]
    A --> K[Investigator + trusted coordinator]
    K <-->|validated actions only| D[Docker sandbox<br/>generated Python, no network]
    K --> T[Target Agent + tool gateway<br/>faults injected here]
    T --> W[(Synthetic CRM)]
    K --> O[Truth Oracle]
    O -->|read only| W
  end
  K -->|live missions only| V[Vultr Serverless Inference]
  T -->|live missions only| V
```

**Vultr usage:** Vultr Cloud Compute hosts the whole application and the sandboxes (`vc2-4c-8gb`, Frankfurt).
Vultr Serverless Inference runs `glm-5.3` for the Investigator and the Target Agent. Containment evidence
comes from the VM itself, identified by its instance metadata service.

## Security boundaries

- Generated code is untrusted: no network, read-only filesystem, non-root, memory, process and time limits.
- A sandbox can only request validated `mb-exp/1` actions. Only the coordinator reaches the agent, CRM and Oracle.
- A verdict comes only from the Oracle, which never sees what the agent was told.
- 8 of 8 [containment attempts](evidence/containment/vultr-report.json) were blocked on the Vultr VM.
- Anonymous visitors cannot start anything chargeable: that needs the operator token, a server switch and ledger room.
- Provider keys stay on the server. Live mode is off, with no key on the VM, between authorized runs.

## Limitations

- The five public investigations ran on `glm-5.3` through Vultr Serverless Inference before hosting. The hosted
  site serves their hash-checked records.
- One [hosted live investigation](evidence/live/README.md) has run. It found no violation, so the hosted
  environment has not itself produced a verified failure. Its view is operator-only.
- Containers share the host kernel. gVisor was not evaluated, and this is not a production security claim.
- The backend user is root-equivalent through Docker. One VM, no redundancy.
- The environment is a synthetic CRM. One run is one sample, not a rate, and results cover only the listed
  worlds, faults and model.
- The spend ledger is an application estimate at ceiling prices, not a provider limit.

## Testing and evaluation

`make check` runs lint, strict types, offline tests, real Docker containment tests and Playwright against a
production build. Hosted Playwright tests run against the deployment. Fixtures are labeled and never count as
model behavior. Scored trials run only from a committed manifest and plan. See
[validation](docs/testing/validation.md).

## Submission materials

The [submission pack](docs/submission/README.md) holds the copy, video script, claim sources and checklist.

## What works today

| Capability | State |
|---|---|
| FastAPI backend: `/health`, `/ready`, `/sandbox/smoke` (not in production) | Implemented and tested |
| Vultr deployment: scripts, Caddy, systemd, hosted test suite | **Deployed**; public browser suite passes. A live model run on the VM is outstanding |
| Containment report and page: eight real attempts, labeled with the host they ran on | **Verified on the Vultr VM** |
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
| Investigation Explorer: result, story, comparison, Investigator view, timeline and raw evidence | Implemented; **real recorded evidence**; verified with Playwright ([design](docs/architecture/product-experience.md)) |
| Evidence API: read-only, validated, hash-pinned ([contracts](docs/architecture/evidence-api.md)) | Implemented and tested |
| Operator missions: token-gated, one at a time, SSE progress, restart classification | Rehearsals verified on real Docker; **one live mission run** from the browser on `glm-5.3`. Refused by the ledger as shipped until the owner raises the limit |
| External agents: `mb-agent/1` over stdio, Python SDK, one long-lived process in the sandbox per run | Implemented and **verified on real Docker with scripted agents, and with a real local model driving an independent agent** ([record](docs/sprints/sprint-17.md)). A real hosted model has not driven one |
| Investigator against external targets: validated selection, real workflow and coordinator | Implemented and verified on real Docker. **A real local 4B model wrote hypotheses and experiments against an external agent**, which ran through the real coordinator. Its reasoning was weak ([results](docs/evaluations/sprint-17/README.md)) |
| Local inference through Ollama, loopback only, separate from the paid ledger | **Experimental.** Verified on one Mac with one small model ([guide](docs/external-agents/local-models.md)) |
| World plugins: CRM and Job Queue through one coordinator, Oracle path and evidence format | Implemented and **verified on real Docker with scripted agents** ([record](docs/sprints/sprint-18.md)). No real model has run in Job Queue World, and it is not deployed |
| Experiment validity: undelivered faults, and model assessments checked against structured records | Implemented. Regression cases use the real Sprint 17 errors; no live model has run with it |
| Spend ledger: worst-case reservation and a $5 sprint limit | Implemented. An estimate at assumed prices, **not** a provider billing limit ([policy](docs/deployment/live-budget.md)) |

## Worlds

MOODY BLUES runs the same coordinator, fault boundaries, Oracle path and evidence against two synthetic environments: a CRM and a
job queue. A world is a trusted, versioned plugin ([contract](docs/architecture/world-plugins.md), [ADR 0015](docs/adr/0015-world-plugins.md)),
with its own tools and deterministic invariants. **Two supported synthetic worlds are not general-purpose agent compatibility.**
Worlds are added in code, not uploaded, and Job Queue runs are local: nothing here is deployed. [Job Queue guide](docs/external-agents/job-queue-example.md).

## Bring your own agent

Write your agent against the [Python SDK](sdk/python), and MOODY BLUES runs it in the sandbox against
the same worlds, faults and Oracle as everything else. Your agent decides; trusted code holds the
tools, the limits and the verdict.

```sh
make external-demo   # two example scripts, real containers, free, no credentials
make external-investigate TARGET=external_llm MANIFEST=examples/external-agent/llm.agent.toml   # free
```

Start with the [quickstart](docs/external-agents/quickstart.md), then the
[LLM adapter guide](docs/external-agents/llm-adapter-guide.md) and the
[Investigator guide](docs/external-agents/investigator-integration.md). To use a model on your own machine, see
[local models](docs/external-agents/local-models.md).

**Works today:** Python agents you run locally, on the CRM tools and existing worlds, through the real sandbox,
broker, gateway and Oracle. By default a labeled fixture stands in for every model, and those runs say nothing about
any LLM. A real local model can take its place, on your own machine and for free.

**Not yet:** a real hosted model driving an external agent ([approval needed](docs/external-agents/live-validation-approval.md)),
external agents on the hosted VM, anything but Python, and any public way to submit an agent. Nothing here shows the
Investigator beats fixed testing.

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
| `make design-lab` / `make test-design` | Local specimen page on :3010, and the browser, axe and WebKit checks of the investigation screens. Never deployed |
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

- [Product experience](docs/architecture/product-experience.md) · [Evidence API](docs/architecture/evidence-api.md) · [Recorded investigations](docs/architecture/recorded-investigations.md) · [Threat model](docs/security/threat-model.md) · [ADR 0007](docs/adr/0007-investigation-explorer.md) · [Sprint 7 record](docs/sprints/sprint-07.md) · [Deploying to Vultr](docs/deployment/vultr-deployment.md) · [Provisioning plan](docs/deployment/sprint-8-provisioning-plan.md) · [ADR 0008](docs/adr/0008-single-vm-hosting.md)
- [Architecture overview](docs/architecture/overview.md) · [World Engine](docs/architecture/world-engine.md) · [Target Agent](docs/architecture/target-agent.md) · [Experiment runtime](docs/architecture/experiment-runtime.md) · [Investigator](docs/architecture/investigator.md)
- [ADR 0001](docs/adr/0001-architecture.md) · [ADR 0002](docs/adr/0002-world-engine.md) · [ADR 0003](docs/adr/0003-target-agent.md) · [ADR 0004](docs/adr/0004-experiment-runtime.md) · [ADR 0005](docs/adr/0005-autonomous-investigator.md)
- [Sprint 6 report](docs/evaluations/sprint-06/report.md) · [Registered evaluation](docs/architecture/evaluation.md) · [ADR 0006](docs/adr/0006-registered-evaluation.md) · [Sprint 6 record](docs/sprints/sprint-06.md)
- [Sprint 1](docs/sprints/sprint-01.md) · [Sprint 2](docs/sprints/sprint-02.md) · [Sprint 3](docs/sprints/sprint-03.md) · [Sprint 4](docs/sprints/sprint-04.md) · [Sprint 5](docs/sprints/sprint-05.md) · [Evaluation methodology](docs/evaluations/methodology.md) · [Validation](docs/testing/validation.md)
- [Known issues](docs/troubleshooting/known-issues.md) · [Vultr preflight](docs/deployment/vultr-preflight.md) · [Live budget](docs/deployment/live-budget.md) · [Key rotation](docs/security/key-rotation.md) · [Sprint 8](docs/sprints/sprint-08.md) · [Sprint 9](docs/sprints/sprint-09.md) · [Sprint 10](docs/sprints/sprint-10.md) · [Design](docs/design/README.md)
- [External agents: quickstart](docs/external-agents/quickstart.md) · [Protocol](docs/architecture/external-agent-protocol.md) · [ADR 0012](docs/adr/0012-external-agent-adapter.md) · [Sprint 15](docs/sprints/sprint-15.md)
- [World plugins](docs/architecture/world-plugins.md) · [ADR 0015](docs/adr/0015-world-plugins.md) · [Job Queue World](docs/external-agents/job-queue-example.md) · [Sprint 18](docs/sprints/sprint-18.md)
- Contributor rules: [AGENTS.md](AGENTS.md)

## License

**Pending.** No license has been chosen yet. Until one is, all rights are reserved by the
authors.
