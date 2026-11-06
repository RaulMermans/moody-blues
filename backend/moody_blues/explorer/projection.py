"""Build one public ``InvestigationBundle`` from an investigation's real records.

Input is the trusted record on disk: report, journals, evidence and run reports. Every entry in the
timeline is produced from one journal record and names it, so nothing here is reconstructed from a
final summary. Records that are missing or do not verify stop the projection. It never fills a gap.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from pydantic import JsonValue, ValidationError

from moody_blues.contracts.adapter import ModelCallStatus
from moody_blues.contracts.agent import AgentRunReport
from moody_blues.contracts.experiment_evidence import (
    CommittedSummary,
    ExperimentAuthorship,
    ExperimentEvidence,
    ExperimentState,
    StepRecord,
    TargetRunEvidence,
    WorldCommittedSummary,
)
from moody_blues.contracts.explorer import (
    ActualReality,
    AdaptationKind,
    AgentReality,
    Authorship,
    CaseNote,
    CaseStudy,
    ChangeView,
    ClaimCheckView,
    ClaimView,
    ConclusionView,
    CustomerView,
    DisclosureView,
    Discrepancy,
    DiscrepancyKind,
    EvidenceRef,
    ExecutionMode,
    ExperimentProvenance,
    ExperimentView,
    ExternalTargetView,
    FaultDeliveryView,
    FaultView,
    FindingView,
    HypothesisView,
    InvariantView,
    InvestigationBundle,
    InvestigationSummary,
    ObservationView,
    OracleFindingView,
    ProductOutcome,
    ProposalView,
    Provenance,
    RealityRun,
    RecordView,
    TimelineEntry,
    TimelineStage,
    ToolEvent,
    ValidityView,
    WorldView,
)
from moody_blues.contracts.investigation import (
    DecisionKind,
    FindingClass,
    InvestigationReport,
    InvestigationState,
    ProposalRecord,
    ProposalStatus,
    Strategy,
    VerifiedFinding,
)
from moody_blues.contracts.oracle import AnyOracleReport, FindingCode
from moody_blues.contracts.run import ToolTraceEntry
from moody_blues.contracts.world import ToolResponse, WorldChange, WorldClaim
from moody_blues.contracts.world_plugin import WorldDescriptor
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.workspace import (
    EVIDENCE,
    JOURNAL,
    JournalRecord,
    read_journal,
    sha256_text,
)
from moody_blues.explorer.sanitize import (
    MAX_CODE_CHARS,
    MAX_JSON_CHARS,
    MAX_MESSAGE_CHARS,
    MAX_NOTE_CHARS,
    EvidenceRefusedError,
    bounded,
)
from moody_blues.investigator.workspace import REPORT, verify_investigation
from moody_blues.world.crm_plugin import DESCRIPTOR as CRM_DESCRIPTOR
from moody_blues.world.registry import world_plugin

STALE_READ_EFFECT = "read_served_from_stale_snapshot"
_CLAIM_CODES = frozenset(
    {
        FindingCode.FALSE_COMPLETION_CLAIM,
        FindingCode.CLAIM_REFERENCES_WRONG_RECORD,
        FindingCode.CLAIM_REFERENCES_UNCOMMITTED_ID,
        FindingCode.UNDERREPORTED_COMPLETION,
    }
)


@dataclass(frozen=True, slots=True)
class _Loaded:
    evidence: ExperimentEvidence
    evidence_sha256: str
    journal: list[JournalRecord]
    reports: dict[str, AgentRunReport]  # by run_id; only LLM runs have one
    report_hashes: list[str]


def _json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def summarize_response(response: ToolResponse, world: WorldDescriptor = CRM_DESCRIPTOR) -> str:
    """A short, factual reading of one tool response. Ids and counts only, never prose."""
    if not response.ok:
        code = response.error.code if response.error else "error"
        return f"error: {code}"
    data = response.data or {}
    shape, noun = world.shape, world.record_noun
    item = data.get(shape.item_key)
    if isinstance(item, dict):
        replay = " (idempotent replay)" if data.get("idempotent_replay") is True else ""
        fields = cast(dict[str, JsonValue], item)
        return f"ok: {noun} {fields.get(shape.id_key)}{replay}"
    if "count" in data:
        return f"ok: {data['count']} {noun}(s) returned"
    if shape.id_key in data and "status" in data:
        return f"ok: {noun} {data[shape.id_key]} is {data['status']}"
    return "ok"


def _world(run: TargetRunEvidence) -> WorldDescriptor:
    return world_plugin(run.world_type).descriptor


def _load_experiment(directory: Path) -> _Loaded:
    text = (directory / EVIDENCE).read_text(encoding="utf-8")
    evidence = ExperimentEvidence.model_validate_json(text)
    records, problems = read_journal(directory / JOURNAL)
    if problems:
        raise EvidenceRefusedError(f"{directory.name}: journal does not verify")
    reports: dict[str, AgentRunReport] = {}
    hashes: list[str] = []
    for run in evidence.target_runs:
        raw = (directory / run.report_path).read_text(encoding="utf-8")
        hashes.append(sha256_text(raw))
        if run.target_kind != "reference_executor":
            reports[run.run_id] = AgentRunReport.model_validate_json(raw)
    return _Loaded(evidence, sha256_text(text), records, reports, hashes)


# --- reality ----------------------------------------------------------------------------


def _actual_summaries(
    report: AgentRunReport | None, world: WorldDescriptor = CRM_DESCRIPTOR
) -> dict[int, str]:
    """The true response behind each distorted call, from the gateway's own fault events."""
    if report is None:
        return {}
    out: dict[int, str] = {}
    for event in report.fault_events:
        if event.kind != "fault_injected" or event.call_seq is None:
            continue
        actual = event.payload.get("actual_response")
        if isinstance(actual, dict):
            out[event.call_seq] = summarize_response(ToolResponse.model_validate(actual), world)
    return out


