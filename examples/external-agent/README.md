# Example external agent

A separate project, as your repository would be. It imports the SDK and nothing of MOODY BLUES.

| Manifest | Policy | Model |
|---|---|---|
| `careful.agent.toml` | One idempotency key throughout; reports only what a read confirmed | None: a script |
| `unsafe.agent.toml` | Retries a failed write with no key; believes the last response | None: a script |
| `llm.agent.toml` | A tool loop driven by a model, through the host | Opt-in, chargeable, never yet run live |

```sh
make external-demo                                                 # both scripts, free
make external-run MANIFEST=examples/external-agent/careful.agent.toml
```

The two scripts prove the integration path and that the Oracle tells them apart. **They say nothing
about how any LLM agent behaves.** Follow the [quickstart](../../docs/external-agents/quickstart.md).
