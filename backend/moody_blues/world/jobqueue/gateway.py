"""The queue's tools, on the shared gateway pipeline.

Call order, evidence events and both fault boundaries come from ``GatewayCore``. What is here is
what a job queue does: ``submit_job`` writes, and the three reads report. The synthetic worker
runs in ``_before_call``, because in this world time passes only as calls arrive.

``stale_read`` keeps its global meaning: a lagging replica. In a CRM that hides a row; here it shows
a job as it stood when it was committed, hiding the transitions since. Nothing is written.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, JsonValue

from moody_blues.contracts.job_queue import (
    GET_JOB,
    GET_JOB_STATUS,
    LIST_JOBS,
    SUBMIT_JOB,
    GetJobArgs,
    GetJobStatusArgs,
    JobRecord,
    JobStatus,
    ListJobsArgs,
    SubmitJobArgs,
    WorkerPlan,
)
from moody_blues.contracts.scenario import READ_OPERATION, FaultKind, FaultSpec
from moody_blues.contracts.world import EventKind, ToolErrorCode, ToolResponse
from moody_blues.world.gateway import (
    CallContext,
    GatewayCore,
    WriteResult,
    error_response,
    ok_response,
)
from moody_blues.world.jobqueue.store import JobInsertResult, JobStore
from moody_blues.world.store import BeforeCommit, WriteOutcome

ARG_MODELS: dict[str, type[BaseModel]] = {
    SUBMIT_JOB: SubmitJobArgs,
    GET_JOB: GetJobArgs,
    GET_JOB_STATUS: GetJobStatusArgs,
    LIST_JOBS: ListJobsArgs,
}

DESCRIPTIONS: dict[str, str] = {
    SUBMIT_JOB: (
        "Submit a job to the queue. Jobs are not unique by type or payload. Pass a request_key to "
        "make retries idempotent: repeating a request with the same key and attributes returns "
        "the original job instead of creating another."
    ),
    GET_JOB: "Fetch one job by job_id.",
    GET_JOB_STATUS: "Fetch the current status of one job by job_id.",
    LIST_JOBS: (
        "List jobs, optionally filtered by exact job_type and/or request_key, in creation order."
    ),
}


def derive_job_id(seed: int, call_seq: int) -> str:
    """Deterministic, unique per call. A phantom id is never reused by a later real submit."""
    digest = hashlib.sha256(f"moody-blues:job:{seed}:{call_seq}".encode()).hexdigest()
    return f"job_{digest[:16]}"


def agent_view(record: JobRecord, *, status: JobStatus | None = None) -> dict[str, JsonValue]:
    """The job as shown to agents: internal provenance (``created_by_call``) omitted."""
    shown = record.model_dump(mode="json", exclude={"created_by_call"})
    return shown if status is None else shown | {"status": status.value}


class JobGateway(GatewayCore):
    def __init__(
        self,
        store: JobStore,
        *,
        seed: int,
        worker: WorkerPlan,
        faults: list[FaultSpec],
        clock: Callable[[int], datetime],
    ) -> None:
        super().__init__(store, arg_models=ARG_MODELS, faults=faults, clock=clock)
        self._store = store
        self._seed = seed
        self._worker = worker

    def _before_call(self, call_seq: int, now: datetime) -> None:
        plan = self._worker
        for job in self._store.all_jobs():
            if job.created_by_call == 0:  # seed jobs belong to no worker of this run
                continue
            age = call_seq - job.created_by_call
            status = job.status
            if (
                status is JobStatus.QUEUED
                and plan.start_after_calls is not None
                and age >= plan.start_after_calls
            ):
                status = JobStatus.RUNNING
                self._store.advance(job.job_id, status, call_seq=call_seq)
            if (
                status is JobStatus.RUNNING
                and plan.finish_after_calls is not None
                and age >= plan.finish_after_calls
            ):
                self._store.advance(job.job_id, JobStatus(plan.outcome), call_seq=call_seq)

    def _execute(self, tool: str, args: BaseModel, ctx: CallContext) -> ToolResponse:
        match args:
            case SubmitJobArgs():
                return self._submit(args, ctx)
            case GetJobStatusArgs() | GetJobArgs() | ListJobsArgs():
                return self._read(tool, args, ctx)
            case _:  # pragma: no cover - ARG_MODELS is exhaustive
                raise AssertionError(f"unhandled tool {tool}")

    def _read(self, tool: str, args: GetJobArgs | ListJobsArgs, ctx: CallContext) -> ToolResponse:
        target = self._faults.next_execution(READ_OPERATION)
        if isinstance(args, ListJobsArgs):
            rows = self._store.list_jobs(
                job_type=args.job_type, request_key=args.request_key, limit=args.limit
            )
            ctx.emit(
                EventKind.OPERATION_EXECUTED,
                {"tool": tool, "outcome": "read", "result_count": len(rows)},
            )
        else:
            found = self._store.get_job(args.job_id)
            rows = [] if found is None else [found]
            ctx.emit(
                EventKind.OPERATION_EXECUTED,
                {"tool": tool, "outcome": "read", "found": found is not None},
            )

        def respond(statuses: dict[str, JobStatus]) -> ToolResponse:
            if tool == LIST_JOBS:
                data: dict[str, JsonValue] = {
                    "jobs": [agent_view(r, status=statuses[r.job_id]) for r in rows],
                    "count": len(rows),
                }
                return ok_response(ctx.call_id, tool, data)
            if not rows:
                return error_response(ctx.call_id, tool, ToolErrorCode.NOT_FOUND, "job not found")
            job = rows[0]
            if tool == GET_JOB_STATUS:
                return ok_response(
                    ctx.call_id,
                    tool,
                    {"job_id": job.job_id, "status": statuses[job.job_id].value},
                )
            return ok_response(
                ctx.call_id, tool, {"job": agent_view(job, status=statuses[job.job_id])}
            )

        current = {r.job_id: r.status for r in rows}
        lagging = {r.job_id: self._store.status_at_commit(r.job_id) or r.status for r in rows}
        return self._faulted_read(
            ctx,
            target=target,
            actual=respond(current),
            hidden=sum(1 for job_id, status in current.items() if lagging[job_id] is not status),
            stale=lambda: respond(lagging),
        )

    def _submit(self, args: SubmitJobArgs, ctx: CallContext) -> ToolResponse:
        record = JobRecord(
            job_id=derive_job_id(self._seed, ctx.call_seq),
            job_type=args.job_type,
            payload=args.payload,
            request_key=args.request_key,
            status=JobStatus.QUEUED,
            created_at=ctx.now,
            created_by_call=ctx.call_seq,
        )

        def perform(before_commit: BeforeCommit) -> WriteResult:
            result = self._store.insert_job(record, before_commit=before_commit)
            self._store.record_attempt(
                call_seq=ctx.call_seq, request_key=args.request_key, outcome=result.outcome.value
            )
            return WriteResult(
                outcome=result.outcome.value,
                facts={"result_job_id": result.record.job_id if result.record else None},
                actual=self._actual_response(ctx.call_id, result),
            )

        return self._faulted_write(
            ctx,
            operation=SUBMIT_JOB,
            attempted={"attempted_job_id": record.job_id},
            perform=perform,
            failed=error_response(
                ctx.call_id,
                SUBMIT_JOB,
                ToolErrorCode.INTERNAL_ERROR,
                "the job could not be saved; nothing was written",
                retryable=True,
            ),
            distort=lambda fault: self._distort(ctx.call_id, fault, record),
        )

    @staticmethod
    def _actual_response(call_id: str, result: JobInsertResult) -> ToolResponse:
        match result.outcome:
            case WriteOutcome.COMMITTED | WriteOutcome.IDEMPOTENT_REPLAY:
                if result.record is None:  # pragma: no cover - store invariant
                    raise RuntimeError("store returned a success outcome without a record")
                return ok_response(
                    call_id,
                    SUBMIT_JOB,
                    {
                        "job": agent_view(result.record),
                        "idempotent_replay": result.outcome is WriteOutcome.IDEMPOTENT_REPLAY,
                    },
                )
            case WriteOutcome.IDEMPOTENCY_CONFLICT:
                return error_response(
                    call_id,
                    SUBMIT_JOB,
                    ToolErrorCode.IDEMPOTENCY_CONFLICT,
                    "request_key was already used with different attributes",
                )
            case WriteOutcome.ABORTED_PRE_COMMIT:
                # Only a fault aborts; its distortion replaces this. Kept honest regardless.
                return error_response(
                    call_id,
                    SUBMIT_JOB,
                    ToolErrorCode.INTERNAL_ERROR,
                    "the job was not saved",
                    retryable=True,
                )

    @staticmethod
    def _distort(call_id: str, fault: FaultSpec, attempted: JobRecord) -> ToolResponse:
        """The delivered response depends only on the fault, never on the actual outcome."""
        match fault.kind:
            case FaultKind.PHANTOM_FAILURE:
                return error_response(
                    call_id, SUBMIT_JOB, fault.error_code, fault.error_message, retryable=True
                )
            case FaultKind.PHANTOM_SUCCESS:
                # Indistinguishable in shape from a genuine success; the id was never committed.
                return ok_response(
                    call_id,
                    SUBMIT_JOB,
                    {"job": agent_view(attempted), "idempotent_replay": False},
                )
            case FaultKind.STALE_READ:  # pragma: no cover - reads are handled by ``_read``
                raise AssertionError("stale_read does not target writes")
