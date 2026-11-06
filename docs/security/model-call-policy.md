# Model-call policy

How an external agent reaches a model. The agent has no network, so the host is the only route.
Tested in `tests/external/test_model_boundary.py`, with labeled doubles.

## Who decides what

| Decision | Who |
|---|---|
| Whether a model exists for this run | The operator, by command line |
| Provider, model, endpoint | The host. `MOODY_EXTERNAL_MODEL_ALLOWLIST` lists the models that can be lent |
| Temperature, max tokens, tools offered | The host |
| The conversation | The agent, as data. It is bounded and validated, and stored only as a hash and a size |

`model_call` carries a `call_id` and `messages`, and nothing else. A line naming a model or an endpoint is a
schema violation and ends the run. It is not filtered.

Local models have their own allowlist and limits: [local models](../external-agents/local-models.md). The boundary
is the same broker. The address must be literal loopback, and the sandbox cannot reach it.

## Limits, checked before a provider is asked

| Limit | Fixture | Live | Refusal code |
|---|---|---|---|
| Model calls per run, counting failures | 8 | 8 | `model_call_budget_exhausted` |
| Tokens per run, including this call's worst case | 30,000 | 30,000 | `token_budget_exhausted` |
| Conversation size | 48,000 bytes | 48,000 bytes | `prompt_too_large` |
| Output tokens per call | 4,096 | 4,096 | set by the host |
| Wait for one call | 45 s | 60 s | `model_call_timeout` |
| Run time | 60 s | 95 s | ends the run as `wall_timeout` |
| Refusals before the run ends | 8 | 8 | ends the run as `rejected_call_limit` |
| Reused `call_id`, shared with tool calls | refused | refused | `duplicate_call_id` |

## What became of a call

| Status | Meaning | Delivered | Ledger |
|---|---|---|---|
| `completed` | An answer arrived and was usable | Yes | Reported usage |
| `rejected` | Refused before a provider was asked | No | Nothing can be billed |
| `failed` | The provider refused it (auth, rate limit, bad request) | No | Reservation kept |
| `malformed` | The provider answered with something unusable | No | Reservation kept |
| `uncertain` | Timeout, connection or 5xx, or the host stopped waiting | No | Reservation kept |

A late answer is dropped. Nothing repeats a call: live clients have `max_retries=0`, and a new request can come
only from the agent's own decision, under a new `call_id`, inside the same budget.

## Crashes

| What dies | What happens |
|---|---|
| The agent, after a reply | Usage is already recorded. The Oracle reads the world |
| The agent, during a call | The answer has nowhere to go. It is recorded, nothing is retried |
| The coordinator | The run is `uncertain`. The intent file shows calls with no outcome as `model_calls_unresolved`. The ledger reservation stays open in full |

## What is not protected

- The agent writes the prompt, inside its budget. It can send the model anything it was told, including its
  mission. Nothing secret reaches it, so nothing secret can leave this way.
- The ledger is an estimate. It is not a provider limit, and it is not an invoice.