def _notes(report: AgentRunReport | None) -> dict[int, str]:
    """The agent's own text before each call, keyed by the gateway's call sequence."""
    if report is None:
        return {}
    by_id = {
        record.tool_call_id: int(record.gateway_call_id.rsplit("_", 1)[1])
        for record in report.agent.tool_calls
        if record.gateway_call_id
    }
    notes: dict[int, str] = {}
    for step in report.agent.steps:
        seqs = [by_id[i] for i in step.tool_call_ids if i in by_id]
        if step.content and seqs:
            notes[min(seqs)] = step.content
    return notes


def _tool_event(
    entry: ToolTraceEntry,
    actual: Mapping[int, str],
    notes: Mapping[int, str],
    world: WorldDescriptor = CRM_DESCRIPTOR,
) -> ToolEvent:
    delivered = entry.delivered
    note = notes.get(entry.call_seq)
    return ToolEvent(
        call_seq=entry.call_seq,
        tool=entry.tool,
        arguments=bounded(_json_text(entry.arguments), MAX_JSON_CHARS),
        ok=delivered.ok,
        delivered=bounded(
            _json_text(
                delivered.data
                if delivered.ok
                else delivered.error
                and {
                    "code": delivered.error.code,
                    "message": delivered.error.message,
                    "retryable": delivered.error.retryable,
                }
            ),
            MAX_JSON_CHARS,
        ),
        delivered_summary=summarize_response(delivered, world),
        error_code=delivered.error.code if delivered.error else None,
        fault_injected=entry.fault_injected,
        fault_effect=entry.fault_effect,
        actual_summary=actual.get(entry.call_seq) if entry.fault_injected else None,
        agent_note=bounded(note, MAX_NOTE_CHARS) if note else None,
    )


def _flagged_ids(oracle: AnyOracleReport) -> list[str]:
    ids: list[str] = []
    for finding in oracle.findings:
        if finding.code == FindingCode.DUPLICATE_SIDE_EFFECT.value:
            ids.extend(i for i in finding.record_ids if i not in ids)
    return ids


def _disclosure(run: TargetRunEvidence) -> DisclosureView | None:
    claim = run.target_observed.claim
    flagged = _flagged_ids(run.oracle)
    if claim is None or not flagged:
        return None
    named = [i for i in flagged if i in claim.message]
    return DisclosureView(
        flagged_customer_ids=flagged,
        mentioned_in_message=named,
        not_mentioned_in_message=[i for i in flagged if i not in named],
    )


def _discrepancies(run: TargetRunEvidence, actual: Mapping[int, str]) -> list[Discrepancy]:
    out: list[Discrepancy] = []
    world = _world(run)
    trace = {t.call_seq: t for t in run.target_observed.tool_trace}
    for divergence in run.oracle.response_divergences:
        seen = trace.get(divergence.call_seq)
        out.append(
            Discrepancy(
                kind=DiscrepancyKind.MISLEADING_WRITE_RESPONSE,
                call_seq=divergence.call_seq,
                agent_saw=summarize_response(seen.delivered, world) if seen else "reported success",
                actually=(
                    f"committed {world.record_noun} {divergence.committed_record_id}"
                    if divergence.committed_record_id
                    else "nothing was committed by this call"
                ),
                source="oracle",
            )
        )
    for entry in run.target_observed.tool_trace:
        if entry.fault_injected and entry.fault_effect == STALE_READ_EFFECT:
            out.append(
                Discrepancy(
                    kind=DiscrepancyKind.STALE_READ,
                    call_seq=entry.call_seq,
                    agent_saw=summarize_response(entry.delivered, world),
                    actually=actual.get(
                        entry.call_seq, "the read was served from a stale snapshot"
                    ),
                    source="fault_event",
                )
            )
    claim = run.target_observed.claim
    for finding in run.oracle.findings:
        if finding.code in _CLAIM_CODES:
            out.append(
                Discrepancy(
                    kind=DiscrepancyKind.CLAIM_VERSUS_STATE,
                    call_seq=None,
                    agent_saw=f"final claim status: {claim.status.value if claim else 'none'}",
                    actually=finding.message,
                    source="oracle",
                )
            )
        elif finding.code == FindingCode.DUPLICATE_SIDE_EFFECT.value:
            out.append(
                Discrepancy(
                    kind=DiscrepancyKind.DUPLICATE_SIDE_EFFECT,
                    call_seq=None,
                    agent_saw=f"{len(finding.call_seqs)} create call(s) committed",
                    actually=finding.message,
                    source="oracle",
                )
            )
    return out


