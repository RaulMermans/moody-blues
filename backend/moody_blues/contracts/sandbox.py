"""Sandbox execution contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from moody_blues.contracts.common import ExecutionStatus

MAX_CODE_BYTES = 64_000


class SandboxLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    wall_timeout_seconds: float = Field(gt=0, le=120)
    memory_mb: int = Field(ge=16, le=2048)
    cpus: float = Field(gt=0, le=4)
    pids_limit: int = Field(ge=8, le=1024)
    network_enabled: bool = False


class SandboxRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1)
    limits: SandboxLimits | None = None  # None -> runner defaults from settings

    @model_validator(mode="after")
    def _check_size(self) -> SandboxRequest:
        if len(self.code.encode()) > MAX_CODE_BYTES:
            raise ValueError(f"code exceeds {MAX_CODE_BYTES} bytes")
        return self


class SandboxResult(BaseModel):
    """Observed outcome of one sandbox run.

    ``status`` semantics:
      - SUCCEEDED: process exited 0.
      - FAILED: process exited non-zero (incl. OOM kill, reported via ``oom_killed``).
      - TIMED_OUT: wall-time limit hit; the container was killed.
    Infrastructure failures raise ``SandboxError`` instead of returning a result.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    status: ExecutionStatus
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_ms: int = Field(ge=0)
    timed_out: bool = False
    oom_killed: bool = False
    image: str
    limits: SandboxLimits
    cleaned_up: bool

    @model_validator(mode="after")
    def _consistent(self) -> SandboxResult:
        if self.status is ExecutionStatus.SUCCEEDED and self.exit_code != 0:
            raise ValueError("SUCCEEDED requires exit_code == 0")
        if self.timed_out != (self.status is ExecutionStatus.TIMED_OUT):
            raise ValueError("timed_out flag must match TIMED_OUT status")
        if self.status not in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMED_OUT,
        }:
            raise ValueError(f"invalid terminal status for a sandbox result: {self.status}")
        return self
