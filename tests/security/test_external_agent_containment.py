"""What an external agent can reach, seen from inside the real sandbox.

These are real containers on this host. A pass describes *this* Docker runtime and kernel, and is
not a claim that any arbitrary agent can be run safely.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentConfigName, TerminationReason
from moody_blues.contracts.experiment_evidence import (
    ExperimentState,
    ExperimentTermination,
)
from moody_blues.contracts.sandbox import SandboxLimits
from moody_blues.experiments.recovery import recover_interrupted, verify_experiment
from moody_blues.experiments.target import TargetRequest, TargetResult
from moody_blues.experiments.workspace import JOURNAL, read_journal
from moody_blues.external.bundle import build_bundle
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.investigator.preflight import generated_code_runner, sandbox_limits
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from moody_blues.world.scenarios import load_scenario
from moody_blues.world.store import DB_FILENAME, ReadOnlyWorldView
from tests.external.conftest import FAST, fixture_manifest

pytestmark = pytest.mark.docker
REPO = Path(__file__).resolve().parents[2]
SECRET = "sk-host-canary-7741"
T = TerminationReason


@pytest.fixture
def settings(docker_runner: DockerSandboxRunner, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("MOODY_VULTR_API_KEY", SECRET)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET)
    return Settings(_env_file=None, sandbox_wall_timeout_seconds=10)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _no_leftovers(docker_runner: DockerSandboxRunner) -> Iterator[None]:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    yield
    assert {c.id for c in docker_runner.list_sandbox_containers()} <= before


def _run(
    settings: Settings,
    tmp_path: Path,
    entry: str,
    *,
    limits: Any = FAST,
    sandbox: SandboxLimits | None = None,
) -> TargetResult:
    target = ExternalAgentTarget(
        runner=generated_code_runner(settings),
        bundle=build_bundle(fixture_manifest(tmp_path, entry)),
        sandbox_limits=sandbox or sandbox_limits(settings),
        limits=limits,
    )
    root = tmp_path / f"worlds-{entry}"
    root.mkdir()
    return target.run(
        TargetRequest(
            scenario=load_scenario("normal-success"),
            config=AgentConfigName.BASELINE,
            world_root=root,
            max_wall_seconds=30,
            cancel=None,
        )
    )


@pytest.fixture
def probe(settings: Settings, tmp_path: Path) -> tuple[dict[str, Any], TargetResult]:
    result = _run(settings, tmp_path, "Probes")
    assert result.claim is not None, result.external
    return json.loads(result.claim.message), result


def _denied(value: str) -> bool:
    return value.startswith("denied:")


def test_the_engine_is_not_in_the_sandbox(probe: tuple[dict[str, Any], TargetResult]) -> None:
    report, _ = probe
    assert report["import_backend"] == "denied:ModuleNotFoundError"
    assert report["import_oracle"] == "denied:ModuleNotFoundError"


def test_no_world_database_is_reachable(probe: tuple[dict[str, Any], TargetResult]) -> None:
    assert probe[0]["sqlite_files"] == []


def test_no_docker_socket(probe: tuple[dict[str, Any], TargetResult]) -> None:
    assert probe[0]["docker_socket"] is False


def test_no_host_environment(probe: tuple[dict[str, Any], TargetResult]) -> None:
    report, result = probe
    allowed = {"HOME", "PATH", "PYTHONDONTWRITEBYTECODE", "LANG", "GPG_KEY", "PYTHON_VERSION"}
    allowed |= {"PYTHON_SHA256", "HOSTNAME", "LC_CTYPE"}
    assert set(report["env"]) <= allowed
    assert SECRET not in result.model_dump_json()


def test_no_network(probe: tuple[dict[str, Any], TargetResult]) -> None:
    report, _ = probe
    for attempt in ("metadata", "internet", "dns", "gateway"):
        assert _denied(report[attempt]), report[attempt]
    assert report["interfaces"] == ["lo"]


def test_no_writes_outside_tmp_and_no_executing_there(
    probe: tuple[dict[str, Any], TargetResult],
) -> None:
    report, _ = probe
    assert _denied(report["write_root"])
    assert _denied(report["write_app"])
    assert _denied(report["exec_tmp"])


def test_runs_unprivileged(probe: tuple[dict[str, Any], TargetResult]) -> None:
    assert probe[0]["uid"] == 65534


def test_pid_limit_holds(settings: Settings, tmp_path: Path) -> None:
    result = _run(settings, tmp_path, "Forks")
    assert result.external is not None
    assert result.external.exit is not None
    assert result.external.exit.cleaned_up
    assert result.claim is not None
    assert "pid limit reached" in result.claim.message


def test_memory_limit_kills_the_agent_and_the_run_is_still_judged(
    settings: Settings, tmp_path: Path
) -> None:
    limits = sandbox_limits(settings).model_copy(update={"memory_mb": 64})
    result = _run(settings, tmp_path, "EatsMemory", sandbox=limits)
    assert result.termination == T.ADAPTER_CRASHED.value
    assert result.external is not None
    assert result.external.exit is not None
    assert result.external.exit.oom_killed
    assert result.oracle is not None


def test_a_stdout_flood_is_bounded(settings: Settings, tmp_path: Path) -> None:
    started = time.monotonic()
    result = _run(settings, tmp_path, "FloodsStdout")
    assert result.termination == T.REJECTED_CALL_LIMIT.value
    assert len(result.world_trace) == FAST.max_tool_calls
    assert time.monotonic() - started < 15


def test_an_unpinned_runner_is_refused(docker_runner: DockerSandboxRunner, tmp_path: Path) -> None:
    assert not docker_runner.approved_for_generated_code
    with pytest.raises(ValueError, match="approved"):
        ExternalAgentTarget(
            runner=docker_runner,
            bundle=build_bundle(fixture_manifest(tmp_path, "Succeeds")),
            sandbox_limits=SandboxLimits(
                wall_timeout_seconds=5, memory_mb=64, cpus=0.5, pids_limit=32
            ),
        )


def _wait_for_commit(root: Path, seconds: float = 40) -> Path:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for database in root.glob(f"*/worlds/*/{DB_FILENAME}"):
            with ReadOnlyWorldView(database) as view:
                if any(c.created_by_call > 0 for c in view.all_customers()):
                    return database
        time.sleep(0.1)
    raise AssertionError("the agent never committed")


def test_coordinator_killed_mid_run_ends_uncertain_and_nothing_is_replayed(
    settings: Settings, docker_runner: DockerSandboxRunner, tmp_path: Path
) -> None:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    root = tmp_path / "experiments"
    root.mkdir()
    manifest = fixture_manifest(tmp_path, "CommitsThenHangs")
    env = {k: v for k, v in os.environ.items() if not k.startswith("MOODY_VULTR")}
    process = subprocess.Popen(  # noqa: S603 - fixed argv, test driver in this repository
        [sys.executable, "-m", "tests.external.crash_driver", str(root), str(manifest)],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        database = _wait_for_commit(root)
        process.send_signal(signal.SIGKILL)
        process.wait(timeout=10)

        # The container outlives its owner, with its in-container deadline still running.
        left = [c for c in docker_runner.list_sandbox_containers() if c.id not in before]
        assert left

        [recovered] = recover_interrupted(root)
        assert recovered.status is ExperimentState.UNCERTAIN
        assert recovered.termination is ExperimentTermination.COORDINATOR_INTERRUPTED
        unresolved = recovered.unresolved_target_runs[0]
        assert unresolved.world_found
        assert len(unresolved.committed_new_customer_ids or []) == 1
        directory = next(p for p in root.iterdir() if p.is_dir())
        assert verify_experiment(directory) == []
        records, problems = read_journal(directory / JOURNAL)
        assert problems == []
        assert [r.kind for r in records].count("target_run_intent") == 1  # never replayed
        with ReadOnlyWorldView(database) as view:
            assert sum(c.created_by_call > 0 for c in view.all_customers()) == 1

        removed = docker_runner.reap_orphans(now=time.time() + 3_600)
        assert removed
    finally:
        if process.poll() is None:
            process.kill()
        docker_runner.reap_orphans(now=time.time() + 3_600)
