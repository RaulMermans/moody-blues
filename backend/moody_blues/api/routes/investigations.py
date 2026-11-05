"""Read-only evidence. Serves projections only; there is no route to a raw record."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from moody_blues.api.deps import EvidenceDep, GateDep
from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.explorer import (
    ExperimentList,
    IntegrityState,
    InvestigationBundle,
    InvestigationDetail,
    InvestigationList,
    RealityRun,
    RunList,
    RunSummary,
    TimelinePage,
)
from moody_blues.explorer.projection import primary_run

router = APIRouter(prefix="/investigations", tags=["investigations"])
MAX_TIMELINE_PAGE = 500


def _bundle(
    investigation_id: str, request: Request, evidence: EvidenceDep, gate: GateDep
) -> InvestigationBundle:
    return evidence.get(investigation_id, operator=gate.is_operator(request))


@router.get("", response_model=InvestigationList)
def list_investigations(
    request: Request, evidence: EvidenceDep, gate: GateDep
) -> InvestigationList:
    return evidence.list(operator=gate.is_operator(request))


@router.get("/{investigation_id}", response_model=InvestigationDetail)
def get_investigation(
    investigation_id: str, request: Request, evidence: EvidenceDep, gate: GateDep
) -> InvestigationDetail:
    bundle = _bundle(investigation_id, request, evidence, gate)
    return InvestigationDetail(
        summary=bundle.summary,
        integrity=IntegrityState.VERIFIED,
        objective=bundle.objective,
        statement=bundle.statement,
        limitations=bundle.limitations,
        hypotheses=bundle.hypotheses,
        proposals=bundle.proposals,
        observations=bundle.observations,
        findings=bundle.findings,
        claim_checks=bundle.claim_checks,
        conclusion=bundle.conclusion,
        case_study=bundle.case_study,
        provenance=bundle.provenance,
    )


@router.get("/{investigation_id}/timeline", response_model=TimelinePage)
def get_timeline(
    investigation_id: str,
    request: Request,
    evidence: EvidenceDep,
    gate: GateDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_TIMELINE_PAGE)] = MAX_TIMELINE_PAGE,
) -> TimelinePage:
    bundle = _bundle(investigation_id, request, evidence, gate)
    return TimelinePage(
        investigation_id=investigation_id,
        total=len(bundle.timeline),
        offset=offset,
        entries=bundle.timeline[offset : offset + limit],
    )


@router.get("/{investigation_id}/experiments", response_model=ExperimentList)
def get_experiments(
    investigation_id: str, request: Request, evidence: EvidenceDep, gate: GateDep
) -> ExperimentList:
    bundle = _bundle(investigation_id, request, evidence, gate)
    return ExperimentList(investigation_id=investigation_id, experiments=bundle.experiments)


@router.get("/{investigation_id}/runs", response_model=RunList)
def get_runs(
    investigation_id: str, request: Request, evidence: EvidenceDep, gate: GateDep
) -> RunList:
    bundle = _bundle(investigation_id, request, evidence, gate)
    case = bundle.summary.case
    fallback = primary_run(bundle.runs)
    return RunList(
        investigation_id=investigation_id,
        primary_run_id=case.primary_run_id if case else (fallback.run_id if fallback else None),
        runs=[
            RunSummary(
                run_id=r.run_id,
                experiment_id=r.experiment_id,
                world_ref=r.world_ref,
                config=r.config,
                verdict=r.verdict,
                run_outcome=r.run_outcome,
                faults_delivered=r.faults_delivered,
            )
            for r in bundle.runs
        ],
    )


@router.get("/{investigation_id}/runs/{run_id}", response_model=RealityRun)
def get_run(
    investigation_id: str, run_id: str, request: Request, evidence: EvidenceDep, gate: GateDep
) -> RealityRun:
    """Agent events, authoritative state and Oracle findings for one run, side by side."""
    bundle = _bundle(investigation_id, request, evidence, gate)
    run = next((r for r in bundle.runs if r.run_id == run_id), None)
    if run is None:
        raise MoodyBluesError(ErrorCategory.NOT_FOUND, "no such run")
    return run
