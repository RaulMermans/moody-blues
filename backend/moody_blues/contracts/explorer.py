"""Public evidence contracts for the Investigation Explorer.

Everything here is a *projection* of records written by the coordinator, the gateway, the Oracle
and the Investigator. Nothing in this module decides a verdict: ``verdict`` and every ``finding``
are copied from the Oracle's report, and ``ProductOutcome`` only summarises recorded states.

Authorship stays visible to the reader. ``Authorship`` says who wrote each timeline entry, so a
model's hypothesis can never look like an Oracle result.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from moody_blues.contracts.investigation import (
    FindingClass,
    Impairment,
    InvestigationState,
    ReproductionStatus,
    ResultClass,
    Strategy,
    WorldTier,
)
from moody_blues.contracts.oracle import FindingCode, Severity, Verdict

EXPORT_VERSION = 1

InvestigationId = Annotated[str, StringConstraints(pattern=r"^inv_[0-9a-f]{12}$")]
ExperimentId = Annotated[str, StringConstraints(pattern=r"^exp_[0-9a-f]{12}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _Public(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionMode(StrEnum):
    # A real past execution, exported and hash-pinned. Never presented as happening now.
    RECORDED = "recorded"
    # A real model-driven investigation started from this application.
    LIVE = "live"
    # Real sandboxes, worlds and Oracle, with a labeled fixture model and a reference script.
    # Exercises the product path for free. Never evidence of model behavior.
    REHEARSAL = "rehearsal"


class CaseKind(StrEnum):
    VERIFIED_VIOLATION = "verified_violation"
    HONEST_VIOLATION = "honest_violation"
    SUCCESSFUL_RECOVERY = "successful_recovery"
    NEGATIVE_RESULT = "negative_result"
    INCONCLUSIVE = "inconclusive"


class ProductOutcome(StrEnum):
    """One headline per investigation, read from recorded findings and states.

    ``NO_VIOLATION_FOUND`` means none was found in the runs listed, never that the agent is safe.
    A run with no claim is not a success: such runs keep their own ``run_outcome``.
    """

    VIOLATION_VERIFIED = "violation_verified"
    VIOLATION_IMPAIRED = "violation_impaired"  # the Oracle found one in an impaired run
    NO_VIOLATION_FOUND = "no_violation_found"
    INCONCLUSIVE = "inconclusive"
    OUTCOME_UNCERTAIN = "outcome_uncertain"  # a run with possible effects never reported back
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class IntegrityState(StrEnum):
    VERIFIED = "verified"  # hash and schema both checked at load time
    CORRUPT = "corrupt"  # refused: never rendered as a result


class BoundedText(_Public):
    """Text cut to a limit, with the size and hash of the whole, so a cut is never silent."""

    text: str
    truncated: bool
    original_chars: int
    sha256: Sha256


class ExperimentProvenance(_Public):
    experiment_id: str
    evidence_sha256: Sha256
    journal_head_sha256: Sha256
    run_report_sha256: list[Sha256]


class Provenance(_Public):
    """Where a bundle came from. Lets anyone with the raw records re-derive it byte for byte."""

    export_version: Literal[1] = EXPORT_VERSION
    source_report_sha256: Sha256
    source_journal_head_sha256: Sha256
    source_journal_records: int
    capability_sha256: Sha256
    experiments: list[ExperimentProvenance]


class CaseNote(_Public):
    """Written by a person choosing this case. Editorial, and labeled so in the interface."""

    kind: CaseKind
    title: str = Field(max_length=120)
    summary: str = Field(max_length=400)
    primary_run_id: str | None


class InvestigationSummary(_Public):
    investigation_id: str
    mode: ExecutionMode
    case: CaseNote | None
    outcome: ProductOutcome
    state: InvestigationState
    termination: str | None
    strategy: Strategy
    tier: WorldTier
    world_ids: list[str]
    investigator_model: str
    target_model: str
    # None: this strategy used no model.
    investigator_evidence: Literal["live_provider", "offline_fixture"] | None
    target_evidence: list[Literal["live_provider", "offline_fixture", "reference_executor"]]
    experiment_count: int
    target_run_count: int
    verified_finding_count: int
    violation_codes: list[str]
    started_at: datetime
    finished_at: datetime | None
    runtime_ms: int
    estimated_cost_usd: float
    usage_complete: bool
    cost_note: str


class HypothesisView(_Public):
    hypothesis_id: str
    status: Literal["open", "supported", "refuted", "inconclusive"]
    behavior: str
    suspected_mechanism: str
    motivation: str
    predicted_observation: str
    failure_discriminator: str
    motivating_observations: list[str]
    revises: str | None
    assessment_reasoning: str | None
    assessment_observations: list[str]


class AdaptationKind(StrEnum):
    FIRST_EXPERIMENT = "first_experiment"
    # The model cited earlier observations. A citation shows what it was shown and named, not that
    # the observation caused the change: Sprint 6 could not demonstrate that.
    CITED_PRIOR_OBSERVATIONS = "cited_prior_observations"
    PLANNED_WITHOUT_RESULTS = "planned_without_results"
    PREDETERMINED_PROGRAM = "predetermined_program"


class ProposalView(_Public):
    proposal_id: str
    hypothesis_id: str | None
    label: str | None
    rationale: str | None
    status: Literal["executed", "rejected_before_execution"]
    authorship: Literal["developer_script", "model_generated"]
    adaptation: AdaptationKind
    motivated_by: list[str]
    rejection_problem: str | None
    replaces_proposal_id: str | None
    code: BoundedText | None
    code_sha256: Sha256 | None


class ObservationView(_Public):
    """What informed the next step: recorded facts only, never target or sandbox prose."""

    observation_id: str
    experiment_id: str
    proposal_id: str
    result_class: ResultClass
    verdicts: list[Verdict]
    claim_statuses: list[str | None]
    faults_delivered: int


class ExperimentView(_Public):
    experiment_id: str
    proposal_id: str
    observation_id: str
    label: str
    status: str
    termination: str
    result_class: ResultClass
    target_run_ids: list[str]
    reproduction_of: str | None
    sandbox_executions: int
    sandbox_network_enabled: bool
    total_tokens: int
    estimated_cost_usd: float | None
    wall_ms: int


class FindingView(_Public):
    experiment_id: str
    run_id: str
    world_ref: str
    config: str
    finding_class: FindingClass
    oracle_verdict: Verdict
    run_outcome: str | None
    termination: str
    violation_codes: list[str]
    faults_delivered: int
    target_evidence: Literal["live_provider", "offline_fixture", "reference_executor"]
    reproduction: ReproductionStatus
    impairments: list[Impairment]
    eligible_for_rate: bool


class ClaimCheckView(_Public):
    experiment_id: str
    finding_code: str
    statement: str
    supported: bool
    reason: str
    fault_was_delivered: bool


class ConclusionView(_Public):
    """The model's reading. ``claim_checks`` say what the Oracle backed."""

    conclusion: Literal["violation_found", "no_violation_found", "inconclusive"]
    reasoning: str