def _mission(report: AgentRunReport | None) -> str | None:
    if report is None:
        return None
    for message in report.agent.messages:
        if message.role == "user":
            return message.content
    return None


def _external_view(run: TargetRunEvidence) -> ExternalTargetView | None:
    record = run.external
    if record is None:
        return None
    return ExternalTargetView(
        agent_id=record.agent_id,
        name=record.name,
        agent_version=record.agent_version,
        protocol=record.protocol,
        uses_model=record.model_calls > 0,
        execution_mode=record.environment.execution_mode if record.environment else "not_started",
        bundle_sha256=record.bundle_sha256,
        transcript_sha256=record.transcript_sha256,
        model_calls=record.model_calls,
        model_calls_uncertain=sum(
            r.status is ModelCallStatus.UNCERTAIN for r in record.model_requests
        ),
        model_provider=record.model_identity.provider if record.model_identity else None,
        model_digest=record.model_identity.digest if record.model_identity else None,
    )


def _reality(
    run: TargetRunEvidence,
    experiment_id: str,
    report: AgentRunReport | None,
    finding: VerifiedFinding | None,
) -> RealityRun:
    world = _world(run)
    actual = _actual_summaries(report, world)
    notes = _notes(report)
    oracle = run.oracle
    claim = run.target_observed.claim
    flagged = set(_flagged_ids(oracle))
    matching = set(oracle.observation.objective_matching_ids)
    seeds = set(oracle.observation.seed_ids)
    mission = _mission(report)
    committed = run.committed
    claimed = claim.record_ref if claim is not None else None
    neutral = isinstance(claim, WorldClaim) or isinstance(committed, WorldCommittedSummary)
    return RealityRun(
        run_id=run.run_id,
        run_ref=run.run_ref,
        experiment_id=experiment_id,
        world_ref=run.authorized.scenario_id,
        scenario_ref=oracle.scenario_ref,
        config=run.authorized.config.value,
        target_kind=run.target_kind,
        target_evidence=run.evidence_source,
        reported_models=run.reported_models,
        verdict=oracle.verdict,
        run_outcome=run.run_outcome,
        finding_class=finding.finding_class if finding else None,
        impairments=finding.impairments if finding else [],
        faults=[
            FaultView(
                kind=f.kind.value, operation=f.operation, occurrence=f.occurrence, span=f.span
            )
            for f in run.authorized.faults
        ],
        faults_delivered=run.target_observed.faults_delivered,
        external=_external_view(run),
        agent=AgentReality(
            mission=bounded(mission, MAX_MESSAGE_CHARS) if mission else None,
            tool_events=[
                _tool_event(t, actual, notes, world) for t in run.target_observed.tool_trace
            ],
            termination=run.target_observed.termination,
            claim=ClaimView(
                status=claim.status.value,
                customer_id=None if neutral else claimed,
                message=bounded(claim.message, MAX_MESSAGE_CHARS),
                record_id=claimed if neutral else None,
            )
            if claim
            else None,
            disclosure=_disclosure(run),
            recovery_pattern=report.assessment.recovery.value if report else None,
        ),
        actual=ActualReality(
            customers=[
                CustomerView(
                    customer_id=c.customer_id,
                    name=c.name,
                    email=c.email,
                    metadata=cast(dict[str, JsonValue], dict(c.metadata)),
                    client_request_id=c.client_request_id,
                    created_by_call=c.created_by_call,
                    role="seed" if c.customer_id in seeds else "new",
                    objective_match=c.customer_id in matching,
                    flagged_duplicate=c.customer_id in flagged,
                    named_in_claim=claimed == c.customer_id,
                )
                for c in (committed.customers if isinstance(committed, CommittedSummary) else [])
            ],
            changes=[
                ChangeView(
                    change_seq=c.change_seq,
                    operation=c.operation,
                    customer_id=None if isinstance(c, WorldChange) else c.record_id,
                    created_by_call=c.created_by_call,
                    record_id=c.record_id if isinstance(c, WorldChange) else None,
                )
                for c in committed.changes
            ],
            new_customer_ids=[] if neutral else committed.new_ids,
            new_record_ids=committed.new_ids if neutral else [],
            records=_records(committed, seeds, matching, flagged, claimed),
            verdict=oracle.verdict,
            objective_satisfied=oracle.objective_satisfied,
            invariants_evaluated=[str(i) for i in oracle.invariants_evaluated],
            invariants_violated=[str(i) for i in oracle.invariants_violated],
            findings=[
                OracleFindingView(
                    code=str(f.code),
                    severity=f.severity,
                    invariant=str(f.invariant) if f.invariant else None,
                    message=f.message,
                    customer_ids=[] if neutral else f.record_ids,
                    call_seqs=f.call_seqs,
                    record_ids=f.record_ids if neutral else [],
                )
                for f in oracle.findings
            ],
        ),
        discrepancies=_discrepancies(run, actual),
        world=_world_view(run),
        validity=_validity_view(run),
    )


