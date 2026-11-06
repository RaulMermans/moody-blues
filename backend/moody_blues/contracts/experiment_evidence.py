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
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from moody_blues.contracts.adapter import ExternalAgentRecord
from moody_blues.contracts.agent import AgentConfigName, TokenTotals
from moody_blues.contracts.common import ErrorDetail, ExecutionStatus
from moody_blues.contracts.oracle import AnyOracleReport
from moody_blues.contracts.protocol import (
    ExperimentConclusion,
    Observation,
    ProtocolRejection,
)
from moody_blues.contracts.run import ToolTraceEntry
from moody_blues.contracts.scenario import FaultSpec
from moody_blues.contracts.validity import RunValidity
from moody_blues.contracts.world import (
    AnyClaim,
    CommittedChange,
    CustomerRecord,
    WorldChange,
    WorldRecord,
)
from moody_blues.contracts.world_plugin import (
    LEGACY_PLUGIN_VERSION,
    LEGACY_WORLD_TYPE,
    WorldProvenance,
)

# Version 2 is version 1 plus external target runs. A record without one stays at version 1, so
# nothing written before Sprint 15, and nothing written since by an internal target, changes.
# Version 3 is a record from a world other than the CRM, which earlier readers cannot parse. A CRM
# record gains optional fields and keeps its version: a reader that ignores them loses nothing.
EVIDENCE_SCHEMA_VERSION: Literal[1] = 1
EXTERNAL_EVIDENCE_SCHEMA_VERSION: Literal[2] = 2
WORLD_EVIDENCE_SCHEMA_VERSION: Literal[3] = 3


class ExperimentAuthorship(StrEnum):
    # Sprint 4 experiments are written by developers. They are not autonomous discoveries.
    DEVELOPER_SCRIPT = "developer_script"
    # Written by the Investigator's model. Generating code is not a discovery; a finding needs
    # an Oracle verdict about a real target run.
    MODEL_GENERATED = "model_generated"


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


class GenerationRecord(BaseModel):
    """Who wrote a ``model_generated`` program. ``offline_fixture`` is never model behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: str = Field(max_length=64)
    model: str = Field(max_length=120)
    evidence_source: Literal["live_provider", "offline_fixture", "local_ollama"]


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1)
    parent_investigation_id: str | None = Field(default=None, max_length=64)
    authorship: ExperimentAuthorship = ExperimentAuthorship.DEVELOPER_SCRIPT
    generation: GenerationRecord | None = None
    reproduction_of: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _generation_matches_authorship(self) -> Self:
        generated = self.authorship is ExperimentAuthorship.MODEL_GENERATED
        if generated != (self.generation is not None):
            raise ValueError("generation is required for, and only for, model_generated code")
        return self


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
    claim: AnyClaim | None
    termination: str


class CommittedSummary(BaseModel):
    """Read back from authoritative state after the run."""

    model_config = ConfigDict(frozen=True)

    world_id: str
    customers: list[CustomerRecord]
    changes: list[CommittedChange]
    new_customer_ids: list[str]

    @property
    def new_ids(self) -> list[str]:
        return self.new_customer_ids


class WorldCommittedSummary(BaseModel):
    """``CommittedSummary`` for a world without customers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    world_id: str
    records: list[WorldRecord]
    changes: list[WorldChange]
    new_record_ids: list[str]

    @property
    def new_ids(self) -> list[str]:
        return self.new_record_ids


class TargetRunEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_ref: str
    run_id: str
    target_kind: Literal["llm_agent", "reference_executor", "external_agent"]
    # ``RunOutcome`` for agent runs. Read this with the verdict: an Oracle PASS only says the
    # state is right, and an agent that never claimed anything is not a success.
    run_outcome: str | None = None  # absent in records written before this field existed
    # Only ``MODEL_EVIDENCE`` values are evidence of model behavior.
    evidence_source: Literal[
        "live_provider",
        "local_ollama",
        "offline_fixture",
        "reference_executor",
        "external_scripted",
    ]
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
    committed: CommittedSummary | WorldCommittedSummary
    oracle: AnyOracleReport
    error: ErrorDetail | None
    tokens: TokenTotals | None
    inference_latency_ms: int | None
    wall_ms: int
    estimated_cost_usd: float | None
    cost_note: str
    report_path: str  # relative to the experiment directory
    report_sha256: str
    # Model steps cut off by a token limit we set. Absent in earlier records.
    truncated_model_steps: int = 0
    # Sprint 15: who ran, on what, under which limits. Left out when absent.
    external: ExternalAgentRecord | None = Field(default=None, exclude_if=lambda v: v is None)
    # Sprint 18. Absent in earlier records: see ``world_type`` and ``run_validity``.
    world: WorldProvenance | None = Field(default=None, exclude_if=lambda v: v is None)
    validity: RunValidity | None = Field(default=None, exclude_if=lambda v: v is None)

    @property
    def world_type(self) -> str:
        return self.world.world_type if self.world is not None else LEGACY_WORLD_TYPE

    @property
    def plugin_version(self) -> str:
        return self.world.plugin_version if self.world is not None else LEGACY_PLUGIN_VERSION

    @model_validator(mode="after")
    def _external_is_recorded(self) -> Self:
        if (self.target_kind == "external_agent") != (self.external is not None):
            raise ValueError("an external run needs its provenance, and only an external run")
        return self


class UnresolvedTargetRun(BaseModel):
    """A target run that started and never reported. Its world effects are unknown."""

    model_config = ConfigDict(frozen=True)

    run_ref: str
    scenario_id: str
    world_found: bool
    committed_new_customer_ids: list[str] | None
    note: str
    # Sprint 18: the same thing for a world without customers. Left out when absent.
    committed_new_record_ids: list[str] | None = Field(default=None, exclude_if=lambda v: v is None)
    # Sprint 16. Model calls the host wrote down before making them and has no answer for. Each may
    # have run and may be billed. Left out when zero, so earlier records stay byte-identical.
    model_calls_unresolved: int = Field(default=0, ge=0, exclude_if=lambda v: v == 0)


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

    schema_version: Literal[1, 2, 3] = EVIDENCE_SCHEMA_VERSION
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
    # Sprint 5. Absent in earlier records, so all of these default.
    generation: GenerationRecord | None = None
    reproduction_of: str | None = None
    source_path: str | None = None  # the original program, relative to the experiment directory
    # Exactly what the sandbox was shown, in order. The Investigator's view is built from these.
    observations: list[Observation] = Field(default_factory=list[Observation])

    @model_validator(mode="after")
    def _version_fits_runs(self) -> Self:
        external = any(r.external is not None for r in self.target_runs)
        if external and self.schema_version < EXTERNAL_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("an external target run needs schema version 2")
        other_world = any(r.world_type != LEGACY_WORLD_TYPE for r in self.target_runs)
        if other_world and self.schema_version < WORLD_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("a run in another world needs schema version 3")
        return self
