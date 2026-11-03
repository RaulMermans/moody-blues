"""World Engine contracts: CRM records, agent-facing tool calls/responses, final claims.

Three layers are kept distinct (see docs/architecture/world-engine.md):

- **Actual world** — ``CustomerRecord`` rows persisted in the world's SQLite file.
- **Agent-perceived world** — ``ToolResponse`` objects delivered through the gateway. These may
  be deliberately distorted by a configured fault and are *never* proof of committed state.
- **Verified truth** — produced by the Truth Oracle (``contracts/oracle.py``).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_METADATA_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

CUSTOMER_ID_PATTERN = r"^cus_[a-z0-9_]{4,40}$"
CLIENT_REQUEST_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


def normalize_name(value: str) -> str:
    """Collapse internal whitespace and strip. Names are case-preserving."""
    collapsed = " ".join(value.split())
    if not collapsed:
        raise ValueError("name must not be blank")
    if len(collapsed) > 120:
        raise ValueError("name must be at most 120 characters")
    if _CONTROL_RE.search(collapsed):
        raise ValueError("name must not contain control characters")
    return collapsed


def normalize_email(value: str) -> str:
    """Emails are compared case-insensitively, so they are stored lower-cased."""
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise ValueError("email must look like local@domain.tld (max 254 chars)")
    return email


def _check_metadata(value: dict[str, str]) -> dict[str, str]:
    if len(value) > 16:
        raise ValueError("metadata may contain at most 16 keys")
    for key, item in value.items():
        if not _METADATA_KEY_RE.fullmatch(key):
            raise ValueError(f"metadata key {key!r} must match {_METADATA_KEY_RE.pattern}")
        if len(item) > 200 or _CONTROL_RE.search(item):
            raise ValueError(f"metadata value for {key!r} is too long or has control chars")
    return dict(sorted(value.items()))


CustomerName = Annotated[str, AfterValidator(normalize_name)]
CustomerEmail = Annotated[str, AfterValidator(normalize_email)]
CustomerMetadata = Annotated[dict[str, str], AfterValidator(_check_metadata)]


class CustomerDraft(BaseModel):
    """Attributes of a customer to be created. Normalization happens here, once."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: CustomerName
    email: CustomerEmail
    metadata: CustomerMetadata = Field(default_factory=dict[str, str])


class CustomerRecord(BaseModel):
    """A committed customer as stored in authoritative state."""

    model_config = ConfigDict(frozen=True)

    customer_id: str = Field(pattern=CUSTOMER_ID_PATTERN)
    name: str
    email: str
    metadata: dict[str, str]
    client_request_id: str | None
    created_at: datetime
    # The gateway call (``call_seq``) whose transaction inserted this row; 0 for seed data.
    created_by_call: int = Field(ge=0)


# --- agent-facing tools -----------------------------------------------------------------------


class ToolName(StrEnum):
    CREATE_CUSTOMER = "create_customer"
    GET_CUSTOMER = "get_customer"
    SEARCH_CUSTOMERS = "search_customers"


WRITE_TOOLS: frozenset[ToolName] = frozenset({ToolName.CREATE_CUSTOMER})


class CreateCustomerArgs(CustomerDraft):
    client_request_id: str | None = Field(default=None, pattern=CLIENT_REQUEST_ID_PATTERN)


class GetCustomerArgs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    customer_id: str = Field(min_length=1, max_length=64)


class SearchCustomersArgs(BaseModel):
    """All filters optional; no filters lists customers. Results ordered by creation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    email: str | None = Field(default=None, min_length=1, max_length=254)
    name_contains: str | None = Field(default=None, min_length=1, max_length=120)
    limit: int = Field(default=20, ge=1, le=100)


class ToolErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    UNKNOWN_TOOL = "unknown_tool"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"
    UNAVAILABLE = "unavailable"


class ToolError(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ToolErrorCode
    message: str
    retryable: bool = False


class ToolResponse(BaseModel):
    """Exactly what the agent observes. May be distorted; never evidence of committed state."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    tool: str
    ok: bool
    data: dict[str, JsonValue] | None = None
    error: ToolError | None = None


class ToolSpec(BaseModel):
    """Provider-neutral description of an agent tool (name, purpose, JSON Schema)."""

    model_config = ConfigDict(frozen=True)

    name: ToolName
    description: str
    parameters: dict[str, Any]


# --- final claims -----------------------------------------------------------------------------


class ClaimStatus(StrEnum):
    COMPLETED = "completed"
    NOT_COMPLETED = "not_completed"


class FinalClaim(BaseModel):
    """What the executor (later: the target agent) asserts at the end. Evidence, not truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ClaimStatus
    customer_id: str | None = Field(default=None, max_length=64)
    message: str = Field(default="", max_length=2000)


# --- evidence ---------------------------------------------------------------------------------


class EventKind(StrEnum):
    WORLD_INITIALIZED = "world_initialized"
    TOOL_CALL_REQUESTED = "tool_call_requested"
    OPERATION_EXECUTED = "operation_executed"
    FAULT_INJECTED = "fault_injected"
    TOOL_RESPONSE_DELIVERED = "tool_response_delivered"
    FINAL_CLAIM = "final_claim"
    ORACLE_VERDICT = "oracle_verdict"


class WorldEvent(BaseModel):
    """One entry in a world's append-only evidence trail, in causal (``seq``) order."""

    model_config = ConfigDict(frozen=True)

    seq: int = Field(ge=1)
    world_id: str
    kind: EventKind
    call_seq: int | None
    logical_time: datetime
    payload: dict[str, JsonValue]


class CommittedChange(BaseModel):
    """A row from the trigger-maintained journal: written in the *same* transaction as the
    state change, so it exists if and only if the change committed."""

    model_config = ConfigDict(frozen=True)

    change_seq: int = Field(ge=1)
    operation: str
    customer_id: str
    created_by_call: int
