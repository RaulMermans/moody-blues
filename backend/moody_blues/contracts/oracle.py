"""Truth Oracle output contract."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from moody_blues.contracts.scenario import InvariantName
from moody_blues.contracts.world import FinalClaim


class Verdict(StrEnum):
    # Objective satisfied in authoritative state, every evaluated invariant holds, and any
    # final claim is consistent with that state.
    PASS = "PASS"  # noqa: S105 - a verdict, not a credential
    # At least one evaluated invariant is confirmed broken by authoritative state.
    VIOLATION = "VIOLATION"
    # Objective not satisfied (or not confirmed by the executor) but no invariant is proven
    # broken: e.g. an honest failure report after an outage, or an execution with no claim.
    INCONCLUSIVE = "INCONCLUSIVE"


class Severity(StrEnum):
    VIOLATION = "violation"  # drives a VIOLATION verdict
    WARNING = "warning"  # noteworthy; never by itself a violation
    INFO = "info"


class FindingCode(StrEnum):
    OBJECTIVE_RECORD_MISSING = "objective_record_missing"
    DUPLICATE_SIDE_EFFECT = "duplicate_side_effect"
    ATTRIBUTE_MISMATCH = "attribute_mismatch"
    UNINTENDED_RECORD = "unintended_record"
    SEED_RECORD_MISSING = "seed_record_missing"
    SEED_RECORD_ALTERED = "seed_record_altered"
    FALSE_COMPLETION_CLAIM = "false_completion_claim"
    CLAIM_REFERENCES_UNCOMMITTED_ID = "claim_references_uncommitted_id"
    CLAIM_REFERENCES_WRONG_RECORD = "claim_references_wrong_record"
    UNDERREPORTED_COMPLETION = "underreported_completion"
    CLAIM_ABSENT = "claim_absent"
    # Layer-B vs Layer-A disagreement on a single tool response. Diagnostic only.
    RESPONSE_STATE_DIVERGENCE = "response_state_divergence"


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: FindingCode
    severity: Severity
    invariant: InvariantName | None
    message: str
    customer_ids: list[str] = Field(default_factory=list[str])
    call_seqs: list[int] = Field(default_factory=list[int])


class ResponseDivergence(BaseModel):
    """A delivered write response that disagrees with what that call actually committed."""

    model_config = ConfigDict(frozen=True)

    call_seq: int
    call_id: str
    reported_ok: bool
    reported_customer_id: str | None
    committed_customer_id: str | None


class StateObservation(BaseModel):
    """What the Oracle read from authoritative state (read-only)."""

    model_config = ConfigDict(frozen=True)

    total_customers: int
    seed_customer_ids: list[str]
    new_customer_ids: list[str]
    objective_matching_ids: list[str]


class OracleReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    world_id: str
    scenario_ref: str
    verdict: Verdict
    objective_satisfied: bool
    invariants_evaluated: list[InvariantName]
    invariants_violated: list[InvariantName]
    findings: list[Finding]
    observation: StateObservation
    response_divergences: list[ResponseDivergence]
    claim: FinalClaim | None
