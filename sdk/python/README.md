# moody-blues-sdk

Implement `AgentAdapter.run`, and MOODY BLUES can test your agent. The SDK has no dependencies, so it
runs inside the bare, network-less sandbox your agent is placed in.

```python
from moody_blues_sdk import AgentAdapter, AgentResult, ExecutionContext, ToolClient


class MyAgent(AgentAdapter):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        customer = context.task.customer
        created = tools.call("create_customer", name=customer.name, email=customer.email)
        if not created.ok:
            return AgentResult.not_completed(message=f"create failed: {created.error_code}")
        return AgentResult.completed(customer_id=created.data["customer"]["customer_id"])
```

Version 0.1.1, alpha, for `mb-agent/1` and Python 3.12 or newer. Not on a package index: `pip install ./sdk/python` from a checkout.

Start with the [quickstart](../../docs/external-agents/quickstart.md), then the [reference](../../docs/sdk-reference.md). The wire format is
[mb-agent/1](../../docs/architecture/external-agent-protocol.md).
