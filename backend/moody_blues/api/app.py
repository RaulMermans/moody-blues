"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from moody_blues import __version__
from moody_blues.api.auth import OperatorGate
from moody_blues.api.errors import install_error_handlers
from moody_blues.api.middleware import RequestIdMiddleware
from moody_blues.api.routes import health, investigations, operator, sandbox
from moody_blues.config import Settings, get_settings
from moody_blues.explorer.factories import default_factory
from moody_blues.explorer.jobs import JobManager, JobStore, WorkflowFactory
from moody_blues.explorer.paths import artifacts_dir, recorded_dir
from moody_blues.explorer.store import EvidenceStore
from moody_blues.logging import configure_logging
from moody_blues.sandbox.base import SandboxRunner, SandboxUnavailableError
from moody_blues.sandbox.docker_runner import DockerSandboxRunner

log = logging.getLogger("moody_blues.app")


def _secrets(settings: Settings) -> tuple[str, ...]:
    held = (settings.vultr_api_key, settings.operator_token)
    return tuple(s.get_secret_value() for s in held if s is not None)


def _reaper(runner: SandboxRunner) -> Callable[[], object] | None:
    """Sandboxes a dead process left behind. Skipped, with a warning, if Docker is down."""
    if not isinstance(runner, DockerSandboxRunner):
        return None

    def reap() -> object:
        try:
            return runner.reap_orphans()
        except SandboxUnavailableError:
            log.warning("orphan_reap_skipped")
            return []

    return reap


def create_app(
    settings: Settings | None = None,
    *,
    sandbox_runner: SandboxRunner | None = None,
    workflow_factory: WorkflowFactory | None = None,
) -> FastAPI:
    """Build the app. Constructing it performs no network calls (Vultr or Docker)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    artifacts = artifacts_dir(settings)
    job_store = JobStore(artifacts / "live-jobs")
    jobs = JobManager(
        job_store,
        artifacts=artifacts,
        factory=workflow_factory or default_factory(settings, artifacts),
        secrets=_secrets(settings),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        # Local files only, and only if a previous process left a job open. No provider calls.
        closed = jobs.reconcile(reap_orphans=_reaper(app.state.sandbox_runner))
        if closed:
            log.warning("jobs_reconciled", extra={"jobs": closed})
        yield
        jobs.shutdown()

    app = FastAPI(title="MOODY BLUES", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.sandbox_runner = sandbox_runner or DockerSandboxRunner.from_settings(settings)
    app.state.evidence = EvidenceStore(recorded_dir(settings), job_store)
    app.state.jobs = jobs
    app.state.operator_gate = OperatorGate(settings)

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-request-id"],
        expose_headers=["x-request-id"],
    )
    app.add_middleware(RequestIdMiddleware)  # outermost: wraps CORS and error responses

    app.include_router(health.router)
    app.include_router(sandbox.router)
    app.include_router(investigations.router)
    app.include_router(operator.router)
    return app
