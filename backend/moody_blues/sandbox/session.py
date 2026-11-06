"""A long-lived sandbox the host can talk to, for code that has to run as one process.

``SandboxRunner`` serves steps: one program in, one document out. An external agent keeps its own
state across many tool calls, so it needs a process that stays up and a channel into it, without
gaining anything else. The channel is its stdin and stdout, and nothing more.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from moody_blues.contracts.sandbox import SandboxRequest


class ReadStatus(StrEnum):
    LINE = "line"
    TIMEOUT = "timeout"  # nothing arrived; the session is still up
    CLOSED = "closed"  # the process closed its output
    OVERSIZED = "oversized"  # a line passed the limit; nothing further will be read


class SessionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ReadStatus
    line: bytes = b""


class SessionClosedError(Exception):
    """The process is gone, so nothing could be written to it."""


class SessionExit(BaseModel):
    """How the session ended. ``cleaned_up`` False means something is left behind."""

    model_config = ConfigDict(frozen=True)

    exit_code: int | None
    oom_killed: bool
    killed_by_host: bool
    cleaned_up: bool
    stdout_bytes: int
    stderr_bytes: int
    stderr_tail: bytes


class SandboxSession(Protocol):
    @property
    def session_id(self) -> str: ...

    @property
    def execution_mode(self) -> str: ...

    @property
    def image(self) -> str: ...

    @property
    def image_id(self) -> str | None: ...

    def send(self, data: bytes) -> None:
        """Write to the process's stdin. Raises ``SessionClosedError`` if it is gone."""
        ...

    def read_line(self, timeout: float) -> SessionRead: ...

    def close(self, grace_seconds: float = 0.0) -> SessionExit:
        """Wait up to ``grace_seconds`` for it to exit, kill it, and remove what it used."""
        ...


class SessionRunner(Protocol):
    """Starts sessions under the same guarantees as ``SandboxRunner``."""

    approved_for_generated_code: bool

    def open_session(self, request: SandboxRequest, *, max_line_bytes: int) -> SandboxSession: ...

    def ping(self) -> None: ...
