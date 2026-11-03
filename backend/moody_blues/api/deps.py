"""FastAPI dependency providers. Override these in tests via ``app.dependency_overrides``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from moody_blues.config import Settings
from moody_blues.sandbox.base import SandboxRunner


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_sandbox_runner(request: Request) -> SandboxRunner:
    runner: SandboxRunner = request.app.state.sandbox_runner
    return runner


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SandboxDep = Annotated[SandboxRunner, Depends(get_sandbox_runner)]
