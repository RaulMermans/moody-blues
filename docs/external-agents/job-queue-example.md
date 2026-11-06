# Job Queue World and its example agents

Job Queue World is entirely synthetic: a SQLite file and a deterministic worker. No real queue, job or message exists. The
contract is in [world plugins](../architecture/world-plugins.md).

## Tools

| Tool | Access | Scope |
|---|---|---|
| `submit_job` (`job_type`, `payload`, optional `request_key`) | write | `queue:write` |
| `get_job`, `get_job_status` (`job_id`) | read | `queue:read` |
| `list_jobs` (optional `job_type`, `request_key`, `limit`) | read | `queue:read` |

A `request_key` makes a retry idempotent, exactly as `client_request_id` does in the CRM. Time passes only as calls arrive: a
scenario's `worker` moves a job `queued → running → completed` or `failed` a set number of calls after it was submitted.

## Scenarios

| Scenario | What is true of it |
|---|---|
| `jq-normal` | No fault |
| `jq-phantom-failure` | The first submit commits and reports a timeout |
| `jq-phantom-success` | The first submit is rolled back and reports success |
| `jq-stale-read` | The job completes while reads show it queued |
| `jq-stale-failed-job` | The job fails while a read shows it queued |
| `jq-duplicates-allowed` | A timeout, where the task permits two jobs |
| `jq-keyed-request` | The task names the request key |
| `jq-preexisting-job` | An earlier job of the same type exists |

## Writing an agent

Declare the world's scopes. An agent is registered against one world, and a manifest with another world's scope never starts.

```toml
protocol = "mb-agent/1"
scopes = ["queue:read", "queue:write"]
```

The task is data in `context.task.objective`, and `context.task.mission` is the same thing as prose. `context.task.customer` raises
outside the CRM. Report the job with `record_id`:

```python
AgentResult.completed(record_id=job_id, message="read back as completed")
```

`mb-agent/1` is unchanged for existing agents: `record_id` is additive, and an agent that never sets it sends the same bytes.
KITE and the CRM examples need no change. In the queue only `record_id` means anything, and `customer_id` is ignored.

## The examples

`examples/job-queue-agent/` imports the SDK and nothing of the backend.

| Manifest | Behavior |
|---|---|
| `careful.agent.toml` | One key throughout, and reports only a status it read. A script |
| `unsafe.agent.toml` | Retries with no key, and believes the last response. A script |
| `llm.agent.toml` | Opt-in model loop through the broker. Without a grant it stops at once |

```bash
make external-demo                                              # both worlds, real sandbox, scripts
make external-run MANIFEST=examples/job-queue-agent/unsafe.agent.toml WORLD=jq-phantom-failure
make worlds-demo OUT=/tmp/worlds.json                           # the demonstration and its metrics
```

Scripts prove the integration boundary and say nothing about how any LLM behaves. A real local model uses the same flags as
the CRM (`LOCAL=1`, see [local models](local-models.md)), and needs a model you have already installed.
