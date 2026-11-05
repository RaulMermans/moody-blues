# CLAUDE.md

Follow [AGENTS.md](AGENTS.md). It is the canonical rule set for this repository and wins any
conflict. This file adds nothing that contradicts it.

Quick orientation:
- `make help` lists commands. `make check` is the local acceptance gate. `make doctor` diagnoses
  the environment.
- `make vultr-smoke` / `make vultr-models` / `make agent-run` / `make agent-eval` /
  `make experiment-live` / `make investigator-live` / `make investigator-eval` / `make eval-run` / `make eval-repro` make **live** calls (all but `vultr-models` are chargeable). Run them
  only when asked. `make live-budget` shows the estimated spend.
- Current sprint record: [docs/sprints/sprint-06.md](docs/sprints/sprint-06.md) (earlier: [sprint-05.md](docs/sprints/sprint-05.md), [sprint-04.md](docs/sprints/sprint-04.md), [sprint-03.md](docs/sprints/sprint-03.md), [sprint-02.md](docs/sprints/sprint-02.md), [sprint-01.md](docs/sprints/sprint-01.md)).
- Known problems: [docs/troubleshooting/known-issues.md](docs/troubleshooting/known-issues.md).
