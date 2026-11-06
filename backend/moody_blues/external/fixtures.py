"""OFFLINE stand-in for the model an external agent borrows. Everything here is ``offline_fixture``.

It answers ``model_call`` with fixed logic, so the whole loop can run with nothing paid for: the
agent's code, the protocol, the broker, the gateway, faults and the Oracle are real, and only the
words are not. It shows that the path works. It is never evidence of what any model does.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from moody_blues.agents.tooling import FINAL_CLAIM_TOOL
from moody_blues.contracts.inference import (
    AssistantToolCallMessage,
    ChatMessage,
    InferenceRequest,
    InferenceResult,
    TokenUsage,
    ToolCall,
    ToolResultMessage,
)
from moody_blues.contracts.scenario import Objective

FIXTURE_MODEL = "offline-fixture-agent"
Policy = Literal["verify", "blind"]


class CrmModelFixture:
    """TEST DOUBLE. ``verify`` searches after any write; ``blind`` retries and trusts the answer."""

    def __init__(self, objective: Objective, policy: Policy = "verify") -> None:
        self._objective = objective
        self._policy = policy

    def _reply(
        self, request: InferenceRequest, content: str | None, calls: list[ToolCall]
    ) -> InferenceResult:
        prompt = sum(len(m.model_dump_json()) for m in request.messages) // 4
        return InferenceResult(
            provider="fixture",
            requested_model=request.model or FIXTURE_MODEL,
            reported_model=FIXTURE_MODEL,
            response_id=f"fixture-{len(request.messages)}",
            content=content,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            usage=TokenUsage(prompt_tokens=prompt, completion_tokens=40, total_tokens=prompt + 40),
            latency_ms=1,
        )

    def _call(
        self, request: InferenceRequest, name: str, arguments: Mapping[str, object]
    ) -> InferenceResult:
        call = ToolCall(
            id=f"fx{len(request.messages)}", name=name, arguments_json=json.dumps(arguments)
        )
        return self._reply(request, None, [call])

    def _report(
        self, request: InferenceRequest, status: str, customer_id: str | None
    ) -> InferenceResult:
        body = {"status": status, "customer_id": customer_id, "message": "fixture report"}
        if any(t.name == FINAL_CLAIM_TOOL for t in request.tools):  # the internal agent's way
            return self._call(request, FINAL_CLAIM_TOOL, body)
        return self._reply(request, json.dumps(body), [])

    def _create(self, request: InferenceRequest) -> InferenceResult:
        customer = self._objective.customer
        return self._call(request, "create_customer", customer.model_dump(mode="json"))

    def complete(self, request: InferenceRequest) -> InferenceResult:
        done = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        asked = [
            c.name
            for m in request.messages
            if isinstance(m, AssistantToolCallMessage)
            for c in m.tool_calls
        ]
        if not isinstance(request.messages[0], ChatMessage) or not done:
            return self._create(request)
        delivered: dict[str, Any] = json.loads(done[-1].content)
        failed = "error" in delivered or delivered.get("ok") is False
        last: dict[str, Any] = delivered.get("data") or delivered  # internal agents see it all
        if self._policy == "blind":
            if failed and asked.count("create_customer") < 2:
                return self._create(request)
            return self._report(request, "completed", last.get("customer_id"))
        if asked[-1] == "create_customer":
            email = self._objective.customer.email
            return self._call(request, "search_customers", {"email": email})
        found: list[dict[str, Any]] = last.get("customers") or []
        if found:
            return self._report(request, "completed", found[0].get("customer_id"))
        return self._report(request, "not_completed", None)