class FaultView(_Public):
    kind: str
    operation: str
    occurrence: int
    span: int


class ToolEvent(_Public):
    """One call as the agent lived it, with the true response where a fault replaced it."""

    call_seq: int
    tool: str
    arguments: BoundedText
    ok: bool
    delivered: BoundedText
    delivered_summary: str
    error_code: str | None
    fault_injected: str | None
    fault_effect: str | None
    actual_summary: str | None  # present only where the delivered response was distorted
    agent_note: BoundedText | None  # the model's own text before this call


class ClaimView(_Public):
    status: str
    customer_id: str | None
    message: BoundedText


class DisclosureView(_Public):
    """Whether the free-text message names records the Oracle flagged. An id match, no more.

    This says nothing about intent. A disclosed duplicate under a ``completed`` status is still a
    false structured claim, and it is still not concealment.
    """

    flagged_customer_ids: list[str]
    mentioned_in_message: list[str]
    not_mentioned_in_message: list[str]


class AgentReality(_Public):
    mission: BoundedText | None
    tool_events: list[ToolEvent]
    termination: str
    claim: ClaimView | None
    disclosure: DisclosureView | None
    recovery_pattern: str | None


class CustomerView(_Public):
    customer_id: str
    name: str
    email: str
    metadata: dict[str, JsonValue]
    client_request_id: str | None
    created_by_call: int
    role: Literal["seed", "new"]
    objective_match: bool
    flagged_duplicate: bool
    named_in_claim: bool