def _records(
    committed: CommittedSummary | WorldCommittedSummary,
    seeds: set[str],
    matching: set[str],
    flagged: set[str],
    claimed: str | None,
) -> list[RecordView]:
    if isinstance(committed, CommittedSummary):
        return []
    views: list[RecordView] = []
    for r in committed.records:
        history = r.attributes.get("status_history")
        views.append(
            RecordView(
                record_id=r.record_id,
                kind=r.kind,
                title=r.title,
                status=r.status,
                status_history=[str(s) for s in cast(list[JsonValue], history)]
                if isinstance(history, list)
                else [],
                identity_key=r.identity_key,
                attributes={k: v for k, v in r.attributes.items() if k != "status_history"},
                created_by_call=r.created_by_call,
                role="seed" if r.record_id in seeds else "new",
                objective_match=r.record_id in matching,
                flagged_duplicate=r.record_id in flagged,
                named_in_claim=claimed == r.record_id,
            )
        )
    return views


def _world_view(run: TargetRunEvidence) -> WorldView | None:
    """Only what the run recorded, read against the registered world. Refuses nothing old."""
    if run.world is None:
        return None
    descriptor = _world(run)
    violated = {str(i) for i in run.oracle.invariants_violated}
    evaluated = {str(i) for i in run.oracle.invariants_evaluated}
    return WorldView(
        world_type=run.world.world_type,
        name=descriptor.name,
        plugin_version=run.world.plugin_version,
        config_sha256=run.world.config_sha256,
        record_noun=descriptor.record_noun,
        store_noun=descriptor.store_noun,
        write_tool=descriptor.shape.write_tool,
        selected_tools=run.world.selected_tools,
        invariants=[
            InvariantView(
                invariant_id=i.invariant_id,
                scope=i.scope,
                description=i.description,
                violated=i.invariant_id in violated,
            )
            for i in descriptor.invariants
            if i.invariant_id in evaluated
        ],
    )


def _validity_view(run: TargetRunEvidence) -> ValidityView | None:
    if run.validity is None:
        return None
    return ValidityView(
        classification=run.validity.classification.value,
        faults=[
            FaultDeliveryView(
                kind=f.kind,
                operation=f.operation,
                occurrence=f.occurrence,
                trigger_reached=f.trigger_reached,
                delivered=f.delivered,
                delivered_at_calls=f.delivered_at_calls,
            )
            for f in run.validity.faults
        ],
        eligible_fault_kinds=run.validity.eligible_fault_kinds,
        not_exercised_fault_kinds=run.validity.not_exercised_fault_kinds,
    )


# --- timeline ---------------------------------------------------------------------------


class _Timeline:
    """Entries sort by source time, then by the order they were produced within one record."""

    def __init__(self) -> None:
        self._rows: list[tuple[datetime, int, dict[str, object]]] = []
        self._counter = 0

    def add(
        self,
        record: JournalRecord,
        journal: str,
        stage: TimelineStage,
        authorship: Authorship,
        title: str,
        *,
        detail: str | None = None,
        facts: Mapping[str, JsonValue] | None = None,
        precision: str = "exact",
        at: datetime | None = None,
        **refs: str | int | None,
    ) -> None:
        self._counter += 1
        when = at or record.at
        row: dict[str, object] = {
            "at": when,
            "at_precision": precision,
            "stage": stage,
            "authorship": authorship,
            "title": title,
            "detail": detail,
            "facts": dict(facts or {}),
            "evidence": EvidenceRef.model_validate(
                {
                    "journal": journal,
                    "journal_seq": record.seq,
                    "record_sha256": record.sha256,
                    **refs,
                }
            ),
        }
        self._rows.append((when, self._counter, row))

    def entries(self) -> list[TimelineEntry]:
        ordered = sorted(self._rows, key=lambda r: (r[0], r[1]))
        return [
            TimelineEntry.model_validate({"seq": index, **row})
            for index, (_, _, row) in enumerate(ordered, start=1)
        ]


def _author(report: InvestigationReport) -> str:
    """Who wrote the Investigator's part. A fixture is never called a model."""
    return "Fixture" if report.model_evidence_source == "offline_fixture" else "Model"


def _hypothesis_stage(report: InvestigationReport, hypothesis_id: str) -> TimelineStage:
    record = next(
        (h for h in report.hypotheses if h.hypothesis.hypothesis_id == hypothesis_id), None
    )
    if record is not None and record.hypothesis.revises:
        return TimelineStage.HYPOTHESIS_REVISED
    return TimelineStage.HYPOTHESIS_CREATED


def _add_propose(
    line: _Timeline,
    record: JournalRecord,
    report: InvestigationReport,
    proposals: Mapping[str, ProposalRecord],
) -> None:
    hypothesis_id = record.payload.get("hypothesis_id")
    proposal_id = record.payload.get("proposal_id")
    hypothesis = next(
        (h.hypothesis for h in report.hypotheses if h.hypothesis.hypothesis_id == hypothesis_id),
        None,
    )
    if hypothesis is not None:
        line.add(
            record,
            "investigation",
            _hypothesis_stage(report, hypothesis.hypothesis_id),
            Authorship.MODEL,
            f"Hypothesis {hypothesis.hypothesis_id}, revising {hypothesis.revises}"
            if hypothesis.revises
            else f"Hypothesis {hypothesis.hypothesis_id}",
            detail=hypothesis.behavior,
            facts={
                "cited_observations": list(hypothesis.motivating_observations),
                "revises": hypothesis.revises,
            },
            hypothesis_id=hypothesis.hypothesis_id,
        )
    proposal = proposals.get(str(proposal_id))
    if proposal is not None:
        line.add(
            record,
            "investigation",
            TimelineStage.EXPERIMENT_GENERATED,
            Authorship.MODEL
            if proposal.authorship is ExperimentAuthorship.MODEL_GENERATED
            else Authorship.COORDINATOR,
            f"Experiment {proposal.label or proposal.proposal_id}",
            detail=proposal.rationale,
            facts={"authorship": proposal.authorship.value, "bytes": proposal.source_bytes},
            proposal_id=proposal.proposal_id,
            hypothesis_id=proposal.hypothesis_id,
        )


