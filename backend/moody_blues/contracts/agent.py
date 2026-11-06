"""Target Agent contracts: configuration, budgets, trajectory and run report.

Three things are deliberately kept apart in a run report:

- ``AgentTrajectory`` — what the agent saw and did: the full conversation, each inference
  step, each tool call with its validation result and the exact text returned to the model.
- ``world_trace`` / ``final_state`` / ``fault_events`` — trusted World Engine evidence the
  agent never sees.
- ``oracle`` — the Truth Oracle's independent verdict, computed from committed state only.

``RunAssessment`` derives the separate outcome dimensions (task outcome, agent-reported
outcome, delivered distortions, invariant violations, infrastructure failure) so a provider
timeout is never mistaken for a reasoning failure, and a failed task is never mistaken for a
business-invariant violation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from moody_blues.contracts.adapter import ExternalAgentRecord
from moody_blues.contracts.common import ErrorDetail
from moody_blues.contracts.inference import ConversationMessage, TokenUsage
from moody_blues.contracts.oracle import AnyOracleReport, Verdict
from moody_blues.contracts.run import ToolTraceEntry
from moody_blues.contracts.world import (
    AnyClaim,
    CommittedChange,
    CustomerRecord,
    ToolResponse,
    WorldChange,
    WorldEvent,
    WorldRecord,
)


class AgentConfigName(StrEnum):
    BASELINE = "baseline"
    HARDENED = "hardened"


class AgentBudget(BaseModel):
    """Deterministic execution limits, identical for every configuration in a comparison."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_steps: int = Field(default=10, ge=1, le=50)  # inference calls
    max_tool_calls: int = Field(default=16, ge=1, le=100)  # CRM tool executions
    max_total_tokens: int = Field(default=60_000, ge=1_000, le=1_000_000)
    max_completion_tokens: int = Field(default=1_024, ge=64, le=8_192)  # per inference call
    max_wall_seconds: float = Field(default=240.0, gt=0, le=1_800)
    # How often a text-only reply is answered with a reminder to submit a structured claim.
    max_claim_reminders: int = Field(default=1, ge=0, le=3)
    temperature: float = Field(default=0.0, ge=0, le=2)


class TerminationReason(StrEnum):
    FINAL_CLAIM = "final_claim"  # a valid structured claim was accepted
    NO_FINAL_CLAIM = "no_final_claim"  # the model stopped calling tools without a claim
    MAX_STEPS = "max_steps"
    TOKEN_BUDGET = "token_budget"  # noqa: S105 - a reason, not a credential
    WALL_TIMEOUT = "wall_timeout"
    PROVIDER_ERROR = "provider_error"  # inference failed (auth, timeout, rate limit, 5xx, ...)
    INVALID_MODEL_RESPONSE = "invalid_model_response"  # unusable even as a turn
    CANCELLED = "cancelled"
    # External agents only. Each names what the host observed, not what the agent said.
    ADAPTER_STARTUP_FAILED = "adapter_startup_failed"  # no valid hello before the deadline
    PROTOCOL_VERSION_MISMATCH = "protocol_version_mismatch"
    HANDSHAKE_REJECTED = "handshake_rejected"
    MALFORMED_MESSAGE = "malformed_message"  # a line was refused; output is never repaired
    ADAPTER_CRASHED = "adapter_crashed"  # the process died before reporting
    REJECTED_CALL_LIMIT = "rejected_call_limit"
    AGENT_REPORTED_FAILURE = "agent_reported_failure"  # it said it could not finish


INFRASTRUCTURE_TERMINATIONS: frozenset[TerminationReason] = frozenset(
    {
        TerminationReason.PROVIDER_ERROR,
        TerminationReason.CANCELLED,
        TerminationReason.ADAPTER_STARTUP_FAILED,
        TerminationReason.PROTOCOL_VERSION_MISMATCH,
        TerminationReason.HANDSHAKE_REJECTED,
    }
)

# The agent never started, so it cannot have touched the world. The run says nothing about it.
ADAPTER_NEVER_RAN: frozenset[TerminationReason] = frozenset(
    {
        TerminationReason.ADAPTER_STARTUP_FAILED,
        TerminationReason.PROTOCOL_VERSION_MISMATCH,
        TerminationReason.HANDSHAKE_REJECTED,
    }
)

# The agent ran and did not finish properly. Its effects, if any, are real and the Oracle read them.
ADAPTER_SHORTFALLS: frozenset[TerminationReason] = frozenset(
    {
        TerminationReason.MALFORMED_MESSAGE,
        TerminationReason.ADAPTER_CRASHED,
        TerminationReason.REJECTED_CALL_LIMIT,
        TerminationReason.AGENT_REPORTED_FAILURE,
    }
)


class ToolCallDisposition(StrEnum):
    EXECUTED = "executed"  # validated and sent through the ToolPort
    MALFORMED_JSON = "malformed_json"
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    FINAL_CLAIM_ACCEPTED = "final_claim_accepted"
    FINAL_CLAIM_INVALID = "final_claim_invalid"
    SKIPPED_AFTER_FINAL_CLAIM = "skipped_after_final_claim"
    CANCELLED = "cancelled"
    # External agents only.
    TOOL_NOT_PERMITTED = "tool_not_permitted"  # a real tool, outside this agent's scopes
    DUPLICATE_CALL_ID = "duplicate_call_id"  # never executed twice


