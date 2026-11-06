"""Parse one line from an external agent. A pure function; nothing here has effects.

Anything short of one complete, well-formed, versioned message is an ``AdapterRejection``. Lines
are never repaired, trimmed or partly accepted. Details name fields, never values: pydantic's
messages can echo what the agent sent.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import TypeAdapter, ValidationError

from moody_blues.contracts.adapter import (
    ALLOWED_MESSAGES,
    SUPPORTED_PROTOCOLS,
    AdapterRejection,
    AdapterRejectionCode,
    AgentMessage,
    FinalMessage,
    HelloMessage,
    ModelCallMessage,
    ToolCallMessage,
)
from moody_blues.experiments.protocol import strict_loads

_ADAPTER: TypeAdapter[HelloMessage | ToolCallMessage | ModelCallMessage | FinalMessage] = (
    TypeAdapter(AgentMessage)
)


def _reject(code: AdapterRejectionCode, detail: str) -> AdapterRejection:
    return AdapterRejection(code=code, detail=detail[:300])


def parse_line(
    line: bytes,
) -> HelloMessage | ToolCallMessage | ModelCallMessage | FinalMessage | AdapterRejection:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return _reject(AdapterRejectionCode.INVALID_ENCODING, "the line is not valid UTF-8")
    try:
        document = strict_loads(text)
    except (ValueError, RecursionError):
        return _reject(AdapterRejectionCode.MALFORMED_JSON, "the line is not one JSON document")
    if not isinstance(document, dict):
        return _reject(AdapterRejectionCode.MALFORMED_JSON, "a message must be a JSON object")
    fields = cast(dict[str, Any], document)
    if fields.get("protocol") not in SUPPORTED_PROTOCOLS:
        return _reject(
            AdapterRejectionCode.UNSUPPORTED_PROTOCOL,
            f"supported: {', '.join(SUPPORTED_PROTOCOLS)}",
        )
    kind = fields.get("type")
    if not isinstance(kind, str) or kind not in ALLOWED_MESSAGES:
        return _reject(AdapterRejectionCode.UNKNOWN_MESSAGE, "type is not on the allowlist")
    try:
        # JSON mode: strict models accept enum values as strings, and nothing else.
        return _ADAPTER.validate_json(text)
    except ValidationError as exc:
        bad = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        return _reject(AdapterRejectionCode.SCHEMA_VIOLATION, f"invalid fields: {', '.join(bad)}")
