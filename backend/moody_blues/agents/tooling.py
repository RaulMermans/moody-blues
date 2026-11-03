"""Deterministic tool validation between the model and the ``ToolPort``.

Every tool call the model requests is classified before anything executes:

1. the name must be on the allowlist (the three CRM tools plus ``submit_final_claim``);
2. the arguments must be a JSON object (an empty string counts as ``{}``);
3. the object must validate against the tool's Pydantic model (the same models the gateway
   uses, so the two layers cannot disagree).

Only calls that pass all three reach the gateway. Failures become explicit, bounded error
results returned to the model under the original tool-call id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, JsonValue, ValidationError

from moody_blues.contracts.agent import ToolCallDisposition
from moody_blues.contracts.inference import ToolCall, ToolSpec
from moody_blues.contracts.world import FinalClaim, ToolName
from moody_blues.world.gateway import ARG_MODELS, tool_specs

FINAL_CLAIM_TOOL = "submit_final_claim"
CRM_TOOLS: frozenset[str] = frozenset(t.value for t in ToolName)
ALLOWED_TOOLS: frozenset[str] = CRM_TOOLS | {FINAL_CLAIM_TOOL}
MAX_ARGUMENTS_CHARS = 8_000
MAX_ERROR_CHARS = 500

_FINAL_CLAIM_SPEC = ToolSpec(
    name=FINAL_CLAIM_TOOL,
    description=(
        "Submit your final report for this task. Call it exactly once, when you are done. "
        "This ends the task."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["completed", "not_completed"],
                "description": "Whether the task was accomplished.",
            },
            "customer_id": {
                "type": "string",
                "description": "The customer_id of the customer you created, if any.",
            },
            "message": {
                "type": "string",
                "description": "A short explanation of what happened.",
            },
        },
        "required": ["status"],
        "additionalProperties": False,
    },
)


def agent_tool_specs() -> list[ToolSpec]:
    """The tools offered to the model, in a fixed order. Same for every configuration."""
    crm = [
        ToolSpec(name=s.name.value, description=s.description, parameters=s.parameters)
        for s in tool_specs()
    ]
    return [*crm, _FINAL_CLAIM_SPEC]


@dataclass(frozen=True, slots=True)
class ValidatedCall:
    """Outcome of validating one tool call. ``arguments`` is set only when valid."""

    disposition: ToolCallDisposition | None  # None: valid, ready to execute
    arguments: dict[str, JsonValue] | None = None
    claim: FinalClaim | None = None
    error: str | None = None


def _bounded(text: str) -> str:
    return text if len(text) <= MAX_ERROR_CHARS else text[: MAX_ERROR_CHARS - 1] + "…"


def _validation_message(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()]
    return _bounded("; ".join(parts))


def _parse_object(arguments_json: str) -> tuple[dict[str, JsonValue] | None, str | None, bool]:
    """Returns (object, error, malformed). ``malformed`` distinguishes bad JSON from a
    well-formed non-object."""
    if len(arguments_json) > MAX_ARGUMENTS_CHARS:
        return None, f"arguments exceed {MAX_ARGUMENTS_CHARS} characters", False
    if not arguments_json.strip():
        return {}, None, False
    try:
        value: Any = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        return None, _bounded(f"arguments are not valid JSON: {exc.msg} at char {exc.pos}"), True
    if not isinstance(value, dict):
        return None, "arguments must be a JSON object", False
    return cast(dict[str, JsonValue], value), None, False


def validate_call(call: ToolCall) -> ValidatedCall:
    if call.name not in ALLOWED_TOOLS:
        allowed = ", ".join(sorted(ALLOWED_TOOLS))
        return ValidatedCall(
            ToolCallDisposition.UNKNOWN_TOOL,
            error=_bounded(f"unknown tool {call.name!r}; allowed tools: {allowed}"),
        )
    obj, error, malformed = _parse_object(call.arguments_json)
    if obj is None:
        if call.name == FINAL_CLAIM_TOOL:
            return ValidatedCall(ToolCallDisposition.FINAL_CLAIM_INVALID, error=error)
        disposition = (
            ToolCallDisposition.MALFORMED_JSON
            if malformed
            else ToolCallDisposition.INVALID_ARGUMENTS
        )
        return ValidatedCall(disposition, error=error)

    if call.name == FINAL_CLAIM_TOOL:
        cid = obj.get("customer_id")
        if isinstance(cid, str) and not cid.strip():
            obj = {k: v for k, v in obj.items() if k != "customer_id"}  # "" is not an id
        try:
            claim = FinalClaim.model_validate(obj)
        except ValidationError as exc:
            return ValidatedCall(
                ToolCallDisposition.FINAL_CLAIM_INVALID, error=_validation_message(exc)
            )
        return ValidatedCall(
            ToolCallDisposition.FINAL_CLAIM_ACCEPTED,
            arguments=cast(dict[str, JsonValue], claim.model_dump(mode="json")),
            claim=claim,
        )

    model: type[BaseModel] = ARG_MODELS[ToolName(call.name)]
    try:
        model.model_validate(obj)
    except ValidationError as exc:
        return ValidatedCall(ToolCallDisposition.INVALID_ARGUMENTS, error=_validation_message(exc))
    # The raw object is what is sent: the gateway re-validates and normalizes it, and its
    # evidence trail then records exactly what the model asked for.
    return ValidatedCall(None, arguments=obj)


def error_result(code: str, message: str) -> str:
    """Tool-result text for a call rejected or not executed by the agent runtime."""
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": _bounded(message)}},
        separators=(",", ":"),
    )
