"""A held boundary must be something a broken boundary would fail. Scripted runner, labeled so.

Real attempts run in tests/security/test_containment_report.py and on the host. These prove the
report turns false when a boundary is broken, and that the API refuses a damaged report.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from moody_blues.api.app import create_app
from moody_blues.config import Settings
from moody_blues.contracts.common import ErrorCategory, ExecutionStatus, MoodyBluesError
from moody_blues.contracts.containment import ContainmentHost, ContainmentReport
from moody_blues.contracts.sandbox import SandboxLimits, SandboxResult
from moody_blues.explorer import containment
from moody_blues.explorer.containment import read_report, report_hash, vultr_instance, write_report
from moody_blues.sandbox.docker_runner import DockerSandboxRunner

LIMITS = SandboxLimits(wall_timeout_seconds=10, memory_mb=128, cpus=0.5, pids_limit=64)


class ScriptedRunner:
    """Labeled fixture: it returns what a broken sandbox would, and starts nothing."""

    def ping(self) -> None:
        return None

    def list_sandbox_containers(self) -> list[object]:
        return []


def result(
    stdout: str = "",
    *,
    status: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    exit_code: int = 0,
    oom: bool = False,
    duration_ms: int = 10,
) -> SandboxResult:
    return SandboxResult(
        run_id="sbx_fixture",
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr="",
        duration_ms=duration_ms,
        timed_out=status is ExecutionStatus.TIMED_OUT,
        oom_killed=oom,
        image="fixture",
        limits=LIMITS,
        cleaned_up=True,
    )


class Context:
    limits = LIMITS

    def __init__(self, *results: SandboxResult) -> None:
        self.runner = ScriptedRunner()
        self.results = list(results)

    def run(self, code: str, limits: SandboxLimits | None = None) -> SandboxResult:
        return self.results.pop(0)

    def host_ok(self) -> bool:
        return True


def ctx(*results: SandboxResult) -> Any:
    return cast(Any, Context(*results))


def test_a_connection_that_succeeds_did_not_hold() -> None:
    connect = {"192.0.2.1": "ENETUNREACH", "169.254.169.254": "connected"}
    body = json.dumps({"connect": connect, "interfaces": ["lo"]})
    assert containment._network(ctx(result(body))).held is False  # pyright: ignore[reportPrivateUsage]


def test_an_extra_network_interface_did_not_hold() -> None:
    connect = {"192.0.2.1": "ENETUNREACH", "169.254.169.254": "ENETUNREACH"}
    body = json.dumps({"connect": connect, "interfaces": ["eth0", "lo"]})
    assert containment._network(ctx(result(body))).held is False  # pyright: ignore[reportPrivateUsage]


def test_a_probe_that_reported_nothing_did_not_hold() -> None:
    failed = result("", status=ExecutionStatus.FAILED, exit_code=1)
    assert containment._network(ctx(failed)).held is False  # pyright: ignore[reportPrivateUsage]


def test_a_successful_write_did_not_hold() -> None:
    written = json.dumps({"/etc/mb-containment": "written"})
    recheck = json.dumps({"present": []})
    attempt = containment._filesystem(ctx(result(written), result(recheck)))  # pyright: ignore[reportPrivateUsage]
    assert attempt.held is False


def test_a_file_surviving_into_a_fresh_sandbox_means_the_host_was_affected() -> None:
    denied = json.dumps({"/etc/mb-containment": "EROFS"})
    recheck = json.dumps({"present": ["/etc/mb-containment"]})
    attempt = containment._filesystem(ctx(result(denied), result(recheck)))  # pyright: ignore[reportPrivateUsage]
    assert attempt.held is True
    assert attempt.host_unaffected is False


def test_memory_that_was_never_killed_did_not_hold() -> None:
    finished = result("", status=ExecutionStatus.FAILED, exit_code=1)
    assert containment._memory(ctx(finished)).held is False  # pyright: ignore[reportPrivateUsage]


def test_reaching_the_process_limit_did_not_hold() -> None:
    body = json.dumps({"threads_started": 500, "stopped_by": "nothing"})
    assert containment._processes(ctx(result(body))).held is False  # pyright: ignore[reportPrivateUsage]


def test_a_program_that_outlives_its_deadline_did_not_hold() -> None:
    late = result("", status=ExecutionStatus.TIMED_OUT, exit_code=137, duration_ms=60_000)
    assert containment._timeout(ctx(late)).held is False  # pyright: ignore[reportPrivateUsage]


def test_a_configured_secret_seen_in_the_sandbox_did_not_hold() -> None:
    body = json.dumps({"env": {"X": "real-secret"}, "docker_socket": False})
    attempt = containment._secrets(ctx(result(body)), ("real-secret",))  # pyright: ignore[reportPrivateUsage]
    assert attempt.held is False
    assert "real-secret" not in attempt.model_dump_json()


def test_a_visible_docker_socket_did_not_hold() -> None:
    body = json.dumps({"env": {}, "docker_socket": True})
    assert containment._secrets(ctx(result(body)), ()).held is False  # pyright: ignore[reportPrivateUsage]


def test_only_the_metadata_service_can_make_a_report_hosted() -> None:
    body = json.dumps({"instanceid": "abc", "region": {"regioncode": "FRA"}}).encode()
    assert vultr_instance(lambda: body) == ("abc", "FRA")

    def unreachable() -> bytes:
        raise OSError("no route")

    assert vultr_instance(unreachable) is None
    assert vultr_instance(lambda: b"<html>a captive portal</html>") is None
    assert vultr_instance(lambda: b"{}") is None


def report(environment: Any = "local_development") -> ContainmentReport:
    draft = ContainmentReport(
        status="PASS",
        generated_at=datetime(2026, 11, 5, tzinfo=UTC),
        git_commit="abc",
        host=ContainmentHost(
            environment=environment,
            instance_id=None,
            region=None,
            architecture="x86_64",
            kernel="6.8",
            operating_system="Ubuntu 24.04",
            docker_version="29",
            cgroup_version="2",
            cgroup_driver="systemd",
            default_runtime="runc",
            runtimes=["runc"],
            security_options=[],
            image="python@sha256:abc",
            image_id=None,
        ),
        attempts=[],
        effective_checks=[],
        leftover_containers=0,
        limitations=["x"],
        sha256="",
    )
    return draft.model_copy(update={"sha256": report_hash(draft)})


def test_a_report_survives_a_write_and_read(tmp_path: Path) -> None:
    path = tmp_path / "containment" / "report.json"
    write_report(report(), path)
    assert read_report(path) == report()


def test_relabeling_a_local_report_as_hosted_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_report(report(), path)
    body = json.loads(path.read_text())
    body["host"]["environment"] = "vultr_hosted"
    path.write_text(json.dumps(body))
    with pytest.raises(MoodyBluesError) as caught:
        read_report(path)
    assert caught.value.detail.category is ErrorCategory.EVIDENCE_INTEGRITY


def test_unparseable_and_missing_reports_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    with pytest.raises(MoodyBluesError) as missing:
        read_report(path)
    assert missing.value.detail.category is ErrorCategory.NOT_FOUND
    path.write_text("{}")
    with pytest.raises(MoodyBluesError) as broken:
        read_report(path)
    assert broken.value.detail.category is ErrorCategory.EVIDENCE_INTEGRITY


def client(tmp_path: Path, report_path: Path) -> TestClient:
    settings = Settings(_env_file=None, artifacts_dir=tmp_path, containment_report=report_path)  # pyright: ignore[reportCallIssue]
    return TestClient(create_app(settings))


def test_the_route_serves_a_valid_report_and_nothing_can_be_posted(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_report(report(), path)
    c = client(tmp_path, path)
    assert c.get("/containment").json()["sha256"] == report().sha256
    assert c.post("/containment").status_code == 405


def test_the_committed_report_is_valid_and_says_it_is_local() -> None:
    root = Path(__file__).resolve().parents[2]
    committed = read_report(root / "evidence" / "containment" / "report.json")
    assert committed.status == "PASS"
    assert committed.host.environment == "local_development"
    assert committed.host.instance_id is None


def test_the_runner_used_is_the_approved_one(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    runner = containment.generated_code_runner(settings)
    assert isinstance(runner, DockerSandboxRunner)
    assert runner.approved_for_generated_code
