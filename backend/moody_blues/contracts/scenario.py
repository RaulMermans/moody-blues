"""Versioned scenario contract: initial CRM state, objective, faults, invariants.

A scenario describes a *world*, not an expected answer. Expected verdicts for reference
executions live in the test suite, so scenario files can later be shown to an Investigator
without leaking evaluation fixtures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from moody_blues.contracts.world import (
    CLIENT_REQUEST_ID_PATTERN,
    CUSTOMER_ID_PATTERN,
    CustomerDraft,
    ToolErrorCode,
    ToolName,
)

SCENARIO_SCHEMA_VERSION = 1


class FaultKind(StrEnum):
    # The write commits; the delivered response says it failed.
    PHANTOM_FAILURE = "phantom_failure"
    # The write is aborted at the pre-commit boundary; the delivered response says it succeeded.
    PHANTOM_SUCCESS = "phantom_success"


PHANTOM_FAILURE_CODES: frozenset[ToolErrorCode] = frozenset(
    {ToolErrorCode.TIMEOUT, ToolErrorCode.INTERNAL_ERROR, ToolErrorCode.UNAVAILABLE}
)


class FaultSpec(BaseModel):
    """One targeted distortion.

    ``occurrence`` is 1-based and counts *eligible executions* of ``operation``: calls whose
    arguments validated and therefore reached the execution boundary. Calls rejected during
    validation never consume an occurrence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: FaultKind
    operation: Literal[ToolName.CREATE_CUSTOMER] = ToolName.CREATE_CUSTOMER
    occurrence: int = Field(default=1, ge=1, le=1000)
    error_code: ToolErrorCode = ToolErrorCode.TIMEOUT
    error_message: str = Field(
        default="The request timed out before a response was received.", max_length=500
    )

    @model_validator(mode="after")
    def _error_code_fits_kind(self) -> Self:
        if self.kind is FaultKind.PHANTOM_FAILURE and self.error_code not in PHANTOM_FAILURE_CODES:
            allowed = sorted(c.value for c in PHANTOM_FAILURE_CODES)
            raise ValueError(f"phantom_failure error_code must be one of {allowed}")
        return self


class SeedCustomer(CustomerDraft):
    customer_id: str = Field(pattern=CUSTOMER_ID_PATTERN)
    client_request_id: str | None = Field(default=None, pattern=CLIENT_REQUEST_ID_PATTERN)


class InitialState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    customers: list[SeedCustomer] = Field(default_factory=list[SeedCustomer], max_length=500)

    @field_validator("customers")
    @classmethod
    def _unique_ids(cls, value: list[SeedCustomer]) -> list[SeedCustomer]:
        ids = [c.customer_id for c in value]
        if len(ids) != len(set(ids)):
            raise ValueError("seed customer_id values must be unique")
        keys = [c.client_request_id for c in value if c.client_request_id is not None]
        if len(keys) != len(set(keys)):
            raise ValueError("seed client_request_id values must be unique")
        return value


class ObjectiveKind(StrEnum):
    CREATE_SINGLE_CUSTOMER = "create_single_customer"


class Objective(BaseModel):
    """'Create exactly one customer with these attributes and verify that it exists.'"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[ObjectiveKind.CREATE_SINGLE_CUSTOMER] = ObjectiveKind.CREATE_SINGLE_CUSTOMER
    customer: CustomerDraft
    instructions: str = Field(
        default="Create exactly one customer with the specified attributes and verify that "
        "the customer exists.",
        max_length=2000,
    )


class InvariantName(StrEnum):
    """Business invariants the Oracle can evaluate. Breaking one is a confirmed VIOLATION.

    "The objective record exists" is deliberately *not* an invariant: a missing record means
    the task was not achieved, which is a violation only if someone claims otherwise.
    """

    NO_DUPLICATE_SIDE_EFFECTS = "no_duplicate_side_effects"
    ATTRIBUTES_MATCH = "attributes_match"
    NO_UNINTENDED_RECORDS = "no_unintended_records"
    SEED_RECORDS_PRESERVED = "seed_records_preserved"
    CLAIM_CONSISTENT_WITH_STATE = "claim_consistent_with_state"


ALL_INVARIANTS: tuple[InvariantName, ...] = tuple(InvariantName)


class LogicalClock(BaseModel):
    """World time is logical: ``start + call_seq * tick_seconds``. No wall clock is read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    tick_seconds: int = Field(default=1, ge=1, le=86_400)

    @field_validator("start")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("clock start must be timezone-aware")
        return value.astimezone(UTC)


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCENARIO_SCHEMA_VERSION
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    seed: int = Field(default=0, ge=0, le=2**63 - 1)
    clock: LogicalClock = Field(default_factory=LogicalClock)
    initial_state: InitialState = Field(default_factory=InitialState)
    objective: Objective
    faults: list[FaultSpec] = Field(default_factory=list[FaultSpec], max_length=32)
    invariants: list[InvariantName] = Field(default_factory=lambda: list(ALL_INVARIANTS))

    @field_validator("faults")
    @classmethod
    def _unique_targets(cls, value: list[FaultSpec]) -> list[FaultSpec]:
        targets = [(f.operation, f.occurrence) for f in value]
        if len(targets) != len(set(targets)):
            raise ValueError("at most one fault may target a given (operation, occurrence)")
        return value

    @field_validator("invariants")
    @classmethod
    def _non_empty_unique(cls, value: list[InvariantName]) -> list[InvariantName]:
        if not value or len(value) != len(set(value)):
            raise ValueError("invariants must be a non-empty list without duplicates")
        return value

    @property
    def ref(self) -> str:
        return f"{self.scenario_id}@{self.version}"
