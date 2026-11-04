"""Investigation contracts: hypotheses, proposals, observations, findings, reports.

Authorship is kept apart here for the same reason it is in experiment evidence:

=====================  ======================================  ==========================
Object                 Author                                  Trust
=====================  ======================================  ==========================
``Hypothesis``,        Investigator model                      interpretation, never fact
``HypothesisAssessment``,
``ClaimedFinding``
``InvestigationObservation``  trusted code, from evidence      structured facts
``VerifiedFinding``    trusted code, from Oracle reports       the only source of findings
=====================  ======================================  ==========================

Text reaching the Investigator's model is bounded by type: every string field of an
observation is a ``SafeToken``, which cannot hold a sentence, so target claim messages and
sandbox remarks are unrepresentable there. They survive only as ``OmittedText`` (hash, length).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from moody_blues.contracts.agent import AgentConfigName, EvidenceSource
from moody_blues.contracts.experiment_evidence import ExperimentAuthorship, ExperimentState
from moody_blues.contracts.oracle import Verdict

INVESTIGATION_SCHEMA_VERSION = 1

SafeToken = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:@+-]{0,96}$")]
ObservationId = Annotated[str, StringConstraints(pattern=r"^obs_[0-9]{1,3}$")]
HypothesisId = Annotated[str, StringConstraints(pattern=r"^h[0-9]{1,3}$")]
ExperimentLabel = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")]
Prose = Annotated[str, StringConstraints(min_length=1, max_length=600)]


class InvestigationState(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    EXPERIMENTING = "experimenting"
    EVALUATING = "evaluating"
    REVISING = "revising"
    # Terminal
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INCONCLUSIVE = "inconclusive"


TERMINAL_INVESTIGATION_STATES: frozenset[InvestigationState] = frozenset(
    {
        InvestigationState.COMPLETED,
        InvestigationState.FAILED,
        InvestigationState.CANCELLED,
        InvestigationState.BUDGET_EXHAUSTED,
        InvestigationState.INCONCLUSIVE,
    }
)


class Strategy(StrEnum):
    FIXED = "fixed"  # Strategy A: approved programs chosen in advance. No model.
    ONE_SHOT = "one_shot"  # Strategy B: one model call writes every experiment, with no feedback.
    ADAPTIVE = "adaptive"  # Strategy C: each experiment is written after seeing earlier results.


class WorldTier(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    EVALUATION = "evaluation"


class InvestigationLimits(BaseModel):
    """Set by trusted code only. Nothing a model or a sandbox says can change them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_experiments: int = Field(default=3, ge=1, le=6)
    max_target_runs_per_experiment: int = Field(default=1, ge=1, le=1)
    max_model_calls: int = Field(default=5, ge=1, le=12)
    max_completion_tokens: int = Field(default=4_096, ge=256, le=8_192)
    max_prompt_chars: int = Field(default=48_000, ge=2_000, le=120_000)
    max_refinements: int = Field(default=1, ge=0, le=2)
    max_reproductions: int = Field(default=1, ge=0, le=3)
    max_wall_seconds: float = Field(default=900.0, gt=0, le=3_600)
    temperature: float = Field(default=0.0, ge=0, le=1)


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    objective: str = Field(min_length=1, max_length=500)
    strategy: Strategy = Strategy.ADAPTIVE
    tier: WorldTier
    world_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    investigator_model: str = Field(max_length=120)
    target_model: str = Field(max_length=120)
    limits: InvestigationLimits = Field(default_factory=InvestigationLimits)


class ToolContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str


class WorldCard(BaseModel):
    """All the Investigator is told about a world. Its conditions are for it to find."""

    model_config = ConfigDict(frozen=True)

    world_id: str
    seed_customers: int


class TargetCapability(BaseModel):
    """What may legitimately be known about the target and the environment."""

    model_config = ConfigDict(frozen=True)

    mission: str
    tools: list[ToolContract]
    expectations: list[str]
    configs: list[AgentConfigName]
    perturbations: list[str]
    worlds: list[WorldCard]


# --- written by the model -----------------------------------------------------------------


