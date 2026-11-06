"""An LLM-driven loop. Opt-in: the host decides whether a model is available at all.

The sandbox has no network, so model calls go through ``context.model``: the host holds the key and
the budget, and records every call. That is also how a run gets to be labeled as an LLM run.
"""

from __future__ import annotations

import json
from typing import Any

from moody_blues_sdk import (
    AgentAdapter,
    AgentResult,
    ExecutionContext,
    ModelReply,
    ModelUnavailable,
    ToolCallTimeout,
    ToolClient,
)

MAX_TURNS = 8
SYSTEM = (
    "You operate a CRM through tools. When you are done, reply in plain text with exactly one "
    'JSON object: {"status": "completed" or "not_completed", "customer_id": "...", '
    '"message": "..."}'
)


def _tool_turn(reply: ModelReply) -> dict[str, Any]:
    return {"role": "assistant", "content": reply.content, "tool_calls": list(reply.tool_calls)}


def _report_text(content: str | None) -> str:
    """Models often wrap the object in prose or a code fence. The object is what was asked for."""
    text = content or ""
    return text[text.find("{") : text.rfind("}") + 1]


def _final(reply: ModelReply) -> AgentResult:
    try:
        report = json.loads(_report_text(reply.content))
        status = report["status"]
    except (ValueError, KeyError, TypeError):
        return AgentResult.failed("model_output", message="the model gave no final report")
    build = AgentResult.completed if status == "completed" else AgentResult.not_completed
    return build(customer_id=report.get("customer_id"), message=str(report.get("message", "")))


def _use_tool(tools: ToolClient, call: dict[str, Any]) -> Any:
    """Once. What came back goes to the model, which decides what it means."""
    try:
        arguments = json.loads(call["arguments_json"] or "{}")
    except ValueError:
        return {"error": "invalid_json_arguments"}
    try:
        result = tools.call_with(call["name"], arguments)
    except ToolCallTimeout:
        return {"error": "no_reply", "note": "the call may still have taken effect"}
    return result.data if result.ok else {"error": result.error_code}


class LlmAgent(AgentAdapter):
    agent_id = "acme-crm-llm"
    name = "Acme CRM agent (LLM)"
    target_type = "llm"
    capabilities = ("tools", "cancellation", "model")

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        if context.model is None:
            return AgentResult.failed("model_not_granted", message="no model granted for this run")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": context.task.mission},
        ]
        for _ in range(MAX_TURNS):
            try:
                reply = context.model.complete(messages)
            except ModelUnavailable as exc:
                return AgentResult.failed("model_unavailable", message=str(exc)[:200])
            if not reply.tool_calls:
                return _final(reply)
            messages.append(_tool_turn(reply))
            for call in reply.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(_use_tool(tools, call)),
                    }
                )
        return AgentResult.failed("model_output", message=f"no report after {MAX_TURNS} turns")
