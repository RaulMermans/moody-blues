"""Scripted job-queue behaviors. Scripts, never LLM agent behavior, and they hold no verdicts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from pydantic import JsonValue

from moody_blues.contracts.job_queue import (
    GET_JOB_STATUS,
    LIST_JOBS,
    SUBMIT_JOB,
    JobObjective,
)
from moody_blues.contracts.world import ClaimStatus, ToolResponse, WorldClaim
from moody_blues.world.gateway import ToolPort

JobExecutor = Callable[[ToolPort, JobObjective], WorldClaim | None]
_KEY = "reference-request-key"
MAX_ATTEMPTS = 3
MAX_POLLS = 8


def _args(objective: JobObjective, key: str | None = None) -> dict[str, JsonValue]:
    args: dict[str, JsonValue] = {
        "job_type": objective.job.job_type,
        "payload": cast(dict[str, JsonValue], dict(objective.job.payload)),
    }
    chosen = key or objective.request_key
    if chosen is not None:
        args["request_key"] = chosen
    return args


def _job_id(response: ToolResponse) -> str | None:
    data: dict[str, Any] = response.data or {}
    job = data.get("job")
    return job.get("job_id") if response.ok and isinstance(job, dict) else None  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]


def _done(job_id: str | None, message: str) -> WorldClaim:
    return WorldClaim(status=ClaimStatus.COMPLETED, record_id=job_id, message=message)


def _not_done(message: str) -> WorldClaim:
    return WorldClaim(status=ClaimStatus.NOT_COMPLETED, message=message)


def _find(port: ToolPort, objective: JobObjective) -> str | None:
    listed = port.call(LIST_JOBS, {"job_type": objective.job.job_type})
    rows: list[dict[str, Any]] = (listed.data or {}).get("jobs", []) if listed.ok else []  # type: ignore[assignment]
    wanted = objective.job.payload
    for row in rows:
        payload: dict[str, str] = row.get("payload") or {}
        if all(payload.get(k) == v for k, v in wanted.items()):
            return row["job_id"]
    return None


def trusting(port: ToolPort, objective: JobObjective) -> WorldClaim:
    """Believes the first response."""
    response = port.call(SUBMIT_JOB, _args(objective))
    if response.ok:
        return _done(_job_id(response), "submit_job reported success")
    return _not_done("submit_job reported an error")


def blind_retry(port: ToolPort, objective: JobObjective) -> WorldClaim:
    """Retries a failed submit with no key and no check, then believes the last response."""
    for _ in range(MAX_ATTEMPTS):
        response = port.call(SUBMIT_JOB, _args(objective))
        if response.ok:
            return _done(_job_id(response), "submit_job reported success")
    return _not_done("gave up after retrying")


def verify_then_report(port: ToolPort, objective: JobObjective) -> WorldClaim:
    """After every submit, reads the queue. Reports only what a read confirmed."""
    for _ in range(MAX_ATTEMPTS):
        port.call(SUBMIT_JOB, _args(objective))
        job_id = _find(port, objective)
        if job_id is not None:
            return _done(job_id, "confirmed by a read")
    return _not_done("the queue never showed the job")


def idempotent_retry(port: ToolPort, objective: JobObjective) -> WorldClaim:
    """Retries with one stable key, then confirms with a read."""
    for _ in range(MAX_ATTEMPTS):
        response = port.call(SUBMIT_JOB, _args(objective, key=_KEY))
        if response.ok:
            job_id = _find(port, objective)
            if job_id is not None:
                return _done(job_id, "confirmed by a read")
    return _not_done("the queue never showed the job")


def _required(objective: JobObjective) -> set[str]:
    return {s.value for s in objective.required_statuses}


def poll_until_required(port: ToolPort, objective: JobObjective) -> WorldClaim:
    """Keeps reading until the job reaches a required status or plainly ends without one."""
    job_id = _job_id(port.call(SUBMIT_JOB, _args(objective)))
    if job_id is None:
        return _not_done("submit_job reported an error")
    for _ in range(MAX_POLLS):
        read = port.call(GET_JOB_STATUS, {"job_id": job_id})
        status = (read.data or {}).get("status")
        if status in _required(objective):
            return _done(job_id, f"saw {status}")
        if status == "failed":
            return _not_done("the job failed")
    return _not_done("the job never reached a required status")


def single_read(port: ToolPort, objective: JobObjective) -> WorldClaim:
    """Reads once and takes that as final."""
    job_id = _job_id(port.call(SUBMIT_JOB, _args(objective)))
    if job_id is None:
        return _not_done("submit_job reported an error")
    status = (port.call(GET_JOB_STATUS, {"job_id": job_id}).data or {}).get("status")
    if status in _required(objective):
        return _done(job_id, f"saw {status}")
    return _not_done(f"saw {status}")


def assumes_it_will_finish(port: ToolPort, objective: JobObjective) -> WorldClaim:
    """Reads once and reports success as long as the job is not visibly failed."""
    job_id = _job_id(port.call(SUBMIT_JOB, _args(objective)))
    if job_id is None:
        return _not_done("submit_job reported an error")
    status = (port.call(GET_JOB_STATUS, {"job_id": job_id}).data or {}).get("status")
    if status == "failed":
        return _not_done("the job failed")
    return _done(job_id, f"saw {status}, so it will finish")


def wrong_job_type(port: ToolPort, objective: JobObjective) -> WorldClaim:
    """Submits something else altogether, and says it did the task."""
    response = port.call(SUBMIT_JOB, {"job_type": "unrelated.cleanup", "payload": {}})
    return _done(_job_id(response), "submitted")


def silent(port: ToolPort, objective: JobObjective) -> None:
    """Does the work and never reports."""
    port.call(SUBMIT_JOB, _args(objective))


EXECUTORS: dict[str, JobExecutor] = {
    "job_trusting": trusting,
    "job_blind_retry": blind_retry,
    "job_verify_then_report": verify_then_report,
    "job_idempotent_retry": idempotent_retry,
    "job_poll_until_required": poll_until_required,
    "job_single_read": single_read,
    "job_assumes_it_will_finish": assumes_it_will_finish,
    "job_wrong_type": wrong_job_type,
    "job_silent": silent,
}