class _ModelArgs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Hypothesis(_ModelArgs):
    hypothesis_id: HypothesisId
    behavior: Prose  # what is being investigated
    suspected_mechanism: Prose  # how it could fail
    motivating_observations: list[ObservationId] = Field(max_length=8)
    motivation: Prose  # why this is worth testing now
    predicted_observation: Prose  # what would be seen if the suspicion is right
    failure_discriminator: Prose  # what separates failure from correct behavior
    revises: HypothesisId | None = None


class HypothesisAssessment(_ModelArgs):
    hypothesis_id: HypothesisId
    status: Literal["supported", "refuted", "inconclusive"]
    cited_observations: list[ObservationId] = Field(min_length=1, max_length=8)
    reasoning: Prose


class ProposedExperiment(_ModelArgs):
    label: ExperimentLabel
    rationale: Prose
    motivated_by: list[ObservationId] = Field(max_length=8)
    python_code: str = Field(min_length=1)


class ProposeExperiment(_ModelArgs):
    assessments: list[HypothesisAssessment] = Field(max_length=8)
    hypothesis: Hypothesis
    experiment: ProposedExperiment


class PlannedExperiment(_ModelArgs):
    hypothesis: Hypothesis
    experiment: ProposedExperiment


class ProposePlan(_ModelArgs):
    """Strategy B only: every experiment at once, before any result exists."""

    experiments: list[PlannedExperiment] = Field(min_length=1, max_length=6)


class ClaimedFinding(_ModelArgs):
    """The model's reading of a result. Checked against the Oracle; never a finding itself."""

    experiment_id: SafeToken
    finding_code: SafeToken
    statement: Prose


class ConcludeInvestigation(_ModelArgs):
    assessments: list[HypothesisAssessment] = Field(max_length=8)
    conclusion: Literal["violation_found", "no_violation_found", "inconclusive"]
    claimed_findings: list[ClaimedFinding] = Field(max_length=8)
    reasoning: Prose


# --- recorded by trusted code -------------------------------------------------------------


class ResultClass(StrEnum):
    """What an experiment produced. Decided from trusted records only."""

    INVALID_PYTHON = "invalid_python"
    INVALID_PROTOCOL_OUTPUT = "invalid_protocol_output"
    UNAUTHORIZED_ACTION = "unauthorized_action"
    SANDBOX_RUNTIME_FAILURE = "sandbox_runtime_failure"
    NO_TARGET_RUN = "no_target_run"  # the program finished without asking for a run
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    PROVIDER_FAILURE = "provider_failure"
    TARGET_AGENT_SHORTFALL = "target_agent_shortfall"
    ORACLE_CONFIRMED_VIOLATION = "oracle_confirmed_violation"
    NO_VIOLATION_FOUND = "no_violation_found"
    UNCERTAIN_SIDE_EFFECTS = "uncertain_side_effects"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"


class Provenance(StrEnum):
    ORACLE = "oracle"  # authoritative
    COORDINATOR = "coordinator"  # trusted record of what was run
    GATEWAY_DELIVERED = "gateway_delivered"  # true record of delivery; content may be distorted
    TARGET_REPORTED = "target_reported"  # asserted by the target; may be false
    SANDBOX_REPORTED = "sandbox_reported"  # asserted by experiment code; may be false


