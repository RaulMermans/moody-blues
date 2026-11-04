from __future__ import annotations

import os
from collections.abc import Iterator
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moody_blues.api.app import create_app
from moody_blues.config import Settings
from moody_blues.contracts.common import ExecutionStatus
from moody_blues.contracts.sandbox import SandboxLimits, SandboxRequest, SandboxResult
from moody_blues.sandbox.base import SandboxUnavailableError
from moody_blues.sandbox.docker_runner import DockerSandboxRunner


def make_settings(**overrides: object) -> Settings:
    """Settings isolated from the developer's .env and MOODY_* environment."""
    base: dict[str, object] = {"environment": "test", "log_format": "console"}
    return Settings(_env_file=None, **(base | overrides))  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("MOODY_") and key not in {"MOODY_REQUIRE_DOCKER", "MOODY_RUN_LIVE_VULTR"}:
            monkeypatch.delenv(key)


class FakeSandboxRunner:
    """Test double for API unit tests. NOT evidence of sandbox behavior —
    real behavior is covered by tests/integration and tests/security."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.requests: list[SandboxRequest] = []

    def ping(self) -> None:
        if not self.available:
            raise SandboxUnavailableError("fake: daemon down")

    def run(self, request: SandboxRequest, *, cancel: Event | None = None) -> SandboxResult:
        self.ping()
        self.requests.append(request)
        return SandboxResult(
            run_id="sbx_fake",
            status=ExecutionStatus.SUCCEEDED,
            exit_code=0,
            stdout="fake\n",
            stderr="",
            duration_ms=1,
            image="fake",
            limits=SandboxLimits(wall_timeout_seconds=1, memory_mb=64, cpus=0.5, pids_limit=16),
            cleaned_up=True,
        )


@pytest.fixture
def fake_sandbox() -> FakeSandboxRunner:
    return FakeSandboxRunner()


@pytest.fixture
def app(fake_sandbox: FakeSandboxRunner) -> FastAPI:
    return create_app(make_settings(), sandbox_runner=fake_sandbox)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# --- real Docker -------------------------------------------------------------------


@pytest.fixture(scope="session")
def docker_runner() -> DockerSandboxRunner:
    """A real runner. Skips (BLOCKED_BY_LOCAL_DEPENDENCY) when Docker is unreachable,
    unless MOODY_REQUIRE_DOCKER=1 (CI), in which case it fails."""
    runner = DockerSandboxRunner.from_settings(make_settings())
    try:
        runner.ping()
        runner.ensure_image()
    except SandboxUnavailableError as exc:
        msg = f"BLOCKED_BY_LOCAL_DEPENDENCY: {exc.detail.message}"
        if os.environ.get("MOODY_REQUIRE_DOCKER") == "1":
            pytest.fail(msg)
        pytest.skip(msg)
    return runner


def limits(**overrides: object) -> SandboxLimits:
    base: dict[str, object] = {
        "wall_timeout_seconds": 10,
        "memory_mb": 128,
        "cpus": 0.5,
        "pids_limit": 64,
    }
    return SandboxLimits.model_validate(base | overrides)
