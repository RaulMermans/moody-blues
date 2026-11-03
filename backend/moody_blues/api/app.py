"""Application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from moody_blues import __version__
from moody_blues.api.errors import install_error_handlers
from moody_blues.api.middleware import RequestIdMiddleware
from moody_blues.api.routes import health, sandbox
from moody_blues.config import Settings, get_settings
from moody_blues.logging import configure_logging
from moody_blues.sandbox.base import SandboxRunner
from moody_blues.sandbox.docker_runner import DockerSandboxRunner


def create_app(
    settings: Settings | None = None,
    *,
    sandbox_runner: SandboxRunner | None = None,
) -> FastAPI:
    """Build the app. Constructing it performs no network calls (Vultr or Docker)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(title="MOODY BLUES", version=__version__)
    app.state.settings = settings
    app.state.sandbox_runner = sandbox_runner or DockerSandboxRunner.from_settings(settings)

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
    return app
