"""Truth Oracle output contract."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from moody_blues.contracts.scenario import InvariantName
from moody_blues.contracts.world import ClaimStatus, FinalClaim, WorldClaim


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

    @property
    def record_ids(self) -> list[str]:
        return self.customer_ids


class ResponseDivergence(BaseModel):
    """A delivered write response that disagrees with what that call actually committed."""

    model_config = ConfigDict(frozen=True)

    call_seq: int
    call_id: str
    reported_ok: bool
    reported_customer_id: str | None
    committed_customer_id: str | None

    @property
    def committed_record_id(self) -> str | None:
        return self.committed_customer_id


class StateObservation(BaseModel):
    """What the Oracle read from authoritative state (read-only)."""

    model_config = ConfigDict(frozen=True)

    total_customers: int
    seed_customer_ids: list[str]
    new_customer_ids: list[str]
    objective_matching_ids: list[str]

    @property
    def seed_ids(self) -> list[str]:
        return self.seed_customer_ids

    @property
    def new_ids(self) -> list[str]:
        return self.new_customer_ids


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


# --- worlds without customers -----------------------------------------------------------------
#
# The verdict, the severities and most finding codes are already world-neutral. The CRM report's
# field names are not, and they serialize into every bundle ever written, so they cannot change.
# These siblings carry the same meaning under neutral names. ``extra="forbid"`` keeps the two
# apart when a stored report is read back: neither parses as the other.


class WorldFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # A ``FindingCode`` value where the meaning is the same, otherwise a code the world defines.
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    severity: Severity
    invariant: str | None
    message: str
    record_ids: list[str] = Field(default_factory=list[str])
    call_seqs: list[int] = Field(default_factory=list[int])


class WorldDivergence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    call_seq: int
    call_id: str
    reported_ok: bool
    reported_record_id: str | None
    committed_record_id: str | None


class WorldStateObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_records: int
    seed_record_ids: list[str]
    new_record_ids: list[str]
    objective_matching_ids: list[str]

    @property
    def seed_ids(self) -> list[str]:
        return self.seed_record_ids

    @property
    def new_ids(self) -> list[str]:
        return self.new_record_ids


class WorldOracleReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    world_type: str
    plugin_version: str
    world_id: str
    scenario_ref: str
    verdict: Verdict
    objective_satisfied: bool
    invariants_evaluated: list[str]
    invariants_violated: list[str]
    findings: list[WorldFinding]
    observation: WorldStateObservation
    response_divergences: list[WorldDivergence]
    claim: WorldClaim | None


AnyOracleReport = OracleReport | WorldOracleReport


def derive_verdict(
    *, violated: bool, objective_satisfied: bool, claim: FinalClaim | WorldClaim | None
) -> Verdict:
    """The meaning of a verdict, in every world. Worlds decide what happened, never this."""
    if violated:
        return Verdict.VIOLATION
    if objective_satisfied and (claim is None or claim.status is ClaimStatus.COMPLETED):
        return Verdict.PASS
    return Verdict.INCONCLUSIVE
