"""Real Docker execution. Requires a reachable daemon (skips as BLOCKED_BY_LOCAL_DEPENDENCY
otherwise; fails instead when MOODY_REQUIRE_DOCKER=1)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from threading import Event, Timer

import pytest
from fastapi.testclient import TestClient

from moody_blues.api.app import create_app
from moody_blues.contracts.common import ExecutionStatus
from moody_blues.contracts.sandbox import SandboxRequest, SandboxResult
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from tests.conftest import limits, make_settings

pytestmark = pytest.mark.docker


@pytest.fixture(autouse=True)
def _assert_no_leftovers(docker_runner: DockerSandboxRunner) -> Iterator[None]:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    yield
    after = {c.id for c in docker_runner.list_sandbox_containers()}
    assert after - before == set(), "sandbox container was not cleaned up"


def test_successful_execution(docker_runner: DockerSandboxRunner) -> None:
    r = docker_runner.run(
        SandboxRequest(code="import sys; print('out'); print('err', file=sys.stderr)")
    )
    assert r.status is ExecutionStatus.SUCCEEDED
    assert r.exit_code == 0
    assert r.stdout == "out\n"
    assert r.stderr == "err\n"
    assert r.cleaned_up
    assert not r.timed_out
    # Structured result round-trips through its own validator.
    assert SandboxResult.model_validate_json(r.model_dump_json()) == r


def test_python_error(docker_runner: DockerSandboxRunner) -> None:
    r = docker_runner.run(SandboxRequest(code="raise ValueError('boom')"))
    assert r.status is ExecutionStatus.FAILED
    assert r.exit_code == 1
    assert "ValueError: boom" in r.stderr
    assert r.cleaned_up


def test_explicit_exit_code(docker_runner: DockerSandboxRunner) -> None:
    r = docker_runner.run(SandboxRequest(code="import sys; sys.exit(7)"))
    assert r.status is ExecutionStatus.FAILED
    assert r.exit_code == 7


def test_timeout_kills_container(docker_runner: DockerSandboxRunner) -> None:
    r = docker_runner.run(
        SandboxRequest(
            code="import time\nprint('started', flush=True)\ntime.sleep(60)",
            limits=limits(wall_timeout_seconds=2),
        )
    )
    assert r.status is ExecutionStatus.TIMED_OUT
    assert r.timed_out
    assert r.exit_code == 137  # SIGKILL
    assert r.stdout == "started\n"  # partial output preserved
    assert 2000 <= r.duration_ms < 15000
    assert r.cleaned_up


def test_memory_limit_enforced(docker_runner: DockerSandboxRunner) -> None:
    r = docker_runner.run(
        SandboxRequest(
            code="b = bytearray(256 * 1024 * 1024)\nprint('allocated')",
            limits=limits(memory_mb=64),
        )
    )
    assert r.status is ExecutionStatus.FAILED
    assert "allocated" not in r.stdout
    # Either the kernel OOM-killed the process or Python raised MemoryError.
    assert r.oom_killed or r.exit_code == 137 or "MemoryError" in r.stderr


def test_pids_limit_enforced(docker_runner: DockerSandboxRunner) -> None:
    code = """
import threading, time
started = 0
try:
    for _ in range(200):
        threading.Thread(target=time.sleep, args=(5,), daemon=True).start()
        started += 1
except RuntimeError as e:
    print(f"limited after {started}: {e}")
else:
    print(f"unlimited: {started}")