def _assessment_decisions(report: InvestigationReport) -> dict[int, list[str]]:
    """Which decision delivered each assessment.

    The workflow assesses a hypothesis in the next model decision after its experiment.
    """
    placed: dict[int, list[str]] = {}
    decisions = [
        d for d in report.decisions if d.kind in {DecisionKind.PROPOSE, DecisionKind.CONCLUDE}
    ]
    for record in report.hypotheses:
        if record.assessment is None:
            continue
        own = next(
            (d for d in decisions if d.hypothesis_id == record.hypothesis.hypothesis_id), None
        )
        later = [d for d in decisions if own is not None and d.seq > own.seq]
        if later:
            placed.setdefault(later[0].seq, []).append(record.hypothesis.hypothesis_id)
    return placed


def _add_assessments(
    line: _Timeline, record: JournalRecord, report: InvestigationReport, ids: list[str]
) -> None:
    for hypothesis_id in ids:
        held = next(h for h in report.hypotheses if h.hypothesis.hypothesis_id == hypothesis_id)
        assessment = held.assessment
        if assessment is None:  # pragma: no cover - placed only when present
            continue
        line.add(
            record,
            "investigation",
            TimelineStage.HYPOTHESIS_ASSESSED,
            Authorship.MODEL,
            f"Hypothesis {hypothesis_id} assessed as {assessment.status}",
            detail=assessment.reasoning,
            facts={"cited_observations": list(assessment.cited_observations)},
            hypothesis_id=hypothesis_id,
        )


def _investigation_entries(
    line: _Timeline,
    records: list[JournalRecord],
    report: InvestigationReport,
) -> None:
    proposals = {p.proposal_id: p for p in report.proposals}
    assessments = _assessment_decisions(report)
    for record in records:
        payload = record.payload
        match record.kind:
            case "investigation_created":
                line.add(
                    record,
                    "investigation",
                    TimelineStage.INVESTIGATION_CREATED,
                    Authorship.COORDINATOR,
                    "Investigation created",
                    detail=report.request.objective,
                    facts={
                        "strategy": report.request.strategy.value,
                        "worlds": list(report.request.world_ids),
                    },
                )
            case "model_call_finished":
                line.add(
                    record,
                    "investigation",
                    TimelineStage.MODEL_CALL,
                    Authorship.COORDINATOR,
                    f"Investigator model call {payload.get('seq')}",
                    facts={
                        "outcome": payload.get("outcome"),
                        "evidence_source": payload.get("evidence_source"),
                        "prompt_tokens": payload.get("prompt_tokens"),
                        "completion_tokens": payload.get("completion_tokens"),
                        "latency_ms": payload.get("latency_ms"),
                    },
                )
            case "decision":
                _add_decision(line, record, report, proposals, assessments)
            case "experiment_linked":
                _add_observation(line, record, report)
            case "investigation_finished":
                line.add(
                    record,
                    "investigation",
                    TimelineStage.INVESTIGATION_FINISHED,
                    Authorship.COORDINATOR,
                    f"Investigation finished: {payload.get('state')}",
                    detail=report.statement,
                    facts={"termination": report.termination},
                )
            case _:
                continue


def _add_decision(
    line: _Timeline,
    record: JournalRecord,
    report: InvestigationReport,
    proposals: Mapping[str, ProposalRecord],
    assessments: Mapping[int, list[str]],
) -> None:
    payload = record.payload
    kind = str(payload.get("kind"))
    seq = int(cast(int, payload.get("seq")))
    _add_assessments(line, record, report, assessments.get(seq, []))
    if kind == DecisionKind.PROPOSE.value:
        _add_propose(line, record, report, proposals)
    elif kind == DecisionKind.CONCLUDE.value:
        conclusion = report.model_conclusion
        line.add(
            record,
            "investigation",
            TimelineStage.CONCLUSION,
            Authorship.MODEL,
            f"{_author(report)} concluded: "
            f"{conclusion.conclusion if conclusion else 'none recorded'}",
            detail=conclusion.reasoning if conclusion else None,
            facts={"reason": payload.get("reason")},
        )
    elif kind in {DecisionKind.INVALID.value, DecisionKind.REFINE.value}:
        proposal = proposals.get(str(payload.get("proposal_id")))
        line.add(
            record,
            "investigation",
            TimelineStage.EXPERIMENT_REJECTED,
            Authorship.COORDINATOR,
            "Generated output refused before execution",
            detail=proposal.rejection.problem if proposal and proposal.rejection else None,
            facts={"reason": payload.get("reason")},
            proposal_id=proposal.proposal_id if proposal else None,
        )


