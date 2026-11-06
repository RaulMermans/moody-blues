"""Real SIGKILLs during a Job Queue run: real containers, world, recovery and evidence.

The CRM's equivalents are in ``test_external_agent_containment.py``. Nothing here is replayed, and
what a dead run did is read back from the queue's own file, never from what the agent said.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from moody_blues.contracts.experiment_evidence import (
    ExperimentEvidence,
    ExperimentState,
    ExperimentTermination,
)
from moody_blues.experiments.recovery import recover_interrupted, verify_experiment
from moody_blues.experiments.workspace import EVIDENCE, JOURNAL, read_journal
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from moody_blues.world.jobqueue.store import ReadOnlyJobView
from moody_blues.world.registry import load_any_scenario, world_plugin
from moody_blues.world.store import DB_FILENAME
from tests.external.conftest import fixture_manifest

pytestmark = pytest.mark.docker
REPO = Path(__file__).resolve().parents[2]
SCOPES = ("queue:read", "queue:write")


def _start(root: Path, manifest: Path) -> subprocess.Popen[bytes]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MOODY_VULTR")}
    return subprocess.Popen(  # noqa: S603 - fixed argv, test driver in this repository
        [sys.executable, "-m", "tests.external.queue_crash_driver", str(root), str(manifest)],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _jobs(database: Path) -> int:
    """A world being created has a file before it has a table, and then it holds no job."""
    try:
        with ReadOnlyJobView(database) as view:
            return len(view.all_jobs())
    except sqlite3.OperationalError:
        return 0


def _wait_for_job(root: Path, seconds: float = 40) -> Path:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for database in root.glob(f"*/worlds/*/{DB_FILENAME}"):
            if _jobs(database):
                return database
        time.sleep(0.1)
    raise AssertionError("the agent never committed a job")


def _clear(docker_runner: DockerSandboxRunner, before: set[str | None]) -> None:
    for container in docker_runner.list_sandbox_containers():
        if container.id not in before:
            docker_runner.reap_orphans(now=time.time() + 3_600)
            return


def test_coordinator_killed_mid_run_is_uncertain_and_creates_no_second_job(
    docker_runner: DockerSandboxRunner, tmp_path: Path
) -> None:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    root = tmp_path / "experiments"
    root.mkdir()
    process = _start(root, fixture_manifest(tmp_path, "QueueCommitsThenHangs", scopes=SCOPES))
    try:
        database = _wait_for_job(root)
        process.send_signal(signal.SIGKILL)
        process.wait(timeout=10)
        assert [c for c in docker_runner.list_sandbox_containers() if c.id not in before]

        [recovered] = recover_interrupted(root)
        assert recovered.status is ExperimentState.UNCERTAIN
        assert recovered.termination is ExperimentTermination.COORDINATOR_INTERRUPTED
        unresolved = recovered.unresolved_target_runs[0]
        assert unresolved.world_found
        assert len(unresolved.committed_new_record_ids or []) == 1
        assert unresolved.committed_new_customer_ids is None

        directory = next(p for p in root.iterdir() if p.is_dir())
        assert verify_experiment(directory) == []
        records, problems = read_journal(directory / JOURNAL)
        assert problems == []
        assert [r.kind for r in records].count("target_run_intent") == 1  # never replayed

        # Recovering again changes nothing, and the Oracle can still read the queue's own file.
        assert recover_interrupted(root) == []
        assert _jobs(database) == 1
        plugin, scenario = world_plugin("job-queue"), load_any_scenario("jq-normal")
        with ReadOnlyJobView(database) as view:
            report = plugin.verify(view, scenario, None)
        assert report.objective_satisfied

        assert docker_runner.reap_orphans(now=time.time() + 3_600)
        assert not [c for c in docker_runner.list_sandbox_containers() if c.id not in before]
    finally:
        if process.poll() is None:
            process.kill()
        _clear(docker_runner, before)


def test_a_run_after_a_crash_gets_its_own_queue(
    docker_runner: DockerSandboxRunner, tmp_path: Path
) -> None:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    root = tmp_path / "experiments"
    root.mkdir()
    hanging = fixture_manifest(tmp_path, "QueueCommitsThenHangs", scopes=SCOPES)
    first = _start(root, hanging)
    second: subprocess.Popen[bytes] | None = None
    try:
        crashed = _wait_for_job(root)
        first.send_signal(signal.SIGKILL)
        first.wait(timeout=10)
        recover_interrupted(root)
        docker_runner.reap_orphans(now=time.time() + 3_600)

        second = _start(root, hanging)
        deadline = time.monotonic() + 40
        others: list[Path] = []
        while time.monotonic() < deadline and not others:
            others = [
                p for p in root.glob(f"*/worlds/*/{DB_FILENAME}") if p != crashed and _jobs(p) > 0
            ]
            time.sleep(0.1)
        assert others, "the second run never committed"
        assert _jobs(crashed) == 1
        assert _jobs(others[0]) == 1
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.kill()
        _clear(docker_runner, before)


def test_agent_killed_mid_run_ends_with_the_oracle_reading_the_queue(
    docker_runner: DockerSandboxRunner, tmp_path: Path
) -> None:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    root = tmp_path / "experiments"
    root.mkdir()
    process = _start(root, fixture_manifest(tmp_path, "QueueCommitsThenHangs", scopes=SCOPES))
    try:
        _wait_for_job(root)
        [agent] = [c for c in docker_runner.list_sandbox_containers() if c.id not in before]
        subprocess.run(  # noqa: S603 - fixed argv, a container this test started
            ["docker", "kill", "--signal=KILL", str(agent.id)],  # noqa: S607
            check=True,
            capture_output=True,
        )
        process.wait(timeout=60)

        directory = next(p for p in root.iterdir() if p.is_dir())
        evidence = ExperimentEvidence.model_validate_json(
            (directory / EVIDENCE).read_text(encoding="utf-8")
        )
        [run] = evidence.target_runs
        assert run.target_observed.claim is None  # a dead agent claims nothing
        assert len(run.committed.new_ids) == 1
        assert run.oracle.verdict.value in {"PASS", "INCONCLUSIVE", "VIOLATION"}
        assert run.target_observed.termination != "final_claim"
        assert verify_experiment(directory) == []
        assert evidence.unresolved_target_runs == []
        records, _ = read_journal(directory / JOURNAL)
        assert [r.kind for r in records].count("target_run_intent") == 1
        assert not [c for c in docker_runner.list_sandbox_containers() if c.id not in before]
    finally:
        if process.poll() is None:
            process.kill()
        _clear(docker_runner, before)