"""
    r = docker_runner.run(SandboxRequest(code=code, limits=limits(pids_limit=16)))
    assert "limited after" in r.stdout, r.stdout + r.stderr
    started = int(r.stdout.split("limited after ")[1].split(":")[0])
    assert started < 16


def test_cpu_quota_applied(docker_runner: DockerSandboxRunner) -> None:
    r = docker_runner.run(
        SandboxRequest(
            code="print(open('/sys/fs/cgroup/cpu.max').read().strip())",
            limits=limits(cpus=0.5),
        )
    )
    assert r.exit_code == 0, r.stderr
    quota, period = r.stdout.split()
    assert int(quota) / int(period) == pytest.approx(0.5)


def test_output_is_truncated(docker_runner: DockerSandboxRunner) -> None:
    r = docker_runner.run(SandboxRequest(code="print('x' * 200_000)"))
    assert r.exit_code == 0
    assert r.stdout_truncated
    assert len(r.stdout) == docker_runner.output_limit_bytes


def test_api_sandbox_smoke_against_real_docker() -> None:
    with TestClient(create_app(make_settings())) as client:
        ready = client.get("/ready").json()
        assert ready["status"] == "ready"
        r = client.post("/sandbox/smoke")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    assert "hello from sandbox" in body["stdout"]
    assert "uid=65534" in body["stdout"]
    assert body["cleaned_up"] is True


# --- Sprint 4: output accounting, cancellation, deadlines that outlive the host process -------


def test_flood_past_log_rotation_is_reported_as_truncated(
    docker_runner: DockerSandboxRunner,
) -> None:
    """Regression: the json-file driver rotates at max-size, so reading logs back returned a
    short tail with ``stdout_truncated=False`` after 2 MB of output."""
    code = (
        "import sys\n"
        "for _ in range(40):\n"
        "    sys.stdout.write('x' * 50_000 + '\\n')\n"
        'print(\'{"action": "finish_experiment"}\')\n'
    )
    r = docker_runner.run(SandboxRequest(code=code))
    assert r.status is ExecutionStatus.SUCCEEDED
    assert r.stdout_truncated
    assert r.stdout_bytes > 2_000_000
    assert len(r.stdout) == docker_runner.output_limit_bytes
    assert r.output_complete


def test_output_byte_counts_are_exact(docker_runner: DockerSandboxRunner) -> None:
    code = "import sys; sys.stdout.write('a' * 1234); sys.stderr.write('b' * 56)"
    r = docker_runner.run(SandboxRequest(code=code))
    assert (r.stdout_bytes, r.stderr_bytes) == (1234, 56)
    assert not r.stdout_truncated
    assert r.output_complete


def test_cancellation_stops_an_active_run(docker_runner: DockerSandboxRunner) -> None:
    cancel = Event()
    timer = Timer(1.0, cancel.set)
    timer.start()
    started = time.monotonic()
    r = docker_runner.run(
        SandboxRequest(code="import time; time.sleep(30)", limits=limits()), cancel=cancel
    )
    timer.join()
    assert r.status is ExecutionStatus.CANCELLED
    assert not r.timed_out
    assert r.cleaned_up
    assert time.monotonic() - started < 8


def test_in_container_deadline_runs_as_pid_1_and_survives_sigkill(
    docker_runner: DockerSandboxRunner,
) -> None:
    code = (
        "import os, time\n"
        "assert os.getppid() == 1\n"
        "print(open('/proc/1/comm').read().strip())\n"
        "os.kill(1, 9)\n"
        "time.sleep(0.3)\n"
        "print('init survived')\n"
    )
    r = docker_runner.run(SandboxRequest(code=code))
    assert r.stdout.split() == ["timeout", "init", "survived"]


def test_reaper_only_removes_expired_containers(docker_runner: DockerSandboxRunner) -> None:
    config = docker_runner._container_config(  # pyright: ignore[reportPrivateUsage]
        "sbx_reaper_test", "import time; time.sleep(1)", limits(wall_timeout_seconds=1)
    )
    client = docker_runner._docker()  # pyright: ignore[reportPrivateUsage]
    container = client.containers.create(**config)
    try:
        assert docker_runner.reap_orphans() == []
        assert container.id in {c.id for c in docker_runner.list_sandbox_containers()}
        assert docker_runner.reap_orphans(now=time.time() + 3600) == ["sbx_reaper_test"]
        assert container.id not in {c.id for c in docker_runner.list_sandbox_containers()}
    finally:
        docker_runner._remove(container)  # pyright: ignore[reportPrivateUsage]
