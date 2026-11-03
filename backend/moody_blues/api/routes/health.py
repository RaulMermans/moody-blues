from __future__ import annotations

from fastapi import APIRouter

from moody_blues.api.deps import SandboxDep, SettingsDep
from moody_blues.services import health as health_service

router = APIRouter(tags=["health"])


@router.get("/health", response_model=health_service.HealthResponse)
def get_health(settings: SettingsDep) -> health_service.HealthResponse:
    """Liveness plus configuration state. Performs no external calls."""
    return health_service.health(settings)


@router.get("/ready", response_model=health_service.ReadinessResponse)
def get_ready(settings: SettingsDep, sandbox: SandboxDep) -> health_service.ReadinessResponse:
    """Readiness with real, non-chargeable dependency checks (Docker ping)."""
    return health_service.readiness(settings, sandbox)
