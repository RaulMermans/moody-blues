"""Sandbox <-> coordinator wire protocol, version ``mb-exp/1``.

Everything here crosses the trust boundary. Inbound models (``ExperimentAction``) describe
what untrusted code may *propose*; none of them can carry SQL, shell, paths, credentials,
budgets, models or free text that reaches an LLM. Outbound models (``StepInput``) are what
the coordinator chooses to reveal.

Free text is deliberately absent from ``FaultSelection``: a fault's ``error_message`` is
delivered verbatim to the Target Agent, so a sandbox-chosen message would be a prompt
injection channel. Messages come from the trusted ``APPROVED_FAULT_MESSAGES`` table.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.scenario import FaultKind
from moody_blues.contracts.world import ToolErrorCode

PROTOCOL_VERSION = "mb-exp/1"

MAX_ACTION_BYTES = 8_192  # one sandbox action on stdout
MAX_STEP_INPUT_BYTES = 24_000  # one JSON step input (base64-embedded in the step program)
MAX_EXPERIMENT_CODE_BYTES = 16_000
MAX_SUMMARY_CHARS = 1_000
MAX_UNTRUSTED_TEXT_CHARS = 500

APPROVED_FAULT_MESSAGES: dict[ToolErrorCode, str] = {
    ToolErrorCode.TIMEOUT: (
        "Upstream CRM did not respond within 30s. The request may or may not have been applied."
    ),
    ToolErrorCode.INTERNAL_ERROR: "The CRM reported an internal error while handling the request.",
    ToolErrorCode.UNAVAILABLE: "The CRM is temporarily unavailable.",
}

ScenarioId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")]
RunRef = Annotated[str, StringConstraints(pattern=r"^trun_[0-9]{1,2}$")]


class FaultSelection(BaseModel):
    """A bounded choice among approved faults. Replaces the scenario's own fault list."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: FaultKind
    occurrence: int = Field(default=1, ge=1, le=3)
    error_code: Literal["timeout", "internal_error", "unavailable"] = "timeout"
    # stale_read only: how many consecutive reads the lag lasts.
    span: int = Field(default=1, ge=1, le=6)


class _Action(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    protocol: Literal["mb-exp/1"]


class RunTargetAgent(_Action):
    """Ask the coordinator to run the Target Agent once, in a fresh world.

    ``faults`` omitted keeps the scenario's own faults; an empty list removes them.
    """

    action: Literal["run_target_agent"]
    scenario_id: ScenarioId
    config: Literal["baseline", "hardened"]
    faults: list[FaultSelection] | None = Field(default=None, max_length=3)


class InspectionSection(StrEnum):
    TOOL_TRACE = "tool_trace"
    CLAIM = "claim"
    STATE_SUMMARY = "state_summary"


class InspectObservation(_Action):
    """Ask for more detail about an earlier run. Delivered in the next step's input."""

    action: Literal["inspect_observation"]
    run_ref: RunRef
    section: Literal["tool_trace", "claim", "state_summary"]


class ExperimentConclusion(StrEnum):
    """The experiment's own reading. Recorded as sandbox-supplied, never as a verdict."""

    BEHAVIOR_OBSERVED = "behavior_observed"
    BEHAVIOR_NOT_OBSERVED = "behavior_not_observed"
    INCONCLUSIVE = "inconclusive"


class FinishExperiment(_Action):
    action: Literal["finish_experiment"]
    conclusion: Literal["behavior_observed", "behavior_not_observed", "inconclusive"]
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)


ExperimentAction = Annotated[
    RunTargetAgent | InspectObservation | FinishExperiment, Field(discriminator="action")
]

ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {"run_target_agent", "inspect_observation", "finish_experiment"}
)


class RejectionCode(StrEnum):
    """Why a step's output was not acted on. Every one of these ends the experiment."""

    OUTPUT_EMPTY = "output_empty"
    OUTPUT_OVERSIZED = "output_oversized"
    OUTPUT_TRUNCATED = "output_truncated"
    OUTPUT_INCOMPLETE = "output_incomplete"
    INVALID_ENCODING = "invalid_encoding"
    MALFORMED_JSON = "malformed_json"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNAUTHORIZED_ACTION = "unauthorized_action"
    SCHEMA_VIOLATION = "schema_violation"
    UNSUPPORTED_SCENARIO = "unsupported_scenario"
    INVALID_FAULT = "invalid_fault"
    UNKNOWN_RUN_REF = "unknown_run_ref"
    TARGET_RUN_LIMIT = "target_run_limit"


class ProtocolRejection(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: RejectionCode
    detail: str = Field(max_length=500)


# --- outbound: what the sandbox is allowed to learn -------------------------------------------


class ToolCallObservation(BaseModel):
    """One CRM call as the agent experienced it. No arguments, ids or rows."""

    model_config = ConfigDict(frozen=True)

    seq: int
    tool: str
    ok: bool
    error_code: str | None
    # Structured facts about the call, so its shape can be read without seeing arguments.
    used_idempotency_key: bool | None = None  # create_customer only
    idempotent_replay: bool | None = None  # create_customer only, on a delivered success
    result_count: int | None = None  # search_customers only


class RunObservation(BaseModel):
    """Sanitized outcome of one target run. Verdict fields come only from the Oracle."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["target_run"] = "target_run"
    run_ref: str
    scenario_ref: str
    config: AgentConfigName
    target_kind: str
    termination: str
    run_outcome: str | None
    claim_status: str | None
    oracle_verdict: str
    objective_satisfied: bool
    invariants_violated: list[str]
    finding_codes: list[str]
    tool_calls: int
    faults_delivered: int
    tokens: int | None


class InspectionObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["inspection"] = "inspection"
    run_ref: str
    section: InspectionSection
    tool_calls: list[ToolCallObservation] | None = None
    claim_status: str | None = None
    claimed_customer_id: str | None = None
    # Written by the model under test: data to look at, never instructions to follow.
    untrusted_claim_message: str | None = Field(default=None, max_length=MAX_UNTRUSTED_TEXT_CHARS)
    new_customers: int | None = None
    objective_matching_records: int | None = None
    seed_customers: int | None = None
    # Where the claimed id points in committed state: new_record, seed_record, uncommitted, none.
    claim_points_to: str | None = None


Observation = Annotated[RunObservation | InspectionObservation, Field(discriminator="kind")]


class ApprovedCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenarios: list[str]
    configs: list[str]
    fault_kinds: list[str]
    fault_error_codes: list[str]


class StepInput(BaseModel):
    """The whole of what one sandbox step receives."""

    model_config = ConfigDict(frozen=True)

    protocol: Literal["mb-exp/1"] = PROTOCOL_VERSION
    experiment_id: str
    step: int = Field(ge=1)
    max_steps: int = Field(ge=1)
    target_runs_remaining: int = Field(ge=0)
    catalog: ApprovedCatalog
    observations: list[Observation]
