# Documentation

## Use it

| Guide | For |
|---|---|
| [Installation](installation.md) | Prerequisites and setup. The one authoritative install page |
| [Quickstart](quickstart.md) | Your first test, reading a verdict, reproducing a failure, cleaning up |
| [Connect your agent](external-agents/quickstart.md) | Testing your own Python agent |
| [SDK reference](sdk-reference.md) | The adapter lifecycle, tools, model calls, timeouts, claims |
| [Evidence guide](evidence.md) | Verdicts, what each file holds, where state lives, how to check it |
| [Troubleshooting](troubleshooting.md) | Common failures. Every known issue: [known-issues.md](troubleshooting/known-issues.md) |

More on agents: [Job Queue World](external-agents/job-queue-example.md) · [LLM adapter guide](external-agents/llm-adapter-guide.md) · [Local models](external-agents/local-models.md) · [Investigating an external target](external-agents/investigator-integration.md)

## Know what it is

| Page | Answers |
|---|---|
| [Evaluation and limitations](evaluation-and-limitations.md) | What has been shown, and what has not |
| [Trust model](security/trust-model.md) | Who is trusted, what the sandbox enforces, what it does not |
| [Supported platforms](supported-platforms.md) | What has actually been tested |
| [Compatibility](compatibility.md) | Versions and contracts |
| [Security policy](../SECURITY.md) | Reporting a vulnerability |

## Extend it

[Adding a world](extending-worlds.md) · [World plugin contract](architecture/world-plugins.md) · [Protocol `mb-agent/1`](architecture/external-agent-protocol.md) · [Contributing](../CONTRIBUTING.md) · [Rules for working in this repository](../AGENTS.md)

## How it is built

[Overview](architecture/overview.md) · [World Engine](architecture/world-engine.md) · [Experiment runtime](architecture/experiment-runtime.md) · [Target Agent](architecture/target-agent.md) · [Investigator](architecture/investigator.md) · [Evaluation](architecture/evaluation.md) · [Benchmark](architecture/benchmark.md) · [Evidence API](architecture/evidence-api.md) · [Recorded investigations](architecture/recorded-investigations.md) · [Product experience](architecture/product-experience.md) · [Decisions (ADRs)](adr/) · [Design system](design/README.md) · [Validation](testing/validation.md)

## Operating a deployment

Maintainers only. [Deploying to Vultr](deployment/vultr-deployment.md) · [Live budget](deployment/live-budget.md) · [Key rotation](security/key-rotation.md) · [Model call policy](security/model-call-policy.md) · [Explorer threat model](security/threat-model.md) · [Hosted containment plan](security/hosted-containment-plan.md)

## Release

[v0.1.0 notes](release/v0.1.0.md) · [Changelog](../CHANGELOG.md) · [Publication plan](release/publication-plan.md) · [License decision](release/license-decision.md) · [Independent acceptance test](testing/independent-acceptance.md)

## Project history

Records of how the project got here. They describe what was true when written, are kept as they were, and may contradict
current guidance. Trust the pages above for how things work today.

- Sprint records: [1](sprints/sprint-01.md) · [2](sprints/sprint-02.md) · [3](sprints/sprint-03.md) · [4](sprints/sprint-04.md) · [5](sprints/sprint-05.md) · [6](sprints/sprint-06.md) · [7](sprints/sprint-07.md) · [8](sprints/sprint-08.md) · [9](sprints/sprint-09.md) · [10](sprints/sprint-10.md) · [11](sprints/sprint-11.md) · [12](sprints/sprint-12.md) · [13](sprints/sprint-13.md) · [14](sprints/sprint-14.md) · [15](sprints/sprint-15.md) · [16](sprints/sprint-16.md) · [17](sprints/sprint-17.md) · [18](sprints/sprint-18.md) · [19](sprints/sprint-19.md) · [20](sprints/sprint-20.md)
- Hackathon: [submission pack](submission/README.md), for the Vultr Agent Rush Hackathon, *Blast Radius Zero* (Nov 3-8, 2026). Archived as submitted
- Evaluations: [Sprint 6 registered evaluation](evaluations/sprint-06/report.md) · [Sprint 19 benchmark](evaluations/sprint-19/report.md) · [Methodology](evaluations/methodology.md)
- Hosted evidence: [the live investigation](../evidence/live/README.md) · [containment on the VM](../evidence/containment/vultr-report.json)
