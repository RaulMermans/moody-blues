# SDK reference

`moody-blues-sdk` 0.1.1, speaking `mb-agent/1`. Python 3.12 or newer, standard library only. It is not published to a
package index: install it from a checkout with `pip install ./sdk/python`, for editor support. Inside the sandbox it is
provided for you. New here? Start with [Connect your agent](external-agents/quickstart.md). The wire format is
[mb-agent/1](architecture/external-agent-protocol.md), and the versions are in [compatibility](compatibility.md).

## Lifecycle

```text
host starts your container  ->  SDK sends hello  ->  host checks it against your manifest
host sends the run context  ->  your run() method  ->  SDK sends your AgentResult
host stops your process     ->  the Oracle reads committed state
```

One process, one run, one world, in a fresh container. Nothing persists between runs. Your code gets the standard
library and the SDK only, because the sandbox has no network and nothing can be installed in it.

## `AgentAdapter`

Subclass it and implement `run`. Class attributes must match your manifest.

```python
class MyAgent(AgentAdapter):
    agent_id = "my-agent"      # manifest: agent_id
    name = "My agent"          # manifest: name

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult: ...
```

## `ExecutionContext`

| Field | Meaning |
|---|---|
| `task.mission` | The whole assignment as prose. Give this to a model |
| `task.instructions` | How to report |
| `task.objective` | The task as data, in the terms of its world |
| `task.customer` | The customer to create. CRM only: it raises `ValueError` elsewhere |
| `tools` | Each `ToolDefinition`: `name`, `description`, `parameters` (JSON Schema), `access` |
| `scopes`, `capabilities` | What you were granted |
| `deadline_seconds`, `max_tool_calls` | Your limits. The deadline runs from when you received the context |
| `model` | A `ModelClient`, or `None`. Always handle `None` |
| `cancelled` | True once the host has asked you to stop |
| `scenario_ref` | An opaque id. It deliberately tells you nothing about the test |

## Calling tools

`tools.call(name, *, timeout=30.0, **arguments)` calls a tool once. `tools.call_with(name, arguments, timeout=30.0)` does
the same for arguments a model wrote, so a bad one is refused by the host, not by your code.

Neither ever retries. Whether to retry is exactly what is being tested.

`ToolResult`:

| Field | Meaning |
|---|---|
| `ok` | What the tool **said**. Not proof of what happened |
| `data` | The response body, or `None` |
| `error_code`, `error_message`, `retryable` | The tool's error, if any. May be a delivered fault |
| `rejected` | The call was refused before reaching the tool. Nothing happened |
| `evidence_ref` | Quote this in `AgentResult.evidence` |
| `calls_remaining` | Your remaining tool calls |

## Timeouts and cancellation

| Situation | What you see | What it means |
|---|---|---|
| No reply within `timeout` | `ToolCallTimeout` | The call may still have taken effect |
| The host cancels | `Cancelled`, or `context.cancelled` is true | Let `Cancelled` propagate |
| You pass your deadline | Your process is stopped | The run ends, and the Oracle still reads |
| You exceed `max_tool_calls` | A rejected result | Too many rejected calls end the run |

Whatever ends a run, the host stops your process first and the Oracle reads afterwards.

## Your final report

Your report is a **claim**. It is recorded and checked against state, and decides nothing.

| Return | When |
|---|---|
| `AgentResult.completed(customer_id=..., message=..., evidence=...)` | You finished, and believe the task is done |
| `AgentResult.not_completed(message=...)` | You finished, and the task is not done |
| `AgentResult.failed(error_class=..., message=...)` | You could not finish |

In a world without customers, pass `record_id=` instead of `customer_id=`. `evidence` holds `evidence_ref` values; any that
match no call in the run are recorded as unknown and believed by nothing. `message` is cut at 2,000 characters.

An unhandled exception in `run` is reported as a failure. `print` and tracebacks go to stderr, and the end of it is kept at
`external.exit.untrusted_stderr_excerpt` in the evidence.

## Permissions

The manifest's `scopes` decide your tools. Asking for a tool you were not granted is refused before it reaches the world.

| World | Scope | Tools |
|---|---|---|
| CRM | `crm:read` | `get_customer`, `search_customers` |
| CRM | `crm:write` | `create_customer` |
| Job Queue | `queue:read` | `get_job`, `get_job_status`, `list_jobs` |
| Job Queue | `queue:write` | `submit_job` |

`capabilities` are `tools`, `cancellation` and `model`. `target_type` is `scripted`, or `llm` if a model drives the agent.
It is your word for it and is only recorded: only a model call the host brokered makes a run an LLM run.

## Model calls

`context.model.complete(messages, timeout=60.0)` returns a `ModelReply` with `content`, `tool_calls` and `finish_reason`.
The call goes through the host, which holds any key and budget. You never name a model or an endpoint. It raises
`ModelUnavailable` when the host refuses, with `.code` and `.message`. Declare the `model` capability and set
`target_type = "llm"`. See the [LLM adapter guide](external-agents/llm-adapter-guide.md).

By default a labeled fixture stands in for the model, so those runs say nothing about any LLM.
[Local models](external-agents/local-models.md) lets a real model on your machine answer, for free.

## Errors from the host

If your agent never starts, `make external-preflight MANIFEST=path` prints `rejection` and `stderr`. The manifest's
`agent_id`, `version` and `target_type` must match your class. Only `.py`, `.json`, `.toml` and `.txt` files are shipped,
with no symbolic links. A line that is not a valid message ends the run; it is never repaired.

## Examples

[`examples/external-agent`](../examples/external-agent) and [`examples/job-queue-agent`](../examples/job-queue-agent) each
hold a safe agent, an unsafe one and a model-driven one. They import only the SDK and the standard library.
