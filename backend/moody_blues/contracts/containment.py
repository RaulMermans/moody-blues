"""What a containment report may say. Every attempt is one real sandbox run on a named host."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

CONTAINMENT_SCHEMA = "mb-containment/1"
Environment = Literal["vultr_hosted", "local_development"]


class ContainmentAttempt(BaseModel):
    """``held`` is computed from what was observed, never from what was configured."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: str
    attempted: str
    boundary: str
    held: bool
    observed: str
    exit_code: int | None
    run_status: str
    duration_ms: int
    cleaned_up: bool
    host_unaffected: bool
    host_check: str


class ContainmentHost(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # ``vultr_hosted`` needs the instance metadata service to have answered on this machine.
    environment: Environment
    instance_id: str | None
    region: str | None
    architecture: str
    kernel: str
    operating_system: str
    docker_version: str
    cgroup_version: str
    cgroup_driver: str
    default_runtime: str
    runtimes: list[str]
    security_options: list[str]
    image: str
    image_id: str | None


class EffectiveCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    status: Literal["PASS", "FAIL"]
    detail: str


class ContainmentReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["mb-containment/1"] = CONTAINMENT_SCHEMA
    status: Literal["PASS", "FAIL"]
    generated_at: datetime
    git_commit: str | None
    host: ContainmentHost
    attempts: list[ContainmentAttempt]
    effective_checks: list[EffectiveCheck]
    leftover_containers: int
    limitations: list[str]
    sha256: str  # over the rest of the report: detects damage, and is not a signature
