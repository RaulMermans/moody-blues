from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from moody_blues.api.app import create_app
from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from tests.conftest import FakeSandboxRunner, make_settings


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _integration(body: dict[str, object], name: str) -> dict[str, object]:
    items: list[dict[str, object]] = body.get("integrations") or body["checks"]  # type: ignore[assignment]
    return next(i for i in items if i["name"] == name)


def test_health_without_credentials(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "moody-blues-backend"
    assert _integration(body, "vultr_inference")["state"] == "not_configured"
    # /health never claims docker works: it doesn't check it.
    docker = _integration(body, "docker_sandbox")
    assert docker["state"] == "not_checked"
    assert docker["checked_at"] is None


def test_health_with_key_is_unverified_not_healthy(fake_sandbox: FakeSandboxRunner) -> None:
    app = create_app(make_settings(vultr_api_key="sk-x"), sandbox_runner=fake_sandbox)
    body = _client(app).get("/health").json()
    vultr = _integration(body, "vultr_inference")
    assert vultr["state"] == "configured_unverified"
    assert "sk-x" not in str(body)


def test_ready_reports_real_check_result() -> None:
    up = create_app(make_settings(), sandbox_runner=FakeSandboxRunner(available=True))
    down = create_app(make_settings(), sandbox_runner=FakeSandboxRunner(available=False))
    up_body = _client(up).get("/ready").json()
    down_body = _client(down).get("/ready").json()
    assert up_body["status"] == "ready"
    assert _integration(up_body, "docker_sandbox")["state"] == "available"
    assert _integration(up_body, "docker_sandbox")["checked_at"] is not None
    assert down_body["status"] == "degraded"
    assert _integration(down_body, "docker_sandbox")["state"] == "unavailable"
    # Vultr is never live-checked by /ready (would be chargeable).
    assert _integration(down_body, "vultr_inference")["state"] == "not_configured"


def test_request_id_generated_and_echoed(client: TestClient) -> None:
    generated = client.get("/health").headers["x-request-id"]
    assert generated.startswith("req_")
    assert client.get("/health", headers={"x-request-id": "abc-123"}).headers["x-request-id"] == (
        "abc-123"
    )


def test_malformed_inbound_request_id_replaced(client: TestClient) -> None:
    rid = client.get("/health", headers={"x-request-id": "bad id\twith spaces"}).headers[
        "x-request-id"
    ]
    assert rid.startswith("req_")


def test_404_uses_error_envelope(client: TestClient) -> None:
    r = client.get("/nope", headers={"x-request-id": "rid-404"})
    assert r.status_code == 404
    assert r.json() == {
        "error": {"category": "not_found", "message": "Not Found", "retryable": False},
        "request_id": "rid-404",
    }


class _Body(BaseModel):
    n: int


def _app_with_test_routes() -> FastAPI:
    app = create_app(make_settings(), sandbox_runner=FakeSandboxRunner())

    @app.post("/_test/validate")
    def validate(body: _Body) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        return {"n": body.n}

    @app.get("/_test/boom")
    def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("secret internal detail")

    @app.get("/_test/domain")
    def domain() -> None:  # pyright: ignore[reportUnusedFunction]
        raise MoodyBluesError(ErrorCategory.PROVIDER_NOT_CONFIGURED, "no key")

    return app


def test_validation_error_envelope() -> None:
    r = _client(_app_with_test_routes()).post("/_test/validate", json={"n": "not-int"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["category"] == "validation"
    assert "body.n" in err["message"]
    assert r.json()["request_id"] == r.headers["x-request-id"]


def test_unhandled_error_does_not_leak() -> None:
    r = _client(_app_with_test_routes()).get("/_test/boom")
    assert r.status_code == 500
    assert r.json()["error"] == {
        "category": "internal",
        "message": "Internal server error",
        "retryable": False,
    }
    assert "secret internal detail" not in r.text
    # Regression: unhandled errors used to bypass RequestIdMiddleware (no header, null id).
    assert r.headers["x-request-id"].startswith("req_")
    assert r.json()["request_id"] == r.headers["x-request-id"]


def test_domain_error_mapped() -> None:
    r = _client(_app_with_test_routes()).get("/_test/domain")
    assert r.status_code == 503
    assert r.json()["error"]["category"] == "provider_not_configured"


def test_sandbox_smoke_route_runs_fixed_program(
    client: TestClient, fake_sandbox: FakeSandboxRunner
) -> None:
    r = client.post("/sandbox/smoke")
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"
    assert "hello from sandbox" in fake_sandbox.requests[0].code


def test_sandbox_smoke_route_when_docker_down() -> None:
    app = create_app(make_settings(), sandbox_runner=FakeSandboxRunner(available=False))
    r = _client(app).post("/sandbox/smoke")
    assert r.status_code == 503
    assert r.json()["error"]["category"] == "sandbox_unavailable"


def test_cors_allows_configured_origin_only(client: TestClient) -> None:
    ok = client.get("/health", headers={"origin": "http://localhost:3000"})
    bad = client.get("/health", headers={"origin": "https://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers
