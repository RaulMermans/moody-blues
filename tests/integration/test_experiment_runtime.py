"""The integrated runtime on real Docker: real Python in a real container proposes actions,
the coordinator validates them, a real world and Oracle produce the outcome.

Targets are deterministic reference executors or labeled provider fixtures. Nothing here is
evidence of model behavior.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from moody_blues.contracts.common import ExecutionStatus
from moody_blues.contracts.experiment_evidence import (
    ActionDecision,
    ExperimentLimits,
    ExperimentSpec,
    ExperimentState,
    ExperimentTermination,
    OutcomeClass,
)
from moody_blues.contracts.oracle import FindingCode, Verdict
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.experiments.demo import DEMO_CASES, run_case
from moody_blues.experiments.programs import probe_program
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.target import ReferenceTarget
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from tests.conftest import limits

pytestmark = pytest.mark.docker


@pytest.fixture(autouse=True)
def _assert_no_leftovers(docker_runner: DockerSandboxRunner) -> Iterator[None]:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    yield
    after = {c.id for c in docker_runner.list_sandbox_containers()}
    assert after - before == set(), "sandbox container was not cleaned up"


def test_observation_feedback_cycle_in_real_containers(
    docker_runner: DockerSandboxRunner, tmp_path: Path
) -> None:
    """C4-B: the final step's output depends on what earlier steps were told."""
    coordinator = ExperimentCoordinator(
        sandbox=docker_runner,
        target=ReferenceTarget("blind_retry"),
        root=tmp_path,
        sandbox_limits=limits(),
    )
    code = probe_program(
        scenario_id="phantom-failure", config="baseline", looking_for="duplicate_side_effect"
    )
    evidence = coordinator.run(ExperimentSpec(label="feedback", code=code))

    assert evidence.status is ExperimentState.COMPLETED
    assert len(evidence.steps) == 4
    runs = {x.sandbox_run_id for s in evidence.steps for x in s.sandbox}
    assert len(runs) == 4, "every step must be a separate disposable container"
    assert all(x.status is ExecutionStatus.SUCCEEDED for s in evidence.steps for x in s.sandbox)
    assert all(not x.network_enabled for s in evidence.steps for x in s.sandbox)
    assert all(s.decision is ActionDecision.AUTHORIZED for s in evidence.steps)
    assert evidence.sandbox_supplied is not None
    assert evidence.sandbox_supplied.conclusion == "behavior_observed"
    assert "2 matching records" in evidence.sandbox_supplied.summary


def test_end_to_end_verdict_comes_from_committed_state(
    docker_runner: DockerSandboxRunner, tmp_path: Path
) -> None:
    """C4-C / C4-D: sandbox -> coordinator -> target -> CRM -> Oracle, with traceable layers."""
    case = next(c for c in DEMO_CASES if c.case_id == "phantom-failure-duplicate")
    evidence = run_case(case, sandbox=docker_runner, root=tmp_path, sandbox_limits=limits())
    (run,) = evidence.target_runs
    assert run.evidence_source == "reference_executor"
    assert run.authorized.fault_source == "scenario"
    assert run.target_observed.tool_trace[0].fault_effect == "committed_write_reported_as_failure"
    assert len(run.committed.new_ids) == 2
    assert run.oracle.verdict is Verdict.VIOLATION
    assert FindingCode.DUPLICATE_SIDE_EFFECT in {f.code for f in run.oracle.findings}
    assert OutcomeClass.ORACLE_VIOLATION in evidence.classifications
    assert verify_experiment(tmp_path / evidence.experiment_id) == []


@pytest.mark.parametrize("case", DEMO_CASES, ids=lambda c: c.case_id)
def test_every_demonstration_path(
    case: object, docker_runner: DockerSandboxRunner, tmp_path: Path
) -> None:
    from moody_blues.experiments.demo import DemoCase

    assert isinstance(case, DemoCase)
    evidence = run_case(case, sandbox=docker_runner, root=tmp_path, sandbox_limits=limits())
    assert evidence.status is case.expected_status
    assert verify_experiment(tmp_path / evidence.experiment_id) == []


def test_experiment_code_error_is_a_sandbox_failure(
    docker_runner: DockerSandboxRunner, tmp_path: Path
) -> None:
    coordinator = ExperimentCoordinator(
        sandbox=docker_runner,
        target=ReferenceTarget("trusting"),
        root=tmp_path,
        sandbox_limits=limits(),
        limits=ExperimentLimits(),
    )
    code = (
        'emit({"protocol": "mb-exp/1", "action": "finish_experiment",'
        ' "conclusion": "inconclusive"})\nraise ValueError("after emitting")\n'
    )
    evidence = coordinator.run(ExperimentSpec(label="crash", code=code))
    assert evidence.termination is ExperimentTermination.SANDBOX_EXIT_NONZERO
    assert "ValueError" in evidence.steps[0].sandbox[0].stderr_excerpt
    assert evidence.sandbox_supplied is None
