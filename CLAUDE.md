# CLAUDE.md

Follow [AGENTS.md](AGENTS.md). It is the canonical rule set for this repository and wins any
conflict. This file adds nothing that contradicts it.

Quick orientation:
- `make help` lists commands. `make check` is the local acceptance gate. `make doctor` diagnoses
  the environment.
- `make vultr-smoke` / `make vultr-models` / `make agent-run` / `make agent-eval` /
  `make experiment-live` / `make investigator-live` / `make investigator-eval` / `make eval-run` / `make eval-repro` make **live** calls (all but `vultr-models` are chargeable). Run them
  only when asked. `make live-budget` shows the estimated spend.
- Latest sprint record: [docs/sprints/sprint-15.md](docs/sprints/sprint-15.md) (earlier: [sprint-14.md](docs/sprints/sprint-14.md), [sprint-13.md](docs/sprints/sprint-13.md), [sprint-12.md](docs/sprints/sprint-12.md), [sprint-11.md](docs/sprints/sprint-11.md), [sprint-10.md](docs/sprints/sprint-10.md), [sprint-07.md](docs/sprints/sprint-07.md), [sprint-06.md](docs/sprints/sprint-06.md), [sprint-05.md](docs/sprints/sprint-05.md), [sprint-04.md](docs/sprints/sprint-04.md), [sprint-03.md](docs/sprints/sprint-03.md), [sprint-02.md](docs/sprints/sprint-02.md), [sprint-01.md](docs/sprints/sprint-01.md)).
- Deployment: [docs/deployment/vultr-deployment.md](docs/deployment/vultr-deployment.md). `provision.sh apply`, `deploy.sh` and `live-switch.sh` act on real resources: run them only when asked.
- External agents: [quickstart](docs/external-agents/quickstart.md), [protocol](docs/architecture/external-agent-protocol.md), [ADR 0012](docs/adr/0012-external-agent-adapter.md). `make external-demo`, `make external-test`. `make external-run LIVE=1 CONFIRM=1` is live and chargeable.
- Design system, used by the product: [docs/design/README.md](docs/design/README.md). `make design-lab`, `make test-design`.
- Known problems: [docs/troubleshooting/known-issues.md](docs/troubleshooting/known-issues.md).