class ChangeView(_Public):
    change_seq: int
    operation: str
    customer_id: str
    created_by_call: int


class OracleFindingView(_Public):
    code: FindingCode
    severity: Severity
    invariant: str | None
    message: str
    customer_ids: list[str]
    call_seqs: list[int]


class ActualReality(_Public):
    customers: list[CustomerView]
    changes: list[ChangeView]
    new_customer_ids: list[str]
    verdict: Verdict
    objective_satisfied: bool
    invariants_evaluated: list[str]
    invariants_violated: list[str]
    findings: list[OracleFindingView]


class DiscrepancyKind(StrEnum):
    MISLEADING_WRITE_RESPONSE = "misleading_write_response"
    STALE_READ = "stale_read"
    CLAIM_VERSUS_STATE = "claim_versus_state"
    DUPLICATE_SIDE_EFFECT = "duplicate_side_effect"


class Discrepancy(_Public):
    kind: DiscrepancyKind
    call_seq: int | None
    agent_saw: str
    actually: str
    source: Literal["oracle", "fault_event"]


class RealityRun(_Public):
    run_id: str
    run_ref: str
    experiment_id: str
    world_ref: str
    scenario_ref: str
    config: str
    target_kind: Literal["llm_agent", "reference_executor"]
    target_evidence: Literal["live_provider", "offline_fixture", "reference_executor"]
    reported_models: list[str]
    verdict: Verdict
    run_outcome: str | None
    finding_class: FindingClass | None
    impairments: list[Impairment]
    faults: list[FaultView]
    faults_delivered: int
    agent: AgentReality
    actual: ActualReality
    discrepancies: list[Discrepancy]


class TimelineStage(StrEnum):
    INVESTIGATION_CREATED = "investigation_created"
    MODEL_CALL = "model_call"
    HYPOTHESIS_CREATED = "hypothesis_created"
    HYPOTHESIS_REVISED = "hypothesis_revised"
    HYPOTHESIS_ASSESSED = "hypothesis_assessed"
    EXPERIMENT_GENERATED = "experiment_generated"
    EXPERIMENT_REJECTED = "experiment_rejected"
    SANDBOX_EXECUTION = "sandbox_execution"
    TARGET_RUN_STARTED = "target_run_started"
    TOOL_INTERACTION = "tool_interaction"
    FAULT_DELIVERED = "fault_delivered"
    TARGET_RUN_FINISHED = "target_run_finished"
    ORACLE_VERDICT = "oracle_verdict"
    OBSERVATION = "observation"
    CONCLUSION = "conclusion"
    INVESTIGATION_FINISHED = "investigation_finished"


class Authorship(StrEnum):
    MODEL = "investigator_model"  # interpretation, never fact
    COORDINATOR = "coordinator"
    SANDBOX = "sandbox"  # what untrusted experiment code did, as checked by the coordinator
    GATEWAY = "gateway"  # true record of delivery; the content may be distorted by design
    TARGET = "target_agent"  # asserted by the target; may be false
    ORACLE = "oracle"  # authoritative


class EvidenceRef(_Public):
    """The exact source record behind a timeline entry."""

    journal: Literal["investigation", "experiment"]
    journal_seq: int
    record_sha256: Sha256
    experiment_id: str | None = None
    run_id: str | None = None
    hypothesis_id: str | None = None
    proposal_id: str | None = None
    observation_id: str | None = None
    call_seq: int | None = None


class TimelineEntry(_Public):
    seq: int
    at: datetime
    # A tool call carries the time of the journal record that reported it, not its own: the
    # gateway keeps logical time inside the world, so calls are ordered by ``call_seq`` only.
    at_precision: Literal["exact", "run_report"]
    stage: TimelineStage
    authorship: Authorship
    title: str
    detail: str | None
    facts: dict[str, JsonValue]
    evidence: EvidenceRef


class StudyContext(_Public):
    """The registered result every reader should see. Copied from the committed results."""

    manifest_id: str
    results_sha256: Sha256
    conclusion: str
    units_with_verified_discovery: dict[str, int]
    units_planned: dict[str, int]
    reasons: list[str]


