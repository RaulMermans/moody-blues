"""OFFLINE fixtures for Target Agent tests.

``ScriptedModel`` is a PROVIDER FIXTURE: a deterministic stand-in for an LLM that returns
pre-written turns (optionally computed from the conversation so far). Every result it
produces is labeled ``provider="fixture"``. Tests built on it show that the agent runtime,
protocol, budgets and Oracle integration behave correctly. They are NOT evidence of how any
real model behaves; live behavior comes only from ``make agent-run`` / ``make agent-eval``.

Worlds are real SQLite files, exactly as in tests/world.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from itertools import count
from typing import Any

from pydantic import JsonValue

from moody_blues.contracts.common import MoodyBluesError
from moody_blues.contracts.inference import (
    InferenceRequest,
    InferenceResult,
    TokenUsage,
    ToolCall,
    ToolResultMessage,
)

FIXTURE_PROVIDER = "fixture"
FIXTURE_MODEL = "fixture-model"

Turn = InferenceResult | MoodyBluesError | Callable[[InferenceRequest], InferenceResult]

_ids = count(1)


def call(
    name: str, arguments: dict[str, Any] | str | None = None, *, id: str | None = None
) -> ToolCall:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments or {})
    return ToolCall(id=id or f"fx_call_{next(_ids)}", name=name, arguments_json=raw)


def tools(*calls: ToolCall, content: str | None = None, usage: int | None = 100) -> InferenceResult:
    return _result(content=content, tool_calls=list(calls), usage=usage)


def text(content: str, *, usage: int | None = 50) -> InferenceResult:
    return _result(content=content, tool_calls=[], usage=usage)


def claim(status: str, customer_id: str | None = None, message: str = "") -> InferenceResult:
    args: dict[str, Any] = {"status": status, "message": message}
    if customer_id is not None:
        args["customer_id"] = customer_id
    return tools(call("submit_final_claim", args))


def _result(
    *, content: str | None, tool_calls: list[ToolCall], usage: int | None
) -> InferenceResult:
    return InferenceResult(
        provider=FIXTURE_PROVIDER,
        requested_model=FIXTURE_MODEL,
        reported_model=FIXTURE_MODEL,
        response_id=f"fx_resp_{next(_ids)}",
        content=content,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else "stop",
        usage=None
        if usage is None
        else TokenUsage(prompt_tokens=usage - 10, completion_tokens=10, total_tokens=usage),
        latency_ms=5,
    )


def last_results(request: InferenceRequest) -> list[dict[str, JsonValue]]:
    """Parsed tool-result payloads that answer the most recent assistant turn."""
    out: list[dict[str, JsonValue]] = []
    for m in reversed(request.messages):
        if not isinstance(m, ToolResultMessage):
            break
        out.append(json.loads(m.content))
    return list(reversed(out))


def customer_id_of(payload: dict[str, JsonValue]) -> str | None:
    data = payload.get("data")
    if isinstance(data, dict):
        customer = data.get("customer")
        if isinstance(customer, dict):
            cid = customer.get("customer_id")
            return cid if isinstance(cid, str) else None
        rows = data.get("customers")
        if isinstance(rows, list) and rows and isinstance(rows[-1], dict):
            cid = rows[-1].get("customer_id")
            return cid if isinstance(cid, str) else None
    return None


class ScriptedModel:
    """PROVIDER FIXTURE. Plays ``turns`` in order and records every request it receives."""

    def __init__(self, turns: Sequence[Turn]) -> None:
        self._turns = list(turns)
        self.requests: list[InferenceRequest] = []

    def complete(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        if not self._turns:
            raise AssertionError("ScriptedModel ran out of turns")
        turn = self._turns.pop(0)
        if isinstance(turn, MoodyBluesError):
            raise turn
        if isinstance(turn, InferenceResult):
            return turn
        return turn(request)

    @property
    def remaining(self) -> int:
        return len(self._turns)
