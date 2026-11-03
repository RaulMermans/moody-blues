"""Live Vultr smoke tests. Run explicitly: ``make vultr-smoke`` / ``make vultr-models``.

These make real, potentially chargeable requests. Without credentials they report
``BLOCKED_BY_CREDENTIALS`` and exit 2. They never fall back to fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from moody_blues.config import Settings
from moody_blues.contracts.inference import (
    AssistantToolCallMessage,
    ChatMessage,
    InferenceRequest,
    ToolResultMessage,
    ToolSpec,
)
from moody_blues.inference.vultr import InferenceError, VultrInferenceClient


class SmokeStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - status label, not a secret
    FAIL = "FAIL"
    BLOCKED_BY_CREDENTIALS = "BLOCKED_BY_CREDENTIALS"


class AddNumbersArgs(BaseModel):
    """Arguments for the harmless ``add_numbers`` tool; validated before use."""

    a: int
    b: int


ADD_NUMBERS_TOOL = ToolSpec(
    name="add_numbers",
    description="Add two integers and return the sum.",
    parameters={
        "type": "object",
        "properties": {
            "a": {"type": "integer", "description": "First addend"},
            "b": {"type": "integer", "description": "Second addend"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
)


def basic_inference(client: VultrInferenceClient) -> dict[str, Any]:
    result = client.complete(
        InferenceRequest(
            messages=[ChatMessage(role="user", content="Reply with exactly the word: pong")],
            max_tokens=16,
        )
    )
    ok = bool(result.content and "pong" in result.content.lower())
    return {
        "status": SmokeStatus.PASS if ok else SmokeStatus.FAIL,
        "reason": None if ok else "response did not contain 'pong'",
        "result": result.model_dump(mode="json"),
    }


def tool_calling(client: VultrInferenceClient) -> dict[str, Any]:
    result = client.complete(
        InferenceRequest(
            messages=[
                ChatMessage(role="system", content="Use the provided tool to do arithmetic."),
                ChatMessage(role="user", content="What is 17 + 25?"),
            ],
            tools=[ADD_NUMBERS_TOOL],
            tool_choice="required",
            max_tokens=128,
        )
    )
    report: dict[str, Any] = {"result": result.model_dump(mode="json")}
    calls = [c for c in result.tool_calls if c.name == ADD_NUMBERS_TOOL.name]
    if not calls:
        return report | {"status": SmokeStatus.FAIL, "reason": "no add_numbers tool call"}
    try:
        args = AddNumbersArgs.model_validate_json(calls[0].arguments_json)
    except ValidationError as exc:
        return report | {"status": SmokeStatus.FAIL, "reason": f"invalid arguments: {exc}"}
    ok = {args.a, args.b} == {17, 25}
    return report | {
        "status": SmokeStatus.PASS if ok else SmokeStatus.FAIL,
        "validated_arguments": args.model_dump(),
        "tool_output": args.a + args.b,
        "reason": None if ok else "arguments do not match the prompt",
    }


def tool_round_trip(client: VultrInferenceClient) -> dict[str, Any]:
    """Multi-turn: the model calls a tool, we return the result under its original id as a
    ``role=tool`` message, and the model must use it. Proves the provider accepts our
    assistant-tool-call and tool-result message shapes (C3-A), not just a single call."""
    system = ChatMessage(
        role="system",
        content="Use the add_numbers tool for arithmetic, then state the result as a number.",
    )
    user = ChatMessage(role="user", content="What is 17 + 25?")
    first = client.complete(
        InferenceRequest(
            messages=[system, user],
            tools=[ADD_NUMBERS_TOOL],
            tool_choice="required",
            max_tokens=128,
        )
    )
    report: dict[str, Any] = {"first": first.model_dump(mode="json")}
    calls = [c for c in first.tool_calls if c.name == ADD_NUMBERS_TOOL.name]
    if not calls or len(calls) != len(first.tool_calls):
        return report | {"status": SmokeStatus.FAIL, "reason": "expected only add_numbers calls"}
    try:
        parsed = [AddNumbersArgs.model_validate_json(c.arguments_json) for c in calls]
    except ValidationError as exc:
        return report | {"status": SmokeStatus.FAIL, "reason": f"invalid arguments: {exc}"}
    results = [
        ToolResultMessage(tool_call_id=c.id, content=json.dumps({"sum": a.a + a.b}))
        for c, a in zip(calls, parsed, strict=True)
    ]
    second = client.complete(
        InferenceRequest(
            messages=[
                system,
                user,
                AssistantToolCallMessage(content=first.content, tool_calls=first.tool_calls),
                *results,
            ],
            tools=[ADD_NUMBERS_TOOL],
            max_tokens=256,
        )
    )
    ok = bool(second.content and "42" in second.content)
    return report | {
        "status": SmokeStatus.PASS if ok else SmokeStatus.FAIL,
        "tool_call_ids": [c.id for c in calls],
        "second": second.model_dump(mode="json"),
        "reason": None if ok else "final answer did not use the tool result (no '42')",
    }


def list_models(client: VultrInferenceClient) -> dict[str, Any]:
    models = client.list_models()
    return {
        "status": SmokeStatus.PASS if models else SmokeStatus.FAIL,
        "models": models,
        "configured_model_listed": client.model in models,
        # Observed 2026-11-03: GET /models answers 200 with no key or a bogus key. This check
        # therefore proves the catalog is reachable, NOT that the configured key is valid.
        "verifies_credentials": False,
    }


CHECKS: dict[str, Callable[[VultrInferenceClient], dict[str, Any]]] = {
    "basic_inference": basic_inference,
    "tool_calling": tool_calling,
    "tool_round_trip": tool_round_trip,
}


def run(names: list[str], settings: Settings) -> tuple[int, dict[str, Any]]:
    report: dict[str, Any] = {
        "provider": "vultr",
        "base_url": settings.vultr_base_url,
        "requested_model": settings.vultr_model,
        "checks": {},
    }
    if not settings.vultr_configured:
        for name in names:
            report["checks"][name] = {
                "status": SmokeStatus.BLOCKED_BY_CREDENTIALS,
                "reason": "MOODY_VULTR_API_KEY not set",
            }
        return 2, report

    client = VultrInferenceClient.from_settings(settings)
    funcs = {**CHECKS, "list_models": list_models}
    for name in names:
        try:
            report["checks"][name] = funcs[name](client)
        except InferenceError as exc:
            report["checks"][name] = {
                "status": SmokeStatus.FAIL,
                "error": exc.detail.model_dump(mode="json"),
            }
    passed = all(c["status"] == SmokeStatus.PASS for c in report["checks"].values())
    return (0 if passed else 1), report


def render(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, default=str)
