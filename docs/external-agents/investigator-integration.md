# The Investigator and external targets

The Investigator runs the same workflow against any `TargetPort`. There is no separate external engine.

```bash
make external-investigate TARGET=external_scripted MANIFEST=examples/external-agent/careful.agent.toml
make external-investigate TARGET=external_llm      MANIFEST=examples/external-agent/llm.agent.toml
make external-investigate TARGET=internal_llm
```

| Step | Who | Where |
|---|---|---|
| Validate the selection against the manifest | Trusted code | `external/selection.py` |
| Discover: the agent's real hello in its sandbox | Trusted code | `ExternalAgentTarget.check_handshake` |
| Describe the target to the model | Trusted code | `investigator/catalog.py`, `external_capability` |
| Hypothesis and experiment | The Investigator's model | unchanged |
| Execute | The coordinator | unchanged |
| Verdict | The Oracle | unchanged |
| Observation back to the model | Trusted code, safe tokens only | unchanged |
| Revise, or conclude | The Investigator's model, inside the limits | unchanged |

## What runs for real

| | Offline | `LIVE=1` | `LIVE_INVESTIGATOR=1` |
|---|---|---|---|
| Workflow, coordinator, sandbox, worlds, Oracle | Real | Real | Real |
| Agent's code | Real | Real | Real |
| Agent's model | Labeled fixture | **Provider** | Labeled fixture, unless `LIVE=1` too |
| Investigator's model | Labeled fixture | Labeled fixture | **Provider** |

The offline Investigator is `ObservationDrivenFixture`. It branches on real observations, so it proves that
results reach the decision. It does not reason, and its hypotheses are fixed text. **A hypothesis written by a
model has not yet been made against an external target.**

## What to conclude

Keep these apart: the integration worked, an experiment ran, a fault was delivered, the agent recovered, the
Oracle found a violation, a failure reproduced, and evidence supports a cause. None implies the next.

Nothing here shows the Investigator finds failures better than fixed testing. The registered result stays
`NO_DEMONSTRATED_ADVANTAGE`.

## What the model is told

Fixed text about the kind of target, the tools it was granted, the expectations, the faults and the worlds. It is
told `config` has no effect. It is never told the agent's display name, its report text, or its stderr.