class CaseStudy(_Public):
    """Registered reruns of a single case. Copied from the committed results file."""

    rerun_source_sha256: Sha256
    eligible_runs: int
    eligible_reproduced: int
    impaired_runs: int
    note: str


class InvestigationBundle(_Public):
    export_version: Literal[1] = EXPORT_VERSION
    summary: InvestigationSummary
    objective: str
    statement: str
    limitations: list[str]
    hypotheses: list[HypothesisView]
    proposals: list[ProposalView]
    observations: list[ObservationView]
    experiments: list[ExperimentView]
    findings: list[FindingView]
    claim_checks: list[ClaimCheckView]
    conclusion: ConclusionView | None
    runs: list[RealityRun]
    timeline: list[TimelineEntry]
    case_study: CaseStudy | None = None
    provenance: Provenance


class ManifestEntry(_Public):
    investigation_id: InvestigationId
    file: Annotated[str, StringConstraints(pattern=r"^inv_[0-9a-f]{12}\.json$")]
    bundle_sha256: Sha256
    source_report_sha256: Sha256


class RecordedManifest(_Public):
    export_version: Literal[1] = EXPORT_VERSION
    study: StudyContext
    cases: list[ManifestEntry]


# --- API responses ------------------------------------------------------------------------


class ListedInvestigation(_Public):
    """A listing never hides a bad record. It says the record was refused, and why in one code."""

    investigation_id: str
    integrity: IntegrityState
    summary: InvestigationSummary | None
    problem: str | None = None


class InvestigationList(_Public):
    items: list[ListedInvestigation]
    study: StudyContext | None


class InvestigationDetail(_Public):
    summary: InvestigationSummary
    integrity: IntegrityState
    objective: str
    statement: str
    limitations: list[str]
    hypotheses: list[HypothesisView]
    proposals: list[ProposalView]
    observations: list[ObservationView]
    findings: list[FindingView]
    claim_checks: list[ClaimCheckView]
    conclusion: ConclusionView | None
    case_study: CaseStudy | None
    provenance: Provenance


class TimelinePage(_Public):
    investigation_id: str
    total: int
    offset: int
    entries: list[TimelineEntry]


class ExperimentList(_Public):
    investigation_id: str
    experiments: list[ExperimentView]


class RunList(_Public):
    investigation_id: str
    primary_run_id: str | None
    run_ids: list[str]


# --- live execution ----------------------------------------------------------------------


class JobStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    # Terminal
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    OUTCOME_UNCERTAIN = "outcome_uncertain"


TERMINAL_JOB_STATES: frozenset[JobStatus] = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.BUDGET_EXHAUSTED,
        JobStatus.OUTCOME_UNCERTAIN,
    }
)


class JobEventType(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    EXPERIMENT_COMPLETED = "experiment_completed"
    FINDING_VERIFIED = "finding_verified"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    OUTCOME_UNCERTAIN = "outcome_uncertain"


class JobEvent(_Public):
    """Fixed codes and ids only. Model and target text is never streamed."""

    event_id: int = Field(ge=1)
    job_id: str
    at: datetime
    type: JobEventType
    code: str = Field(max_length=64)
    experiment_id: str | None = None
    result_class: ResultClass | None = None


class JobRecord(_Public):
    job_id: str
    mission_id: str
    mode: ExecutionMode
    status: JobStatus
    investigation_id: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    code: str | None = None  # why it ended, as a fixed code
    cancel_requested: bool = False
    evidence_available: bool = False
    bundle_sha256: Sha256 | None = None


class JobView(_Public):
    job: JobRecord
    events: list[JobEvent]


class MissionView(_Public):
    mission_id: str
    mode: ExecutionMode
    title: str
    description: str
    worlds: list[str]
    max_experiments: int
    available: bool
    # Why it cannot start now, as a fixed code. None when ``available``.
    blocked_by: str | None


class BudgetView(_Public):
    limit_usd: float
    settled_usd: float
    open_reservations_usd: float
    remaining_usd: float
    required_usd: float
    note: str


class LiveStatus(_Public):
    live_enabled: bool
    budget: BudgetView | None
    budget_problem: str | None
    active_job_id: str | None
    missions: list[MissionView]


class StartJob(_Public):
    mission_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{3,48}$")]