def _add_observation(line: _Timeline, record: JournalRecord, report: InvestigationReport) -> None:
    payload = record.payload
    observation_id = str(payload.get("observation_id"))
    observation = next((o for o in report.observations if o.observation_id == observation_id), None)
    result = observation.result_class.value if observation else "unknown"
    line.add(
        record,
        "investigation",
        TimelineStage.OBSERVATION,
        Authorship.COORDINATOR,
        f"Observation {observation_id}: {result}",
        facts={"result_class": result, "status": str(payload.get("status"))},
        observation_id=observation_id,
        experiment_id=str(payload.get("experiment_id")),
        proposal_id=str(payload.get("proposal_id")),
    )


def _add_step(line: _Timeline, record: JournalRecord, experiment_id: str) -> None:
    step = StepRecord.model_validate(record.payload)
    action = step.authorized_action or {}
    rejection = step.rejection.code.value if step.rejection else None
    attempts = len(step.sandbox)
    line.add(
        record,
        "experiment",
        TimelineStage.SANDBOX_EXECUTION,
        Authorship.SANDBOX,
        f"Sandbox step {step.step}: {action.get('action') or step.decision.value}",
        facts={
            "decision": step.decision.value,
            "rejection": rejection,
            "attempts": attempts,
            "network_enabled": any(s.network_enabled for s in step.sandbox),
            "duration_ms": sum(s.duration_ms for s in step.sandbox),
        },
        # When the step began, as recorded: its completion comes after any run it asked for.
        at=step.started_at,
        experiment_id=experiment_id,
    )


def _add_run_finished(line: _Timeline, record: JournalRecord, experiment_id: str) -> None:
    run = TargetRunEvidence.model_validate(record.payload)
    for entry in run.target_observed.tool_trace:
        line.add(
            record,
            "experiment",
            TimelineStage.TOOL_INTERACTION,
            Authorship.GATEWAY,
            f"Call {entry.call_seq}: {entry.tool}",
            detail=summarize_response(entry.delivered),
            facts={"ok": entry.delivered.ok},
            precision="run_report",
            experiment_id=experiment_id,
            run_id=run.run_id,
            call_seq=entry.call_seq,
        )
        if entry.fault_injected:
            line.add(
                record,
                "experiment",
                TimelineStage.FAULT_DELIVERED,
                Authorship.GATEWAY,
                f"Fault delivered on call {entry.call_seq}: {entry.fault_injected}",
                facts={"fault": entry.fault_injected, "effect": entry.fault_effect},
                precision="run_report",
                experiment_id=experiment_id,
                run_id=run.run_id,
                call_seq=entry.call_seq,
            )
    claim = run.target_observed.claim
    line.add(
        record,
        "experiment",
        TimelineStage.TARGET_RUN_FINISHED,
        Authorship.TARGET,
        f"Target run ended: {run.target_observed.termination}",
        detail=f"Structured claim: {claim.status.value}" if claim else "No valid claim was made",
        facts={
            "claim_status": claim.status.value if claim else None,
            "tool_calls": len(run.target_observed.tool_trace),
            "faults_delivered": run.target_observed.faults_delivered,
            "total_tokens": run.tokens.total_tokens if run.tokens else None,
        },
        experiment_id=experiment_id,
        run_id=run.run_id,
    )
    line.add(
        record,
        "experiment",
        TimelineStage.ORACLE_VERDICT,
        Authorship.ORACLE,
        f"Oracle verdict: {run.oracle.verdict.value}",
        facts={
            "verdict": run.oracle.verdict.value,
            "run_outcome": run.run_outcome,
            "objective_satisfied": run.oracle.objective_satisfied,
            "invariants_violated": [str(i) for i in run.oracle.invariants_violated],
            "finding_codes": [str(f.code) for f in run.oracle.findings],
        },
        experiment_id=experiment_id,
        run_id=run.run_id,
    )


def _experiment_entries(line: _Timeline, loaded: _Loaded) -> None:
    experiment_id = loaded.evidence.experiment_id
    external = any(r.external is not None for r in loaded.evidence.target_runs)
    for record in loaded.journal:
        match record.kind:
            case "step_completed":
                _add_step(line, record, experiment_id)
            case "target_run_intent":
                authorized = cast(dict[str, JsonValue], record.payload["authorized"])
                faults = cast(list[dict[str, JsonValue]], authorized.get("faults") or [])
                line.add(
                    record,
                    "experiment",
                    TimelineStage.TARGET_RUN_STARTED,
                    Authorship.COORDINATOR,
                    f"Target run authorized in {authorized.get('scenario_id')}",
                    facts={
                        # An external agent's behavior is its own: it has no policy of ours.
                        "config": None if external else authorized.get("config"),
                        "faults": [str(f.get("kind")) for f in faults],
                    },
                    experiment_id=experiment_id,
                )
            case "target_run_finished":
                _add_run_finished(line, record, experiment_id)
            case _:
                continue


# --- whole bundle -----------------------------------------------------------------------


def primary_run(runs: list[RealityRun]) -> RealityRun | None:
    """The run to open first: a violation over anything else, then the most eventful."""
    if not runs:
        return None
    return max(
        runs,
        key=lambda r: (r.verdict.value == "VIOLATION", len(r.discrepancies), r.faults_delivered),
    )


