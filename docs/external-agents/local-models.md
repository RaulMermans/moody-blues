# Local models

Run an agent, and optionally the Investigator, on a model on your own machine. Nothing is paid, and the Vultr key and
ledger are not touched. Experimental: proven on one machine with one small model.
Decision: [ADR 0014](../adr/0014-local-inference-provider.md). Results: [Sprint 17 evaluation](../evaluations/sprint-17/README.md).

## Run it

```bash
export MOODY_ARTIFACTS_DIR=$(mktemp -d)              # keep runs away from .artifacts
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 ollama serve &    # never bind it to a public address
ollama pull qwen3:4b-instruct                        # 2.5 GB, about 5.3 GB of RAM in use
make local-preflight                                 # what is installed; generates nothing
make local-smoke                                     # one real generation
M=/absolute/path/to/your.agent.toml
make external-preflight MANIFEST=$M
make external-run MANIFEST=$M LOCAL=1 FAULT=none     # or phantom_failure, phantom_success
make external-investigate TARGET=external_llm MANIFEST=$M LOCAL=1 LOCAL_INVESTIGATOR=1
make local-eval MANIFEST=$M                          # the whole Sprint 17 set, checked from the evidence
MOODY_E2E_LOCAL_ARTIFACTS=$MOODY_ARTIFACTS_DIR make local-ui
```

Each run prints its investigation id. To open it, start `make dev` with `MOODY_OPERATOR_TOKEN` set and the same
`MOODY_ARTIFACTS_DIR`, sign in at `/operator`, and open `/investigations/<id>`. Verify with the `evidence verification`
line, which reads every hash again.

`LOCAL=1` gives the agent a local model. `LOCAL_INVESTIGATOR=1` also makes the Investigator local. With `external-run`,
a labeled fixture chooses the faults, so the page says the tests were not a model's. No flags: labeled fixtures.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MOODY_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Literal loopback only. Anything else is refused before contact |
| `MOODY_OLLAMA_MODEL` | `qwen3:4b-instruct` | Must be on the allowlist |
| `MOODY_LOCAL_MODEL_ALLOWLIST` | `["qwen3:4b-instruct"]` | The only models anyone can select. Separate from the hosted one |
| `MOODY_OLLAMA_THINK` | `false` | Recorded with every run, because it changes what the model does |

To try another model, install it and set both `MOODY_OLLAMA_MODEL` and the allowlist. No code changes.

## Models

A model must report `completion` and `tools`, and support the policy's context. `make local-preflight` checks this.

| Model | Size | Measured here | Status |
|---|---|---|---|
| `qwen3:4b-instruct` Q4_K_M | 2.5 GB | 3-turn KITE runs, valid JSON every time, wrote valid experiment programs | **Selected.** Weak reasoning, see below |
| `qwen3:4b` Q4_K_M | 2.5 GB | Thinking build. Spent 2,048 tokens on turn one with `think` on or off, 4,789 uncapped. No tool call | **Unsuitable** for these limits |

Reporting `thinking` does not mean a model obeys `think: false`. `qwen3:4b` reasoned aloud in its answer instead. And
`qwen3:4b-instruct` also reports `thinking`, though it did not reason aloud.

## Resource policy

Local inference has no bill, so these limits are what bound it. Defined in `external/local.py`, recorded in each run's
`model_identity.policy`, and unaffected by anything an agent or model says.

| Limit | Value | Refusal |
|---|---|---|
| Model calls per run | 8 | `model_call_budget_exhausted` |
| Tokens per run | 30,000 | `token_budget_exhausted` |
| Output tokens per call | 2,048 agent, 4,096 Investigator | Cut off, and read as cut off |
| Prompt size | 32,000 bytes | `prompt_too_large`, or `provider_bad_request` |
| Context | 12,288 tokens | Refused before sending, never truncated |
| One agent call | 60 s, then aborted | `model_call_timeout` |
| One Investigator call | 180 s | `provider_error` |
| Agent run | 95 s, inside the sandbox's 120 s ceiling | `wall_timeout` |
| Concurrent generations | 1 | `provider_rate_limited` |
| Experiments | 2, no reproductions | |
| Investigator calls | 4 | |
| Investigation | 600 s | |

## Evidence

| Source | Meaning |
|---|---|
| `offline_fixture` | A labeled stand-in. Never model behavior |
| `external_scripted` | The host brokered no model call |
| `local_ollama` | A model on the operator's machine, through the broker |
| `live_provider` | A hosted, paid provider |

Recorded for local runs: provider, model name and digest, server version, family, size, quantization, capabilities,
context limit, thinking setting, host OS and architecture, and the policy (`model_identity`, `investigator_identity`).
Per call: request id, reported model, tokens, latency, and load, prompt and generation time. Prompts and answers follow
the existing rule: hashes in the broker's record, the model's text in the run's steps. Hidden reasoning is measured
(`thinking_chars`) and never passed to the agent or stored.

## Security

- The sandbox has no network, so it cannot reach Ollama. `test_a_local_model_server_cannot_be_reached` tries from inside
  a real container, by loopback, bridge, VM host and host name.
- An agent names no model or endpoint. A request cannot change the client's model.
- Ollama has no authentication. Keep it on loopback: anything else on this machine can already call it.
- A local run proves nothing about hosted containment, which is still `NOT_RUN` for external agents.
