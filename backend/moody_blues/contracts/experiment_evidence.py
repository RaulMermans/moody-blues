"""Evidence schema for one experiment.

Five layers are kept apart on purpose, because each has a different author and trust level:

=================  ==========================================  ==============================
Layer              Field                                       Author
=================  ==========================================  ==============================
requested          ``StepRecord.proposed_*``                   untrusted experiment code
authorized         ``StepRecord.decision`` and                 trusted coordinator
                   ``TargetRunEvidence.authorized``
target_observed    ``TargetRunEvidence.target_observed``       gateway (may be distorted)
committed          ``TargetRunEvidence.committed``             authoritative SQLite state
oracle             ``TargetRunEvidence.oracle``                Truth Oracle
=================  ==========================================  ==============================

``sandbox_supplied`` holds the experiment's closing remarks. Nothing reads it back into a
verdict, a status or a classification.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from moody_blues.contracts.agent import AgentConfigName, TokenTotals
from moody_blues.contracts.common import ErrorDetail, ExecutionStatus
from moody_blues.contracts.oracle import OracleReport
from moody_blues.contracts.protocol import ExperimentConclusion, ProtocolRejection
from moody_blues.contracts.run import ToolTraceEntry
from moody_blues.contracts.scenario import FaultSpec
from moody_blues.contracts.world import CommittedChange, CustomerRecord, FinalClaim

EVIDENCE_SCHEMA_VERSION = 1


class ExperimentAuthorship(StrEnum):
    # Sprint 4 experiments are written by developers. They are not autonomous discoveries.
    DEVELOPER_SCRIPT = "developer_script"


class ExperimentState(StrEnum):
    CREATED = "created"
    SANDBOX_RUNNING = "sandbox_running"
    VALIDATING = "validating"
    TARGET_RUNNING = "target_running"
    FINALIZING = "finalizing"
    # Terminal
    COMPLETED = "completed"  # ended by a valid finish action
    REJECTED = "rejected"  # experiment output refused
    FAILED = "failed"  # infrastructure could not complete it
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    # A step with possible world effects did not finish cleanly. Never retried automatically.
    UNCERTAIN = "uncertain"


TERMINAL_STATES: frozenset[ExperimentState] = frozenset(
    {
        ExperimentState.COMPLETED,
        ExperimentState.REJECTED,
        ExperimentState.FAILED,
        ExperimentState.CANCELLED,
        ExperimentState.BUDGET_EXHAUSTED,
        ExperimentState.UNCERTAIN,
    }
)


class ExperimentTermination(StrEnum):
    FINISH_ACTION = "finish_action"
    ACTION_REJECTED = "action_rejected"
    MAX_STEPS = "max_steps"
    MAX_RUNTIME = "max_runtime"
    SANDBOX_TIMEOUT = "sandbox_timeout"
    SANDBOX_OOM = "sandbox_oom"
    SANDBOX_EXIT_NONZERO = "sandbox_exit_nonzero"
    SANDBOX_INFRASTRUCTURE = "sandbox_infrastructure"
    SANDBOX_CLEANUP_FAILED = "sandbox_cleanup_failed"
    PROVIDER_ERROR = "provider_error"
    TARGET_FAILED = "target_failed"
    CANCELLED = "cancelled"
    SPEND_LIMIT = "spend_limit"
    COORDINATOR_ERROR = "coordinator_error"
    COORDINATOR_INTERRUPTED = "coordinator_interrupted"


class OutcomeClass(StrEnum):
    """Why an experiment looks the way it does. Several can apply at once.

    An expected fault or an Oracle violation is a *finding*: the experiment did its job. The
    rest say the run itself was impaired, so its findings need care.
    """

    PROVIDER_FAILURE = "provider_failure"
    EXPERIMENT_VALIDATION_FAILURE = "experiment_validation_failure"
    SANDBOX_FAILURE = "sandbox_failure"
    COORDINATOR_FAILURE = "coordinator_failure"
    TARGET_AGENT_FAILURE = "target_agent_failure"
    EXPECTED_ENVIRONMENTAL_FAULT = "expected_environmental_fault"
    ORACLE_VIOLATION = "oracle_violation"
    CANCELLATION = "cancellation"
    BUDGET_EXHAUSTION = "budget_exhaustion"


class ExperimentLimits(BaseModel):
    """Set by trusted code only. Nothing in the protocol can change them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_steps: int = Field(default=6, ge=1, le=20)
    max_runtime_seconds: float = Field(default=300.0, gt=0, le=1_800)
    step_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    max_target_runs: int = Field(default=1, ge=0, le=3)
    # Sandbox steps have no world effects, so re-running one is safe. Target runs are never
    # retried: there is deliberately no setting for that.
    sandbox_infra_retries: int = Field(default=1, ge=0, le=2)


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1)
    parent_investigation_id: str | None = Field(default=None, max_length=64)


class SandboxExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox_run_id: str
    attempt: int = Field(ge=1)
    status: ExecutionStatus
    exit_code: int | None
    duration_ms: int
    oom_killed: bool
    cleaned_up: bool
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    output_complete: bool
    stdout_sha256: str
    stderr_excerpt: str = Field(max_length=500)
    image: str
    image_id: str | None
    network_enabled: bool


class ActionDecision(StrEnum):
    AUTHORIZED = "authorized"
    REJECTED = "rejected"
    NOT_EVALUATED = "not_evaluated"  # the step failed before a proposal existed


class StepRecord(BaseModel):
    """One sandbox step: what ran, what it proposed, and what the coordinator decided."""

    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=1)
    started_at: datetime
    finished_at: datetime
    step_input_sha256: str
    sandbox: list[SandboxExecutionRecord]
    # Requested (untrusted). The raw text is kept only as a hash and bounded excerpt.
    proposed_action_sha256: str | None
    proposed_action_excerpt: str | None = Field(default=None, max_length=1_000)
    # Authorized (trusted).
    decision: ActionDecision
    authorized_action: dict[str, JsonValue] | None
    rejection: ProtocolRejection | None
    observation_sha256: str | None


class AuthorizedRun(BaseModel):
    """What the coordinator actually allowed, after validation."""

    model_config = ConfigDict(frozen=True)

    scenario_id: str
    scenario_version: str
    scenario_sha256: str  # of the exact scenario run, after any fault selection
    config: AgentConfigName
    fault_source: Literal["scenario", "experiment_selection"]
    faults: list[FaultSpec]


class TargetObserved(BaseModel):
    """What the target saw through the gateway. May be distorted by design."""

    model_config = ConfigDict(frozen=True)

    tool_trace: list[ToolTraceEntry]
    faults_delivered: int
    claim: FinalClaim | None
    termination: str


class CommittedSummary(BaseModel):
    """Read back from authoritative state after the run."""

    model_config = ConfigDict(frozen=True)

    world_id: str
    customers: list[CustomerRecord]
    changes: list[CommittedChange]
    new_customer_ids: list[str]


class TargetRunEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_ref: str
    run_id: str
    target_kind: Literal["llm_agent", "reference_executor"]
    # "reference_executor" and "offline_fixture" are never evidence of model behavior.
    evidence_source: Literal["live_provider", "offline_fixture", "reference_executor"]
    executor: str | None
    provider: str | None
    requested_model: str | None
    reported_models: list[str]
    policy_version: str | None
    policy_sha256: str | None
    started_at: datetime
    finished_at: datetime
    authorized: AuthorizedRun
    target_observed: TargetObserved
    committed: CommittedSummary
    oracle: OracleReport
    error: ErrorDetail | None
    tokens: TokenTotals | None
    inference_latency_ms: int | None
    wall_ms: int
    estimated_cost_usd: float | None
    cost_note: str
    report_path: str  # relative to the experiment directory
    report_sha256: str


class UnresolvedTargetRun(BaseModel):
    """A target run that started and never reported. Its world effects are unknown."""

    model_config = ConfigDict(frozen=True)

    run_ref: str
    scenario_id: str
    world_found: bool
    committed_new_customer_ids: list[str] | None
    note: str


class SandboxSupplied(BaseModel):
    """Untrusted closing remarks, kept for the reader and for nothing else."""

    model_config = ConfigDict(frozen=True)

    conclusion: ExperimentConclusion
    summary: str


class ResourceUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox_executions: int
    sandbox_ms: int
    target_runs: int
    total_tokens: int
    tokens_complete: bool
    estimated_cost_usd: float | None
    wall_ms: int


class ExperimentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = EVIDENCE_SCHEMA_VERSION
    experiment_id: str
    parent_investigation_id: str | None
    label: str
    authorship: ExperimentAuthorship
    code_sha256: str
    protocol: str
    limits: ExperimentLimits
    status: ExperimentState
    termination: ExperimentTermination
    classifications: list[OutcomeClass]
    detail: str | None
    created_at: datetime
    finished_at: datetime
    steps: list[StepRecord]
    target_runs: list[TargetRunEvidence]
    unresolved_target_runs: list[UnresolvedTargetRun] = Field(
        default_factory=list[UnresolvedTargetRun]
    )
    sandbox_supplied: SandboxSupplied | None
    usage: ResourceUsage
