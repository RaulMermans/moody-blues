# External agent protocol: `mb-agent/1`

The authoritative types are in
[contracts/adapter.py](../../backend/moody_blues/contracts/adapter.py). This page explains them. The
decision behind it is [ADR 0012](../adr/0012-external-agent-adapter.md). To connect an agent, start
with the [quickstart](../external-agents/quickstart.md); the SDK writes all of this for you.

## Transport

One JSON document per line, UTF-8, over the agent's stdin and stdout, with `"protocol": "mb-agent/1"`
in every message. stderr is captured, bounded, kept as untrusted text, and never parsed. Before the
protocol starts, the host sends a 4-byte big-endian length and the code bundle.

Limits: a line from the agent is at most 65,536 bytes, a bundle at most 4,000,000.

## Conversation

```
agent                                         host
  │  hello {agent}                             │  checked against the manifest
  │ ─────────────────────────────────────────▶ │
  │  welcome {context}   or   refused {code}   │
  │ ◀───────────────────────────────────────── │
  │  tool_call {call_id, tool, arguments}      │  validated, then the gateway, once
  │ ─────────────────────────────────────────▶ │
  │  tool_result {call_id, evidence_ref,       │  exactly what the gateway delivered
  │    response | rejection, calls_remaining}  │
  │ ◀───────────────────────────────────────── │
  │  model_call {call_id, messages}            │  only if granted; the host holds the key
  │ ─────────────────────────────────────────▶ │
  │  model_result {call_id, content, ...}      │
  │ ◀───────────────────────────────────────── │
  │  final {completion, outcome, message, ...} │  a claim, for the Oracle to check
  │ ─────────────────────────────────────────▶ │
```

The host may send `cancel` at any time. `tool_call` and `model_call` are answered in order.

## Messages

