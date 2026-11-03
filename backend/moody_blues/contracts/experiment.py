"""Experiment request contract (foundational shape only; the Investigator arrives later)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from moody_blues.contracts.common import ExecutionStatus


class TargetAgent(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=4000)
    tools: list[str] = Field(default_factory=list[str])


class ExperimentRequest(BaseModel):
    """What the Investigator will be asked to examine."""

    model_config = ConfigDict(frozen=True)

    target: TargetAgent
    hypothesis: str | None = Field(default=None, max_length=4000)
    max_iterations: int = Field(default=1, ge=1, le=50)


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(default_factory=lambda: f"exp_{uuid4().hex[:12]}")
    request: ExperimentRequest
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
