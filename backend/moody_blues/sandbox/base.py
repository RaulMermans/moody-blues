"""Sandbox runner interface."""

from __future__ import annotations

from threading import Event
from typing import Protocol

from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.sandbox import SandboxRequest, SandboxResult


class SandboxError(MoodyBluesError):
    """The sandbox infrastructure failed; the submitted code did not run to completion."""


class SandboxUnavailableError(SandboxError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCategory.SANDBOX_UNAVAILABLE, message, retryable=True)


class SandboxRunner(Protocol):
    """Executes code in an isolated, disposable environment.

    Implementations must never run code in the calling process, must not pass host
    secrets into the environment, and must release all resources before returning.
    Setting ``cancel`` stops an active run promptly; the result then has status CANCELLED.
    """

    def run(self, request: SandboxRequest, *, cancel: Event | None = None) -> SandboxResult: ...

    def ping(self) -> None:
        """Raise ``SandboxUnavailableError`` if the backing runtime is unreachable."""
        ...