| Direction | Type | Fields |
|---|---|---|
| Agent | `hello` | `agent`: `agent_id`, `name`, `version`, `target_type`, `capabilities`, `config_refs`, `sdk_version` |
| Agent | `tool_call` | `call_id`, `tool`, `arguments` |
| Agent | `model_call` | `call_id`, `messages` (model, temperature, tools and limits are the host's) |
| Agent | `final` | `completion` (`finished`, `failed`, `cancelled`), `outcome` (`status`, `customer_id`), `message`, `error_class`, `evidence_refs` |
| Host | `welcome` | `context`: `run_id`, `correlation_id`, `scenario_ref`, `task`, `tools`, `scopes`, `deadline_seconds`, `max_tool_calls`, `capabilities` |
| Host | `refused` | `code`, `supported_protocols` |
| Host | `tool_result` | `call_id`, `evidence_ref`, `response` (a `ToolResponse`) or `rejection`, `calls_remaining` |
| Host | `model_result` | `call_id`, `content`, `tool_calls`, `finish_reason`, or `rejection` |
| Host | `cancel` | `reason` |

`scenario_ref` is opaque on purpose: real scenario ids name their faults. `tool_result.response` is
the same `ToolResponse` a model-driven target receives, with no marking if a fault changed it.
`evidence_ref` is the gateway's call id, and an agent can quote it in `final.evidence_refs`. A
reference that matches no call is recorded in `unknown_evidence_refs` and believed by nothing.

## Versioning

The `protocol` field is checked on every line. An unsupported version at the handshake is answered
with `refused` and the list of supported versions, and the run ends with
`protocol_version_mismatch`. A change that an existing agent cannot ignore is a new version. There
is no negotiation or downgrade: a host supports a listed set, and only `mb-agent/1` exists today.

Evidence has its own version. `ExperimentEvidence.schema_version` is 2 when a record holds an
external run, and 1 otherwise. A record is never migrated or rewritten: version 1 readers are
unaffected, because nothing but an external run changes what is written.

## What happens to bad input

| Input | Outcome |
|---|---|
| A line that is not one valid message: bad UTF-8, bad JSON, duplicate keys, `NaN`, wrong protocol, unknown `type`, extra or missing fields, over the size limit | **Run ends**, `malformed_message`. Never repaired. Kept by hash, not by content |
| `hello` that disagrees with the manifest, or asks for an undeclared capability | **Refused**, `handshake_rejected` |
| Anything but `hello` first | **Refused**, `handshake_rejected` |
| A second `hello` | **Run ends**, `malformed_message` |
| Unknown tool, a tool outside the agent's scopes, invalid arguments, a reused `call_id`, a call after the quota | **Answered** with a `rejection`. Nothing reaches the gateway. The agent may carry on |
| More than `max_rejected_calls` of those | **Run ends**, `rejected_call_limit` |

A forged `tool_result` from an agent is an unknown inbound `type`, so it ends the run. An agent has
no message that can touch the Oracle or state.

## How a run ends

| Termination | Meaning | Retried? |
|---|---|---|
| `final_claim` | A valid `finished` report arrived | Never |
| `agent_reported_failure` | The agent said it could not finish | Never |
| `no_final_claim` | It exited cleanly without reporting | Never |
| `adapter_crashed` | It died, or was OOM-killed, before reporting | Never |
| `wall_timeout` | It ran past its deadline and was killed | Never |
| `malformed_message` | See above | Never |
| `rejected_call_limit` | See above | Never |
| `cancelled` | An operator cancelled it | Never |
| `adapter_startup_failed` | No valid `hello` before the startup deadline, or the sandbox did not start | Never |
| `protocol_version_mismatch`, `handshake_rejected` | Refused at the door | Never |

Whatever the ending, the process is stopped first and then **the Oracle reads the world**. A crash
after two commits is still a duplicate. The last three endings mean the agent never ran: they stop
the experiment as `failed`, because asking again would fail the same way. The others are findings
about the target, and the experiment goes on.

### What may be retried

| Operation | Rule |
|---|---|
| A target run, including one that never started | **Never**, automatically. An operator can start a new run |
| A tool call | **Never**, by host or SDK. A reused `call_id` is refused. The agent may issue a *new* call: that decision is what is being tested |
| A sandbox step of an experiment | Up to `sandbox_infra_retries`, only for infrastructure failures, as before. It has no world effects |
| A provider request from an agent's `model_call` | **Never.** Live clients run with `max_retries=0`. A call with no trusted answer is `uncertain`, and the agent may ask again under a new `call_id`, inside its budget |

If the coordinator dies mid-run, nothing resumes: `make experiment-recover` closes the experiment as
`uncertain` and reads what the world holds. The container stops at its own in-container deadline,
and the API removes it at start-up, or `make sandbox-clean` does.

## Timeouts

| Limit | Default | Enforced by |
|---|---|---|
| Startup, to a valid `hello` | 20 s | Host |
| Run, from `welcome` | 60 s, or less if the experiment has less left | Host |
| Grace after `cancel` | 1 s, then killed | Host |
| Grace after `final` | 1 s, then killed | Host |
| Writing to an agent that stopped reading | 5 s, then the run ends | Host |
| A tool call, from the agent's side | 30 s, `timeout=` per call | SDK |
| Hard stop if the host process is gone | Run limit plus 10 s | Inside the container, as PID 1 |

A `ToolCallTimeout` in the agent does not mean the call failed: it may have taken effect. A late
reply is dropped, never matched to a later call.

## Evidence

Each run adds an `ExternalAgentRecord` to the run report and the experiment evidence: identity,
protocol and SDK versions, manifest and bundle hashes, environment, limits, granted tools and
scopes, `model_calls`, startup and wall time, exit, any rejection, the raw final report, unknown
references, a hash chained over every protocol line, and the lifecycle events. These events are also
logged as `adapter_event`, with ids and fixed codes only, never agent text or arguments.

| Label | `target_kind` | `evidence_source` |
|---|---|---|
| Internal LLM target | `llm_agent` | `live_provider` |
| External LLM target | `external_agent` | `live_provider` |
| External LLM target, local model | `external_agent` | `local_ollama` |
| External scripted adapter | `external_agent` | `external_scripted` |
| Reference rehearsal | `reference_executor` | `reference_executor` |
| Any target on a fixture model | either | `offline_fixture` |

Only `live_provider` and `local_ollama` are evidence of model behavior, and an external run gets one only if the host
brokered a live model call in that run.

### Model calls (Sprint 16)

`mb-agent/1` is unchanged on the wire. An agent that ignores these still works: refusals gained codes, and events
gained kinds. Each `model_call` leaves a `ModelCallRecord` in `external.model_requests`, written by the host:
`request_id` (`<run_id>.m<n>`, stable for the run), the agent's `call_id`, `status`, `code`, the approved model, what
the provider reported, hashes and sizes of the conversation and answer, usage, and latency. The conversation
itself is not stored.

`evidence_source` is decided by these records: any request that reached a provider makes the run `live_provider`
or `offline_fixture`, even if it failed. `declared_target_type` never does. See the
[model-call policy](../security/model-call-policy.md).

An investigation also records `request.target`, a `TargetProvenance`: the kind selected, the bundle and manifest
hashes, and whether a broker was a fixture or live. That is what was chosen. The run records are what happened.

All of this is optional and left out when empty, so schema 1 and 2 evidence parses and hashes as before.
