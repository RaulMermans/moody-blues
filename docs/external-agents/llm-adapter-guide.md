# External LLM adapter guide

For a developer connecting an agent that uses a model. Start with the [quickstart](quickstart.md).

Your agent never holds a key and has no network. It asks the host, the host calls the model, and the answer
comes back over the same protocol. The rules are in the [model-call policy](../security/model-call-policy.md).

## 1. Declare it

```toml
target_type = "llm"
capabilities = ["tools", "cancellation", "model"]
```

This is a claim, and only a claim. A run is labeled a model run only if the host brokered a call in it.

## 2. Write the loop

```python
from moody_blues_sdk import AgentAdapter, AgentResult, ModelUnavailable, ToolCallTimeout

class MyAgent(AgentAdapter):
    agent_id = "my-agent"
    name = "My agent"
    target_type = "llm"
    capabilities = ("tools", "cancellation", "model")

    def run(self, context, tools):
        if context.model is None:
            return AgentResult.failed("model_not_granted")
        messages = [{"role": "user", "content": context.task.mission}]
        try:
            reply = context.model.complete(messages)
        except ModelUnavailable as exc:
            return AgentResult.failed("model_unavailable", message=exc.code)
        ...
```

`examples/external-agent/acme_crm_agent/llm.py` is a complete loop. Three things to copy from it:

- **Pass model-written arguments with `tools.call_with(name, arguments)`.** Bad ones are the host's to refuse.
- **Handle `ModelUnavailable` by its `.code`.** After `model_call_timeout` the call may have run and been billed.
  The host will not repeat it. Asking again is your decision, and it spends your budget.
- **Report what you verified.** `final` is a claim. The Oracle reads committed state either way.

## 3. Test it offline

```bash
make external-preflight MANIFEST=path/to/my.agent.toml
MOODY_ARTIFACTS_DIR=/tmp/mb make external-investigate TARGET=external_llm MANIFEST=path/to/my.agent.toml
```

This is free. A labeled fixture answers your model calls: **it is a CRM script, not a model**, so it exercises
your loop and the protocol, and tells you nothing about how your agent behaves with a real one. If your agent
expects a different reply format from the fixture's, that is a limit of the fixture.

Always set `MOODY_ARTIFACTS_DIR` to scratch when experimenting. Runs publish into `live-jobs` under it.

## 4. Read the result

The command prints the Oracle verdict, the brokered call count and where the evidence is. `model_requests` in
`evidence.json` lists each call: status, request id, hashes, usage and latency.

## 5. Use a real model

This costs money and needs the owner's approval first. See
[live validation](live-validation-approval.md). Nothing live can start without `--confirm-billable`, an
`--approved-spend-usd` limit, a key on the host and a model on the allowlist.
