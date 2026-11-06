"""Connect your own agent to a MOODY BLUES investigation. Standard library only.

Subclass ``AgentAdapter`` and implement ``run``. Everything your agent may do goes through the
``ToolClient`` it is handed. Nothing it reports is taken as truth: MOODY BLUES reads the outcome
from the world itself.
"""

from moody_blues_sdk.agent import (
    AgentAdapter,
    AgentResult,
    CustomerTask,
    ExecutionContext,
    Task,
    ToolDefinition,
)
from moody_blues_sdk.client import (
    Cancelled,
    ModelClient,
    ModelReply,
    ModelUnavailable,
    ToolCallTimeout,
    ToolClient,
    ToolResult,
)
from moody_blues_sdk.protocol import PROTOCOL_VERSION, SDK_VERSION

__all__ = [
    "PROTOCOL_VERSION",
    "SDK_VERSION",
    "AgentAdapter",
    "AgentResult",
    "Cancelled",
    "CustomerTask",
    "ExecutionContext",
    "ModelClient",
    "ModelReply",
    "ModelUnavailable",
    "Task",
    "ToolCallTimeout",
    "ToolClient",
    "ToolDefinition",
    "ToolResult",
]
