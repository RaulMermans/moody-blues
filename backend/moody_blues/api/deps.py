"""FastAPI dependency providers. Override these in tests via ``app.dependency_overrides``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from moody_blues.api.auth import OperatorGate
from moody_blues.config import Settings
from moody_blues.explorer.jobs import JobManager
from moody_blues.explorer.store import EvidenceStore
from moody_blues.sandbox.base import SandboxRunner


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_sandbox_runner(request: Request) -> SandboxRunner:
    runner: SandboxRunner = request.app.state.sandbox_runner
    return runner


def get_evidence(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence
    return store


def get_jobs(request: Request) -> JobManager:
    jobs: JobManager = request.app.state.jobs
    return jobs


def get_gate(request: Request) -> OperatorGate:
    gate: OperatorGate = request.app.state.operator_gate
    return gate


def require_operator(request: Request) -> None:
    get_gate(request).require(request)


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SandboxDep = Annotated[SandboxRunner, Depends(get_sandbox_runner)]
EvidenceDep = Annotated[EvidenceStore, Depends(get_evidence)]
JobsDep = Annotated[JobManager, Depends(get_jobs)]
GateDep = Annotated[OperatorGate, Depends(get_gate)]
