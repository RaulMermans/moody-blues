"""Authorized, bounded investigation runs. Every route here requires the operator token.

A request can only name a mission id from the closed catalog. Admission checks run before a job
exists, in this order: authorized, known mission, enabled, affordable, nothing else running.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from moody_blues.api.deps import JobsDep, SettingsDep, require_operator
from moody_blues.config import Settings
from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.explorer import (
    TERMINAL_JOB_STATES,
    BudgetView,
    ExecutionMode,
    JobEvent,
    JobRecord,
    JobView,
    LiveStatus,
    MissionView,
    StartJob,
)
from moody_blues.experiments.budget import BudgetExceededError
from moody_blues.explorer.factories import ledger_for
from moody_blues.explorer.jobs import JobManager
from moody_blues.explorer.missions import MISSIONS, Mission, find_mission
from moody_blues.explorer.paths import artifacts_dir

router = APIRouter(prefix="/operator", tags=["operator"], dependencies=[Depends(require_operator)])

_STREAM_POLL_SECONDS = 0.5
_HEARTBEAT_SECONDS = 15.0
_MAX_STREAM_SECONDS = 3_600.0


def _budget(settings: Settings) -> tuple[BudgetView | None, str | None]:
    try:
        status = ledger_for(settings, artifacts_dir(settings)).status()
    except BudgetExceededError:
        return None, "ledger_unreadable"
    view = BudgetView(
        limit_usd=status.limit_usd,
        settled_usd=status.settled_usd,
        open_reservations_usd=status.open_reservations_usd,
        remaining_usd=status.remaining_usd,
        required_usd=settings.investigator_max_spend_usd,
        note=status.note,
    )
    return view, None


def _blocked_by(mission: Mission, settings: Settings, jobs: JobManager) -> str | None:
    if jobs.active_job_id is not None:
        return "another_job_running"
    if mission.mode is not ExecutionMode.LIVE:
        return None
    if not settings.live_runs_enabled:
        return "live_runs_disabled"
    if not settings.vultr_configured:
        return "provider_not_configured"
    budget, problem = _budget(settings)
    if budget is None:
        return problem
    if budget.remaining_usd < budget.required_usd:
        return "budget_insufficient"
    return None


@router.get("/session")
def get_session() -> dict[str, bool]:
    """Lets the server-side layer check a token without touching anything else."""
    return {"operator": True}


@router.get("/status", response_model=LiveStatus)
def get_status(settings: SettingsDep, jobs: JobsDep) -> LiveStatus:
    budget, problem = _budget(settings)
    missions: list[MissionView] = []
    for mission in MISSIONS:
        blocked = _blocked_by(mission, settings, jobs)
        missions.append(
            MissionView(
                mission_id=mission.mission_id,
                mode=mission.mode,
                title=mission.title,
                description=mission.description,
                worlds=list(mission.worlds),
                max_experiments=mission.limits.max_experiments,
                available=blocked is None,
                blocked_by=blocked,
            )
        )
    return LiveStatus(
        live_enabled=settings.live_runs_enabled,
        budget=budget,
        budget_problem=problem,
        active_job_id=jobs.active_job_id,
        missions=missions,
    )


_REFUSALS: dict[str, tuple[ErrorCategory, str]] = {
    "another_job_running": (ErrorCategory.CONFLICT, "another investigation is running"),
    "live_runs_disabled": (ErrorCategory.FORBIDDEN, "live runs are disabled on this server"),
    "provider_not_configured": (
        ErrorCategory.PROVIDER_NOT_CONFIGURED,
        "no provider credentials are configured",
    ),
    "ledger_unreadable": (ErrorCategory.BUDGET_EXCEEDED, "the spend ledger is unreadable"),
    "budget_insufficient": (
        ErrorCategory.BUDGET_EXCEEDED,
        "the spend ledger does not cover one investigation",
    ),
}


@router.post("/jobs", status_code=202, response_model=JobRecord)
def start_job(body: StartJob, settings: SettingsDep, jobs: JobsDep) -> JobRecord:
    mission = find_mission(body.mission_id)
    if mission is None:
        raise MoodyBluesError(ErrorCategory.VALIDATION, "unknown mission")
    blocked = _blocked_by(mission, settings, jobs)
    if blocked is not None:
        category, message = _REFUSALS[blocked]
        raise MoodyBluesError(category, message)
    return jobs.start(mission)


@router.get("/jobs", response_model=list[JobRecord])
def list_jobs(jobs: JobsDep) -> list[JobRecord]:
    return jobs.store.all()


@router.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, jobs: JobsDep, after: Annotated[int, Query(ge=0)] = 0) -> JobView:
    """The polling path. Pass the last event id seen as ``after``."""
    return jobs.view(job_id, after=after)


@router.post("/jobs/{job_id}/cancel", status_code=202, response_model=JobRecord)
def cancel_job(job_id: str, jobs: JobsDep) -> JobRecord:
    return jobs.cancel(job_id)


def _frame(event: JobEvent) -> str:
    body = json.dumps(json.loads(event.model_dump_json()))
    return f"id: {event.event_id}\nevent: job\ndata: {body}\n\n"


async def _stream(jobs: JobManager, job_id: str, after: int) -> AsyncIterator[str]:
    last = after
    quiet = 0.0
    elapsed = 0.0
    while elapsed < _MAX_STREAM_SECONDS:
        view = await asyncio.to_thread(jobs.view, job_id, after=last)
        for event in view.events:
            last = event.event_id
            yield _frame(event)
            quiet = 0.0
        if view.job.status in TERMINAL_JOB_STATES:
            # The status can land a moment before its event. Stop only once the event is out.
            tail = await asyncio.to_thread(jobs.view, job_id, after=last)
            for event in tail.events:
                last = event.event_id
                yield _frame(event)
            yield "event: end\ndata: {}\n\n"
            return
        await asyncio.sleep(_STREAM_POLL_SECONDS)
        quiet += _STREAM_POLL_SECONDS
        elapsed += _STREAM_POLL_SECONDS
        if quiet >= _HEARTBEAT_SECONDS:
            quiet = 0.0
            yield ": heartbeat\n\n"


@router.get("/jobs/{job_id}/events")
def stream_events(
    job_id: str,
    jobs: JobsDep,
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Server-sent events with replay: reconnecting with ``Last-Event-ID`` resumes after it."""
    jobs.view(job_id)  # a clean 404 before the stream opens
    return StreamingResponse(
        _stream(jobs, job_id, last_event_id if last_event_id is not None else after),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )
