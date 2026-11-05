"""Real server, real Docker: a process killed mid-investigation, then restarted.

The server runs as a child process and is SIGKILLed while a rehearsal is running. The mission uses
a fixture and a reference script, so this exercises interruption handling and spends nothing.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from moody_blues.sandbox.docker_runner import DockerSandboxRunner

pytestmark = pytest.mark.docker

TOKEN = "integration-operator-token-not-a-real-secret"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def call(port: int, path: str, *, method: str = "GET", body: object = None) -> Any:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"authorization": f"Bearer {TOKEN}", "content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        return json.loads(response.read())


def serve(artifacts: Path, port: int) -> subprocess.Popen[bytes]:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("MOODY_")},
        "MOODY_ENVIRONMENT": "test",
        "MOODY_OPERATOR_TOKEN": TOKEN,
        "MOODY_ARTIFACTS_DIR": str(artifacts),
    }
    process = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "moody_blues.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            call(port, "/health")
            return process
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)
    process.kill()
    raise AssertionError("the server did not start")


def test_a_killed_server_closes_its_job_on_restart_and_never_retries(
    tmp_path: Path,
    docker_runner: DockerSandboxRunner,  # the skip-or-fail gate for a missing daemon
) -> None:
    port = free_port()
    first = serve(tmp_path, port)
    try:
        job = call(port, "/operator/jobs", method="POST", body={"mission_id": "rehearsal-recovery"})
        deadline = time.monotonic() + 30
        while call(port, f"/operator/jobs/{job['job_id']}")["job"]["status"] != "running":
            assert time.monotonic() < deadline
            time.sleep(0.02)
    finally:
        os.kill(first.pid, signal.SIGKILL)
        first.wait(10)

    second_port = free_port()
    second = serve(tmp_path, second_port)
    try:
        view = call(second_port, f"/operator/jobs/{job['job_id']}")
        record = view["job"]
        assert record["status"] in {"failed", "outcome_uncertain", "completed"}
        assert record["finished_at"] is not None
        # A job that had no report at the kill must not claim evidence.
        report = tmp_path / "investigations" / record["investigation_id"] / "report.json"
        assert record["evidence_available"] is report.exists()
        jobs = call(second_port, "/operator/jobs")
        assert [j["job_id"] for j in jobs] == [job["job_id"]]
        status = call(second_port, "/operator/status")
        assert status["active_job_id"] is None
        started = [e for e in view["events"] if e["type"] == "running"]
        assert len(started) == 1
    finally:
        second.terminate()
        second.wait(30)
