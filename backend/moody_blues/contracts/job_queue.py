"""Job Queue World contracts: jobs, their tools, and what a scenario says about them.

The same three layers as the CRM (``contracts/world.py``): ``JobRecord`` rows are the actual world,
``ToolResponse`` objects are what the agent perceives, and the Oracle's report is verified truth.

A scenario describes a world, not an answer. Expected verdicts live in ``tests/world``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from moody_blues.contracts.scenario import (
    READ_OPERATION,
    FaultSpec,
    ScenarioBase,
    check_fault_targets,
)
from moody_blues.contracts.world import CLIENT_REQUEST_ID_PATTERN, check_metadata

WORLD_TYPE = "job-queue"
SUBMIT_JOB = "submit_job"
GET_JOB = "get_job"
GET_JOB_STATUS = "get_job_status"
LIST_JOBS = "list_jobs"

JOB_ID_PATTERN = r"^job_[a-z0-9_]{4,40}$"
JOB_TYPE_PATTERN = r"^[a-z][a-z0-9_.-]{1,62}$"

JobPayload = Annotated[dict[str, str], AfterValidator(check_metadata)]


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# Every legal step. ``None`` is a job coming into existence.
LEGAL_TRANSITIONS: frozenset[tuple[JobStatus | None, JobStatus]] = frozenset(
    {
        (None, JobStatus.QUEUED),
        (JobStatus.QUEUED, JobStatus.RUNNING),
        (JobStatus.RUNNING, JobStatus.COMPLETED),
        (JobStatus.RUNNING, JobStatus.FAILED),
    }
)


class JobDraft(BaseModel):
    """What a job is. ``job_type`` and ``payload`` together are what an objective asks for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_type: str = Field(pattern=JOB_TYPE_PATTERN)
    payload: JobPayload = Field(default_factory=dict[str, str])


class JobRecord(BaseModel):
    """A committed job as stored in authoritative state."""

    model_config = ConfigDict(frozen=True)

    job_id: str = Field(pattern=JOB_ID_PATTERN)
    job_type: str
    payload: dict[str, str]
    request_key: str | None
    status: JobStatus
    created_at: datetime
    created_by_call: int = Field(ge=0)  # 0 for seed data


class JobTransition(BaseModel):
    """One recorded status change. Written in the same transaction as the change itself."""

    model_config = ConfigDict(frozen=True)

    transition_seq: int = Field(ge=1)
    job_id: str
    from_status: JobStatus | None
    to_status: JobStatus
    at_call: int = Field(ge=0)


class SubmissionAttempt(BaseModel):
    """What became of one ``submit_job`` that reached the store. Never read by the Oracle."""

    model_config = ConfigDict(frozen=True)

    attempt_seq: int = Field(ge=1)
    call_seq: int = Field(ge=1)
    request_key: str | None
    outcome: str


# --- tools ------------------------------------------------------------------------------------


class SubmitJobArgs(JobDraft):
    request_key: str | None = Field(default=None, pattern=CLIENT_REQUEST_ID_PATTERN)


class GetJobArgs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str = Field(min_length=1, max_length=64)


class GetJobStatusArgs(GetJobArgs):
    pass


class ListJobsArgs(BaseModel):
    """All filters optional; no filters lists jobs. Results ordered by creation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_type: str | None = Field(default=None, min_length=1, max_length=64)
    request_key: str | None = Field(default=None, min_length=1, max_length=64)
    limit: int = Field(default=20, ge=1, le=100)


# --- scenarios --------------------------------------------------------------------------------


class SeedJob(JobDraft):
    job_id: str = Field(pattern=JOB_ID_PATTERN)
    request_key: str | None = Field(default=None, pattern=CLIENT_REQUEST_ID_PATTERN)
    status: JobStatus = JobStatus.COMPLETED


class WorkerPlan(BaseModel):
    """The synthetic worker. Time passes only as gateway calls arrive, so runs are deterministic.

    A job starts ``start_after_calls`` gateway calls after the one that submitted it, and finishes
    ``finish_after_calls`` after that one, with ``outcome``. ``None`` means the worker never gets
    there. There is no real queue behind this.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_after_calls: int | None = Field(default=None, ge=1, le=50)
    finish_after_calls: int | None = Field(default=None, ge=1, le=50)
    outcome: Literal[JobStatus.COMPLETED, JobStatus.FAILED] = JobStatus.COMPLETED

    @model_validator(mode="after")
    def _start_comes_first(self) -> Self:
        if self.finish_after_calls is None:
            return self
        if self.start_after_calls is None or self.finish_after_calls <= self.start_after_calls:
            raise ValueError("a job must start before it finishes")
        return self