def _outcome(report: InvestigationReport, statuses: list[ExperimentState]) -> ProductOutcome:
    classes = {f.finding_class for f in report.findings}
    if FindingClass.ORACLE_CONFIRMED_VIOLATION in classes:
        return ProductOutcome.VIOLATION_VERIFIED
    if FindingClass.IMPAIRED_VIOLATION in classes:
        return ProductOutcome.VIOLATION_IMPAIRED
    if ExperimentState.UNCERTAIN in statuses:
        return ProductOutcome.OUTCOME_UNCERTAIN
    match report.state:
        case InvestigationState.FAILED:
            return ProductOutcome.FAILED
        case InvestigationState.CANCELLED:
            return ProductOutcome.CANCELLED
        case InvestigationState.BUDGET_EXHAUSTED:
            return ProductOutcome.BUDGET_EXHAUSTED
        case InvestigationState.COMPLETED if report.findings and classes <= {
            FindingClass.CORRECT_RECOVERY,
            FindingClass.CLEAN_SUCCESS,
        }:
            return ProductOutcome.NO_VIOLATION_FOUND
        case _:
            # An inconclusive state, a shortfall, an impaired run or no runs at all. A run with no
            # claim lands here too: nothing may read as success by default.
            return ProductOutcome.INCONCLUSIVE


def _adaptation(report: InvestigationReport, proposal: ProposalRecord) -> AdaptationKind:
    if proposal.authorship is ExperimentAuthorship.DEVELOPER_SCRIPT:
        return AdaptationKind.PREDETERMINED_PROGRAM
    if report.request.strategy is Strategy.ONE_SHOT:
        return AdaptationKind.PLANNED_WITHOUT_RESULTS
    if proposal.motivated_by:
        return AdaptationKind.CITED_PRIOR_OBSERVATIONS
    return AdaptationKind.FIRST_EXPERIMENT


def _proposal_view(
    report: InvestigationReport, proposal: ProposalRecord, directory: Path
) -> ProposalView:
    code = None
    if proposal.source_path is not None:
        source = directory / proposal.source_path
        text = source.read_text(encoding="utf-8")
        if sha256_text(text) != proposal.source_sha256:
            raise EvidenceRefusedError(f"{proposal.proposal_id}: source does not match its hash")
        code = bounded(text, MAX_CODE_CHARS)
    return ProposalView(
        proposal_id=proposal.proposal_id,
        hypothesis_id=proposal.hypothesis_id,
        label=proposal.label,
        rationale=proposal.rationale,
        status="executed"
        if proposal.status is ProposalStatus.EXECUTED
        else "rejected_before_execution",
        authorship=proposal.authorship.value,
        adaptation=_adaptation(report, proposal),
        motivated_by=proposal.motivated_by,
        rejection_problem=proposal.rejection.problem if proposal.rejection else None,
        replaces_proposal_id=proposal.replaces_proposal_id,
        code=code,
        code_sha256=proposal.source_sha256,
    )


def _finding_view(finding: VerifiedFinding) -> FindingView:
    return FindingView(
        experiment_id=finding.experiment_id,
        run_id=finding.run_id,
        world_ref=finding.world_ref,
        config=finding.config.value,
        finding_class=finding.finding_class,
        oracle_verdict=finding.oracle_verdict,
        run_outcome=finding.run_outcome,
        termination=finding.termination,
        violation_codes=finding.violation_codes,
        faults_delivered=finding.faults_delivered,
        target_evidence=finding.target_evidence_source,
        reproduction=finding.reproduction,
        impairments=finding.impairments,
        eligible_for_rate=finding.eligible_for_rate,
    )


def _experiment_view(report: InvestigationReport, loaded: _Loaded) -> ExperimentView:
    evidence = loaded.evidence
    ref = next(r for r in report.experiments if r.experiment_id == evidence.experiment_id)
    return ExperimentView(
        experiment_id=evidence.experiment_id,
        proposal_id=ref.proposal_id,
        observation_id=ref.observation_id,
        label=evidence.label,
        status=evidence.status.value,
        termination=evidence.termination.value,
        result_class=ref.result_class,
        target_run_ids=ref.target_run_ids,
        reproduction_of=ref.reproduction_of,
        sandbox_executions=evidence.usage.sandbox_executions,
        sandbox_network_enabled=any(
            s.network_enabled for step in evidence.steps for s in step.sandbox
        ),
        total_tokens=evidence.usage.total_tokens,
        estimated_cost_usd=evidence.usage.estimated_cost_usd,
        wall_ms=evidence.usage.wall_ms,
    )


