"""Shared status vocabulary and error categories."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ExecutionStatus(StrEnum):
    """Lifecycle/outcome of any unit of work (experiment, sandbox run, inference call)."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"  # stopped on request by trusted code
    ERROR = "error"  # infrastructure failure: the work itself never ran to completion


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    INTERNAL = "internal"
    # Provider
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    PROVIDER_AUTH = "provider_auth"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_CONNECTION = "provider_connection"
    PROVIDER_BAD_REQUEST = "provider_bad_request"
    PROVIDER_MODEL_NOT_FOUND = "provider_model_not_found"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    PROVIDER_INVALID_RESPONSE = "provider_invalid_response"
    # Sandbox
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    SANDBOX_IMAGE_UNAVAILABLE = "sandbox_image_unavailable"
    SANDBOX_RUNTIME = "sandbox_runtime"
    # Experiment runtime
    BUDGET_EXCEEDED = "budget_exceeded"
    EVIDENCE_INTEGRITY = "evidence_integrity"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: ErrorCategory
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    """Body returned by every non-2xx API response."""

    error: ErrorDetail
    request_id: str | None = None


class MoodyBluesError(Exception):
    """Base for categorized domain errors. Carries an ``ErrorDetail``."""

    def __init__(self, category: ErrorCategory, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.detail = ErrorDetail(category=category, message=message, retryable=retryable)