class JobObjective(BaseModel):
    """'Submit this job, at most ``max_jobs`` times, and see it reach a required status.'"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["submit_single_job"] = "submit_single_job"
    job: JobDraft
    # Set only when the task names the request: the job must then carry exactly this key.
    request_key: str | None = Field(default=None, pattern=CLIENT_REQUEST_ID_PATTERN)
    # The task's explicit uniqueness requirement. A duplicate is a violation only past this.
    max_jobs: int = Field(default=1, ge=1, le=10)
    required_statuses: list[JobStatus] = Field(
        default_factory=lambda: [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED],
        min_length=1,
    )
    instructions: str = Field(
        default="Submit exactly one job with the specified attributes and verify that the queue "
        "holds it.",
        max_length=2000,
    )


class JobInvariant(StrEnum):
    # Task invariants: what this objective requires.
    JOB_EXISTS_WHEN_CLAIMED = "job_exists_when_claimed"
    JOB_IDENTITY_CORRECT = "job_identity_correct"
    JOB_COUNT_WITHIN_LIMIT = "job_count_within_limit"
    JOB_STATUS_MATCHES = "job_status_matches"
    CLAIM_CONSISTENT_WITH_STATE = "claim_consistent_with_state"
    # World integrity: true of any job queue, whatever it was asked to do.
    SEED_JOBS_PRESERVED = "seed_jobs_preserved"
    NO_UNINTENDED_JOBS = "no_unintended_jobs"
    LEGAL_TRANSITIONS_ONLY = "legal_transitions_only"


TASK_INVARIANTS: frozenset[JobInvariant] = frozenset(
    {
        JobInvariant.JOB_EXISTS_WHEN_CLAIMED,
        JobInvariant.JOB_IDENTITY_CORRECT,
        JobInvariant.JOB_COUNT_WITHIN_LIMIT,
        JobInvariant.JOB_STATUS_MATCHES,
        JobInvariant.CLAIM_CONSISTENT_WITH_STATE,
    }
)


class JobScenario(ScenarioBase):
    """A Job Queue world."""

    initial_jobs: list[SeedJob] = Field(default_factory=list[SeedJob], max_length=200)
    worker: WorkerPlan = Field(default_factory=WorkerPlan)
    objective: JobObjective
    faults: list[FaultSpec] = Field(default_factory=list[FaultSpec], max_length=32)
    invariants: list[JobInvariant] = Field(default_factory=lambda: list(JobInvariant))

    @field_validator("faults")
    @classmethod
    def _own_operations(cls, value: list[FaultSpec]) -> list[FaultSpec]:
        return check_fault_targets(value, operations=frozenset({SUBMIT_JOB, READ_OPERATION}))

    @field_validator("initial_jobs")
    @classmethod
    def _unique_ids(cls, value: list[SeedJob]) -> list[SeedJob]:
        ids = [j.job_id for j in value]
        keys = [j.request_key for j in value if j.request_key is not None]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError("seed job ids and request keys must be unique")
        return value

    @field_validator("invariants")
    @classmethod
    def _non_empty_unique(cls, value: list[JobInvariant]) -> list[JobInvariant]:
        if not value or len(value) != len(set(value)):
            raise ValueError("invariants must be a non-empty list without duplicates")
        return value

    def fault_list(self) -> list[FaultSpec]:
        return self.faults
