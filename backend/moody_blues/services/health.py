"""Health and readiness evaluation.

``/health`` is a cheap liveness view: it only reports what is *configured*, never claims
an external dependency is working. ``/ready`` performs real, non-chargeable checks
(Docker daemon ping). Vultr is never called implicitly: inference costs money, so its
state stays ``configured_unverified`` until an explicit smoke test is run.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from moody_blues import __version__
from moody_blues.config import Settings
from moody_blues.sandbox.base import SandboxRunner, SandboxUnavailableError

_STARTED = time.monotonic()


class IntegrationState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED_UNVERIFIED = "configured_unverified"
    NOT_CHECKED = "not_checked"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class IntegrationStatus(BaseModel):
    name: str
    state: IntegrationState
    detail: str
    checked_at: datetime | None = None  # set only when a real check ran


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["moody-blues-backend"] = "moody-blues-backend"
    version: str
    environment: str
    uptime_seconds: float
    integrations: list[IntegrationStatus]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checks: list[IntegrationStatus]


def _vultr_status(settings: Settings) -> IntegrationStatus:
    if not settings.vultr_configured:
        return IntegrationStatus(
            name="vultr_inference",
            state=IntegrationState.NOT_CONFIGURED,
            detail="MOODY_VULTR_API_KEY not set",
        )
    return IntegrationStatus(
        name="vultr_inference",
        state=IntegrationState.CONFIGURED_UNVERIFIED,
        detail=f"API key present, model={settings.vultr_model}; not live-checked "
        "(run `make vultr-smoke`)",
    )


def health(settings: Settings) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment,
        uptime_seconds=round(time.monotonic() - _STARTED, 3),
        integrations=[
            _vultr_status(settings),
            IntegrationStatus(
                name="docker_sandbox",
                state=IntegrationState.NOT_CHECKED,
                detail="see /ready for a live daemon check",
            ),
        ],
    )


def readiness(settings: Settings, sandbox: SandboxRunner) -> ReadinessResponse:
    now = datetime.now(UTC)
    try:
        sandbox.ping()
        docker = IntegrationStatus(
            name="docker_sandbox",
            state=IntegrationState.AVAILABLE,
            detail="Docker daemon responded to ping",
            checked_at=now,
        )
    except SandboxUnavailableError as exc:
        docker = IntegrationStatus(
            name="docker_sandbox",
            state=IntegrationState.UNAVAILABLE,
            detail=exc.detail.message,
            checked_at=now,
        )
    status: Literal["ready", "degraded"] = (
        "ready" if docker.state is IntegrationState.AVAILABLE else "degraded"
    )
    return ReadinessResponse(status=status, checks=[docker, _vultr_status(settings)])
