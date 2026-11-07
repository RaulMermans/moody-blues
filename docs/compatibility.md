# Compatibility

For v0.1.0, developer alpha. Nothing here promises compatibility with a future version.

| Component | Version | Stability |
|---|---|---|
| Product | 0.1.0 | Alpha |
| Python SDK, `moody-blues-sdk` | 0.1.1 | Alpha. Not on a package index |
| Agent protocol | `mb-agent/1` | Alpha. A change an existing agent cannot ignore becomes a new protocol version |
| World contract | `mb-world/1` | **Alpha, subject to change.** Not a stable plugin ABI. Worlds are trusted code registered in the source |
| Experiment protocol | `mb-exp/1` | Internal |
| Evidence schema | 1, 2, 3 | Every version stays readable. 2 holds an external run, 3 a run from another world |

## SDK and protocol

| SDK | `mb-agent/1` | `record_id` in a final report | Notes |
|---|---|---|---|
| 0.1.1 | Yes | Yes | Current |
| 0.1.0 | Yes | Before or after, unknown (KI-78) | Still accepted. `bundle_sha256` in the evidence identifies exactly what ran |

Both versions report `mb-agent/1`. `record_id` is additive, so an agent that ignores it keeps working.

## Runtimes

| Runtime | Supported |
|---|---|
| Python 3.12 or newer, for the SDK and backend | Yes. The sandbox image is `python:3.12-slim`, pinned by digest |
| Node 20.9 or newer, pnpm 10 | Yes |
| Other languages, agent frameworks | **No.** A framework can be used only from inside a Python adapter that needs nothing beyond the standard library, which rules most out |

## Model providers

| Provider | State |
|---|---|
| Labeled fixture | Default. Not a model, and says nothing about any LLM |
| Ollama, local | Experimental. Verified on one Mac with one small model |
| Vultr Serverless Inference | Used for past evaluations. Paid, operator only, and never used by a default command. A real hosted model has not driven an external agent |
| Any other provider | Not supported |

Operating systems: [supported platforms](supported-platforms.md).