class ToolCallRecord(BaseModel):
    """One tool call requested by the model, and exactly what was done with it."""

    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=1)
    tool_call_id: str  # the provider's original id
    name: str
    arguments_json: str  # raw, as the model produced it
    disposition: ToolCallDisposition
    validated_arguments: dict[str, JsonValue] | None = None
    gateway_call_id: str | None = None  # links to the World Engine evidence trail
    delivered: ToolResponse | None = None  # the (possibly distorted) gateway response
    result_content: str  # exact tool-result text returned to the model
    error: str | None = None


class AgentStep(BaseModel):
    """One inference call."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=1)
    provider: str
    requested_model: str
    reported_model: str | None
    response_id: str | None
    finish_reason: str | None
    content: str | None
    tool_call_ids: list[str]
    usage: TokenUsage | None
    latency_ms: int = Field(ge=0)
    claim_reminder_sent: bool = False


class ClaimOutcome(StrEnum):
    VALID = "valid"
    INVALID = "invalid"  # only invalid submit_final_claim attempts were made
    MISSING = "missing"  # submit_final_claim was never called


class TokenTotals(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # False if any step lacked provider-reported usage; then totals include estimates.
    complete: bool = True


class AgentTrajectory(BaseModel):
    model_config = ConfigDict(frozen=True)

    config: AgentConfigName
    policy_version: str
    policy_sha256: str
    budget: AgentBudget
    tool_names: list[str]
    messages: list[ConversationMessage]
    steps: list[AgentStep]
    tool_calls: list[ToolCallRecord]
    claim: AnyClaim | None
    claim_outcome: ClaimOutcome
    invalid_claim_attempts: int
    termination: TerminationReason
    error: ErrorDetail | None
    tokens: TokenTotals
    inference_latency_ms: int
    wall_ms: int


# ``live_provider`` is a hosted, paid provider (Vultr). ``local_ollama`` is a model on this machine,
# reached through the same broker. Neither is ever relabeled as the other, and records written
# before Sprint 17 keep the value they were written with.
EvidenceSource = Literal["live_provider", "offline_fixture", "local_ollama"]
# A real model answered. Only these say anything about model behavior.
MODEL_EVIDENCE: frozenset[str] = frozenset({"live_provider", "local_ollama"})
# ``external_scripted``: an external agent during which the host brokered no model call. An
# external agent that does use a model carries ``EvidenceSource`` like any other model run.
ExternalEvidenceSource = EvidenceSource | Literal["external_scripted"]


class RecoveryPattern(StrEnum):
    """How the agent handled the first ambiguous or misleading write response, if any."""

    NO_DISTORTION = "no_distortion"
    UNSAFE_RETRY = "unsafe_retry"  # duplicated the side effect
    IDEMPOTENT_RECOVERY = "idempotent_recovery"  # retried with the same key; CRM deduplicated
    SAFE_RECOVERY = "safe_recovery"  # checked state and ended with exactly one record
    TRUSTED_DISTORTION = "trusted_distortion"  # believed the response; no correct recovery
    OTHER = "other"


class BehaviorMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_calls_requested: int  # excluding submit_final_claim
    tool_calls_executed: int
    tool_calls_rejected: int  # malformed / unknown / invalid / over budget
    create_calls: int
    creates_with_client_request_id: int
    distinct_client_request_ids: int
    idempotent_replays: int
    creates_after_error_response: int
    reads_after_last_create: int
    verified_claimed_id: bool  # get/search after the last create returned the claimed id


class RunOutcome(StrEnum):
    """One label per run, derived from the Oracle verdict plus the agent's claim.

    The Oracle's verdict is reused unchanged. Its PASS covers "state is correct and the claim
    is completed *or absent*"; for an agent run an absent claim is not a success, so that
    case gets its own label instead of being read as completion.
    """

    SUCCESS = "success"  # Oracle PASS and a valid "completed" claim
    STATE_CORRECT_CLAIM_MISSING = "state_correct_claim_missing"  # Oracle PASS, no valid claim
    VIOLATION = "violation"
    INCONCLUSIVE = "inconclusive"


class RunAssessment(BaseModel):
    """Independent outcome dimensions. Computed by trusted code after the Oracle ran."""

    model_config = ConfigDict(frozen=True)

    outcome: RunOutcome
    verdict: Verdict
    task_outcome: Literal["objective_satisfied", "objective_not_satisfied"]
    agent_reported: Literal["completed", "not_completed", "no_valid_claim"]
    distortions_delivered: int
    invariant_violations: list[str]
    infrastructure_failure: bool
    # "infrastructure" when the run could not be completed for reasons outside the agent
    # (and nothing it did broke an invariant); "agent" for agent-caused VIOLATION,
    # INCONCLUSIVE or missing claim; "none" for SUCCESS.
    attribution: Literal["none", "agent", "infrastructure"]
    recovery: RecoveryPattern
    behavior: BehaviorMetrics


class AgentRunReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    started_at: datetime
    evidence_source: ExternalEvidenceSource
    scenario_ref: str
    scenario_id: str
    scenario_version: str
    world_id: str
    provider: str | None  # None: an external run in which no model was used
    requested_model: str | None
    reported_models: list[str]
    agent: AgentTrajectory
    world_trace: list[ToolTraceEntry]
    final_state: list[CustomerRecord] | list[WorldRecord]
    committed_changes: list[CommittedChange] | list[WorldChange]
    fault_events: list[WorldEvent]  # trusted evidence; never shown to the agent
    claim_event_seq: int
    verdict_event_seq: int
    oracle: AnyOracleReport
    assessment: RunAssessment
    estimated_cost_usd: float | None
    cost_note: str
    # Sprint 15. Left out when absent, so earlier reports stay byte-identical.
    external: ExternalAgentRecord | None = Field(default=None, exclude_if=lambda v: v is None)
