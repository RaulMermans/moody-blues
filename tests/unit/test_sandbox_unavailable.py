"""Docker unavailable / misconfigured. Uses the REAL runner against a socket that
doesn't exist — no mocks."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from moody_blues.api.app import create_app
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.sandbox import SandboxRequest
from moody_blues.sandbox.base import SandboxUnavailableError
from moody_blues.sandbox.docker_host import resolve_docker_host
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from tests.conftest import make_settings

BOGUS = "unix:///nonexistent/moody-blues-test/docker.sock"


def _runner() -> DockerSandboxRunner:
    return DockerSandboxRunner.from_settings(make_settings(docker_host=BOGUS))


def test_ping_raises_categorized_error() -> None:
    with pytest.raises(SandboxUnavailableError) as info:
        _runner().ping()
    assert info.value.detail.category is ErrorCategory.SANDBOX_UNAVAILABLE
    assert BOGUS in info.value.detail.message


def test_run_raises_instead_of_fake_result() -> None:
    with pytest.raises(SandboxUnavailableError):
        _runner().run(SandboxRequest(code="print(1)"))


def test_ready_endpoint_reports_unavailable() -> None:
    settings = make_settings(docker_host=BOGUS)
    with TestClient(create_app(settings)) as client:
        body = client.get("/ready").json()
        assert body["status"] == "degraded"
        docker = next(c for c in body["checks"] if c["name"] == "docker_sandbox")
        assert docker["state"] == "unavailable"
        smoke = client.post("/sandbox/smoke")
        assert smoke.status_code == 503
        assert smoke.json()["error"]["category"] == "sandbox_unavailable"


def test_host_resolution_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_HOST", "tcp://from-env:2375")
    assert resolve_docker_host("unix:///explicit.sock") == (
        "unix:///explicit.sock",
        "MOODY_DOCKER_HOST",
    )
    assert resolve_docker_host(None) == ("tcp://from-env:2375", "DOCKER_HOST")