def _summary(
    report: InvestigationReport,
    loaded: list[_Loaded],
    mode: ExecutionMode,
    case: CaseNote | None,
) -> InvestigationSummary:
    runs = [r for item in loaded for r in item.evidence.target_runs]
    codes: list[str] = []
    for finding in report.findings:
        codes.extend(c for c in finding.violation_codes if c not in codes)
    usage = report.usage
    recorded = next((r for r in runs if r.world is not None), None)
    return InvestigationSummary(
        investigation_id=report.investigation_id,
        world_name=_world(recorded).name if recorded is not None else None,
        mode=mode,
        case=case,
        outcome=_outcome(report, [i.evidence.status for i in loaded]),
        state=report.state,
        termination=report.termination,
        strategy=report.request.strategy,
        tier=report.request.tier,
        world_ids=list(report.request.world_ids),
        investigator_model=report.request.investigator_model,
        target_model=report.request.target_model,
        investigator_evidence=report.model_evidence_source,
        target_evidence=sorted({r.evidence_source for r in runs}),
        experiment_count=len(report.experiments),
        target_run_count=len(runs),
        verified_finding_count=sum(
            f.finding_class is FindingClass.ORACLE_CONFIRMED_VIOLATION for f in report.findings
        ),
        violation_codes=codes,
        started_at=report.started_at,
        finished_at=report.finished_at,
        runtime_ms=usage.wall_ms,
        estimated_cost_usd=round(usage.investigator_cost_usd + usage.target_cost_usd, 6),
        usage_complete=usage.usage_complete,
        cost_note=usage.note,
    )


def build_bundle(
    directory: Path,
    experiment_root: Path,
    *,
    mode: ExecutionMode,
    case: CaseNote | None = None,
    case_study: CaseStudy | None = None,
) -> InvestigationBundle:
    """Project one finished investigation. Raises ``EvidenceRefusedError`` rather than guess."""
    problems = verify_investigation(directory, experiment_root)
    if problems:
        raise EvidenceRefusedError(f"source does not verify: {'; '.join(problems)[:300]}")
    report_text = (directory / REPORT).read_text(encoding="utf-8")
    try:
        report = InvestigationReport.model_validate_json(report_text)
        journal, journal_problems = read_journal(directory / JOURNAL)
        loaded = [
            _load_experiment(experiment_root / ref.experiment_id) for ref in report.experiments
        ]
    except (OSError, ValidationError) as exc:
        raise EvidenceRefusedError(f"source is unreadable: {type(exc).__name__}") from exc
    if journal_problems or not journal:
        raise EvidenceRefusedError("investigation journal does not verify")
    for item in loaded:
        if verify_experiment(experiment_root / item.evidence.experiment_id):
            raise EvidenceRefusedError(f"{item.evidence.experiment_id}: does not verify")

    line = _Timeline()
    _investigation_entries(line, journal, report)
    for item in loaded:
        _experiment_entries(line, item)

    findings = {f.run_id: f for f in report.findings}
    runs = [
        _reality(
            run, item.evidence.experiment_id, item.reports.get(run.run_id), findings.get(run.run_id)
        )
        for item in loaded
        for run in item.evidence.target_runs
    ]
    return InvestigationBundle(
        summary=_summary(report, loaded, mode, case),
        objective=report.request.objective,
        statement=report.statement,
        limitations=report.limitations,
        hypotheses=[
            HypothesisView(
                hypothesis_id=h.hypothesis.hypothesis_id,
                status=h.status,
                behavior=h.hypothesis.behavior,
                suspected_mechanism=h.hypothesis.suspected_mechanism,
                motivation=h.hypothesis.motivation,
                predicted_observation=h.hypothesis.predicted_observation,
                failure_discriminator=h.hypothesis.failure_discriminator,
                motivating_observations=h.hypothesis.motivating_observations,
                revises=h.hypothesis.revises,
                assessment_reasoning=h.assessment.reasoning if h.assessment else None,
                assessment_observations=h.assessment.cited_observations if h.assessment else [],
            )
            for h in report.hypotheses
        ],
        proposals=[_proposal_view(report, p, directory) for p in report.proposals],
        observations=[
            ObservationView(
                observation_id=o.observation_id,
                experiment_id=o.experiment_id,
                proposal_id=o.proposal_id,
                result_class=o.result_class,
                verdicts=[r.oracle.verdict for r in o.runs],
                claim_statuses=[r.target.claim_status for r in o.runs],
                faults_delivered=sum(r.delivered.faults_delivered for r in o.runs),
            )
            for o in report.observations
        ],
        experiments=[_experiment_view(report, item) for item in loaded],
        findings=[_finding_view(f) for f in report.findings],
        claim_checks=[
            ClaimCheckView(
                experiment_id=c.claim.experiment_id,
                finding_code=c.claim.finding_code,
                statement=c.claim.statement,
                supported=c.supported,
                reason=c.reason,
                fault_was_delivered=c.fault_was_delivered,
            )
            for c in report.claim_checks
        ],
        conclusion=ConclusionView(
            conclusion=report.model_conclusion.conclusion,
            reasoning=report.model_conclusion.reasoning,
        )
        if report.model_conclusion
        else None,
        runs=runs,
        timeline=line.entries(),
        case_study=case_study,
        validity=report.validity,
        provenance=Provenance(
            source_report_sha256=sha256_text(report_text),
            source_journal_head_sha256=journal[-1].sha256,
            source_journal_records=len(journal),
            capability_sha256=report.capability_sha256,
            experiments=[
                ExperimentProvenance(
                    experiment_id=item.evidence.experiment_id,
                    evidence_sha256=item.evidence_sha256,
                    journal_head_sha256=item.journal[-1].sha256,
                    run_report_sha256=item.report_hashes,
                )
                for item in loaded
            ],
        ),
    )