class SelectedFault(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: SafeToken
    occurrence: int
    span: int = 1


class OracleFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    provenance: Literal[Provenance.ORACLE] = Provenance.ORACLE
    verdict: Verdict
    objective_satisfied: bool
    invariants_violated: list[SafeToken]
    finding_codes: list[SafeToken]
    run_outcome: SafeToken | None


class TargetReportedFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    provenance: Literal[Provenance.TARGET_REPORTED] = Provenance.TARGET_REPORTED
    claim_status: SafeToken | None
    termination: SafeToken


class DeliveredFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    provenance: Literal[Provenance.GATEWAY_DELIVERED] = Provenance.GATEWAY_DELIVERED
    tool_calls: int
    faults_delivered: int


class RunFacts(BaseModel):
    """One target run. Built faults of a world are not named: they are for finding out."""

    model_config = ConfigDict(frozen=True)

    provenance: Literal[Provenance.COORDINATOR] = Provenance.COORDINATOR
    run_ref: SafeToken
    world_ref: SafeToken
    config: AgentConfigName
    fault_source: Literal["world_default", "experiment_selection"]
    selected_faults: list[SelectedFault]
    oracle: OracleFacts
    target: TargetReportedFacts
    delivered: DeliveredFacts


class CallFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    tool: SafeToken
    ok: bool
    error_code: SafeToken | None
    used_idempotency_key: bool | None = None
    idempotent_replay: bool | None = None
    result_count: int | None = None


class InspectionFacts(BaseModel):
    """Detail the experiment program itself asked for with ``inspect_observation``."""

    model_config = ConfigDict(frozen=True)

    provenance: Literal[Provenance.GATEWAY_DELIVERED] = Provenance.GATEWAY_DELIVERED
    run_ref: SafeToken
    section: SafeToken
    tool_calls: list[CallFact] | None = None
    claim_status: SafeToken | None = None
    claim_points_to: SafeToken | None = None
    new_customers: int | None = None
    objective_matching_records: int | None = None
    seed_customers: int | None = None


class OmittedText(BaseModel):
    """Untrusted free text that exists in evidence and was deliberately not passed on."""

    model_config = ConfigDict(frozen=True)

    source: Literal["target_claim_message", "sandbox_summary"]
    chars: int
    sha256: str


class InvestigationObservation(BaseModel):
    """The whole of what the Investigator learns from one experiment."""

    model_config = ConfigDict(frozen=True)

    observation_id: ObservationId
    experiment_id: SafeToken
    proposal_id: SafeToken
    provenance: Literal[Provenance.COORDINATOR] = Provenance.COORDINATOR
    result_class: ResultClass
    status: ExperimentState
    termination: SafeToken
    rejection_code: SafeToken | None = None
    python_error: SafeToken | None = None
    python_error_line: int | None = None
    runs: list[RunFacts] = Field(default_factory=list[RunFacts])
    inspections: list[InspectionFacts] = Field(default_factory=list[InspectionFacts])
    sandbox_reported_conclusion: SafeToken | None = None
    omitted_untrusted_text: list[OmittedText] = Field(default_factory=list[OmittedText])


class GenerationDiagnostic(BaseModel):
    """Feedback after a rejected proposal. Codes and known field names only."""

    model_config = ConfigDict(frozen=True)

    problem: SafeToken
    rejection_code: SafeToken | None = None
    python_error: SafeToken | None = None
    python_error_line: int | None = None
    invalid_fields: list[SafeToken] = Field(default_factory=list[SafeToken], max_length=12)
    hint: str  # from a fixed table in trusted code


class ProposalStatus(StrEnum):
    EXECUTED = "executed"
    REJECTED_BEFORE_EXECUTION = "rejected_before_execution"


class ProposalRecord(BaseModel):
    """One generated program. Replacements are new records; originals are never altered."""

    model_config = ConfigDict(frozen=True)

    proposal_id: str
    model_call_seq: int | None  # None for a developer script
    authorship: ExperimentAuthorship
    hypothesis_id: str | None
    label: str | None
    rationale: str | None
    motivated_by: list[str]
    source_sha256: str | None
    source_bytes: int | None
    source_path: str | None  # relative to the investigation directory
    status: ProposalStatus
    rejection: GenerationDiagnostic | None = None
    replaces_proposal_id: str | None = None


class ExperimentRef(BaseModel):
    """Links a proposal to the evidence of what really ran."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str
    proposal_id: str
    observation_id: str
    code_sha256: str
    evidence_sha256: str
    status: ExperimentState
    result_class: ResultClass
    target_run_ids: list[str]
    reproduction_of: str | None = None


class HypothesisRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis: Hypothesis
    status: Literal["open", "supported", "refuted", "inconclusive"] = "open"
    assessment: HypothesisAssessment | None = None


class DecisionKind(StrEnum):
    PROPOSE = "propose"
    CONCLUDE = "conclude"
    INVALID = "invalid"
    REFINE = "refine"  # a recoverable generation failure was answered with diagnostics
    TERMINATE = "terminate"  # trusted code stopped the investigation


class InvestigationDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    kind: DecisionKind
    model_call_seq: int | None
    hypothesis_id: str | None = None
    proposal_id: str | None = None
    cited_observations: list[str] = Field(default_factory=list[str])
    reason: str  # a fixed code from trusted code, or a model-call summary


class ModelCallRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    purpose: str
    evidence_source: EvidenceSource
    provider: str | None
    requested_model: str
    reported_model: str | None
    response_id: str | None
    finish_reason: str | None
    outcome: Literal["ok", "provider_error"]
    prompt_sha256: str
    response_sha256: str | None
    artifact_path: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    estimated_cost_usd: float | None
    spend_entry: str | None


class FindingClass(StrEnum):
    ORACLE_CONFIRMED_VIOLATION = "oracle_confirmed_violation"
    # The Oracle found a violation, but the run or its evidence was impaired. Needs review.
    IMPAIRED_VIOLATION = "impaired_violation"
    TARGET_SHORTFALL = "target_shortfall"  # no violation; the agent did not finish properly
    CORRECT_RECOVERY = "correct_recovery"  # faults delivered, and the run succeeded
    CLEAN_SUCCESS = "clean_success"  # no fault delivered, and the run succeeded


class ReproductionStatus(StrEnum):
    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"
    UNTESTED = "untested"
    NOT_APPLICABLE = "not_applicable"


class VerifiedFinding(BaseModel):
    """One run, classified by trusted code from the Oracle report and the run's own record."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str
    proposal_id: str
    run_id: str
    run_ref: str
    world_ref: str
    config: AgentConfigName
    selected_faults: list[SelectedFault]
    finding_class: FindingClass
    oracle_verdict: Verdict
    run_outcome: str | None
    termination: str
    violation_codes: list[str]
    faults_delivered: int
    target_evidence_source: Literal["live_provider", "offline_fixture", "reference_executor"]
    reproduction: ReproductionStatus
    reproduction_experiment_id: str | None = None
    notes: list[str] = Field(default_factory=list[str])

    @property
    def is_model_behavior(self) -> bool:
        return self.target_evidence_source == "live_provider"


class ClaimCheck(BaseModel):
    """Whether something the model claimed is backed by an Oracle report."""

    model_config = ConfigDict(frozen=True)

    claim: ClaimedFinding
    supported: bool
    reason: Literal[
        "oracle_confirms",
        "unknown_experiment",
        "no_violation_in_experiment",
        "finding_code_not_reported",
    ]


class InvestigationUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_calls: int = 0
    investigator_prompt_tokens: int = 0
    investigator_completion_tokens: int = 0
    investigator_latency_ms: int = 0
    investigator_cost_usd: float = 0.0
    target_runs: int = 0
    target_tokens: int = 0
    target_cost_usd: float = 0.0
    sandbox_executions: int = 0
    sandbox_ms: int = 0
    wall_ms: int = 0
    scope_settled_usd: float | None = None
    scope_open_usd: float | None = None
    scope_limit_usd: float | None = None
    usage_complete: bool = True
    note: str = "estimate at assumed ceiling prices; not a provider invoice"


class InvestigationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = INVESTIGATION_SCHEMA_VERSION
    investigation_id: str
    request: InvestigationRequest
    model_evidence_source: EvidenceSource | None  # None: no model in this strategy
    state: InvestigationState
    termination: str | None
    started_at: datetime
    finished_at: datetime | None
    capability_sha256: str
    hypotheses: list[HypothesisRecord]
    decisions: list[InvestigationDecision]
    proposals: list[ProposalRecord]
    experiments: list[ExperimentRef]
    observations: list[InvestigationObservation]
    model_calls: list[ModelCallRecord]
    model_conclusion: ConcludeInvestigation | None
    findings: list[VerifiedFinding]
    claim_checks: list[ClaimCheck]
    statement: str
    limitations: list[str]
    usage: InvestigationUsage
