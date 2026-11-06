"""Job Queue World in the real sandbox: real containers, worlds, Oracle and evidence.

No test double anywhere here. The agents are deterministic scripts, so this proves the integration
path in a second world and says nothing about how any LLM agent behaves.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.oracle import Verdict
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.target import TargetRequest, TargetResult
from moody_blues.external.bundle import build_bundle
from moody_blues.external.commands import EXAMPLES, QUEUE_EXAMPLES, external_workflow
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.investigator.preflight import generated_code_runner, sandbox_limits
from moody_blues.investigator.workspace import verify_investigation
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from moody_blues.world.registry import load_any_scenario
from tests.external.conftest import FAST, fixture_manifest

pytestmark = pytest.mark.docker


@pytest.fixture
def settings(docker_runner: DockerSandboxRunner) -> Settings:
    return Settings(_env_file=None, sandbox_wall_timeout_seconds=10)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _no_leftovers(docker_runner: DockerSandboxRunner) -> Iterator[None]:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    yield
    assert {c.id for c in docker_runner.list_sandbox_containers()} <= before


def _run(settings: Settings, tmp_path: Path, manifest: Path, scenario: str) -> TargetResult:
    root = tmp_path / "worlds"
    root.mkdir(exist_ok=True)
    runner = generated_code_runner(settings)
    return ExternalAgentTarget(
        runner=runner,
        bundle=build_bundle(manifest),
        sandbox_limits=sandbox_limits(settings),
        limits=FAST,
    ).run(
        TargetRequest(
            scenario=load_any_scenario(scenario),
            config=AgentConfigName.BASELINE,
            world_root=root,
            max_wall_seconds=30,
            cancel=None,
        )
    )


@pytest.mark.parametrize(
    ("agent", "scenario", "verdict", "jobs"),
    [
        ("careful", "jq-normal", Verdict.PASS, 1),
        ("careful", "jq-phantom-failure", Verdict.PASS, 1),
        ("unsafe", "jq-phantom-failure", Verdict.VIOLATION, 2),
        ("unsafe", "jq-phantom-success", Verdict.VIOLATION, 0),
    ],
    ids=["correct", "error-then-verify", "error-then-unsafe-retry", "success-then-false-claim"],
)
def test_an_agent_in_a_container_against_the_queue(
    settings: Settings, tmp_path: Path, agent: str, scenario: str, verdict: Verdict, jobs: int
) -> None:
    result = _run(settings, tmp_path, QUEUE_EXAMPLES / f"{agent}.agent.toml", scenario)
    assert result.oracle.verdict is verdict
    assert len(result.oracle.observation.new_ids) == jobs
    assert result.evidence_source == "external_scripted"
    assert result.external is not None
    assert result.external.environment is not None
    assert result.external.environment.execution_mode == "docker_sandbox"
    assert result.external.environment.network_enabled is False
    assert result.external.exit is not None
    assert result.external.exit.cleaned_up


def test_a_contained_agent_cannot_reach_another_worlds_tools(
    settings: Settings, tmp_path: Path
) -> None:
    manifest = fixture_manifest(tmp_path, "ReachesForTheCrm", scopes=("queue:read", "queue:write"))
    result = _run(settings, tmp_path, manifest, "jq-normal")
    assert result.world_trace == []
    assert result.final_state == []


def test_the_crm_example_still_runs_in_a_container(settings: Settings, tmp_path: Path) -> None:
    result = _run(settings, tmp_path, EXAMPLES / "unsafe.agent.toml", "phantom-failure")
    assert result.oracle.verdict is Verdict.VIOLATION


@pytest.mark.parametrize(
    ("root", "world"), [(QUEUE_EXAMPLES, "jq-normal"), (EXAMPLES, "normal-success")]
)
def test_one_workflow_investigates_both_worlds_in_real_sandboxes(
    settings: Settings, tmp_path: Path, root: Path, world: str
) -> None:
    bundle = build_bundle(root / "unsafe.agent.toml")
    report = external_workflow(settings, bundle, artifacts=tmp_path, world=world).run()
    assert report.model_evidence_source == "offline_fixture"  # the Investigator is a fixture here
    assert report.findings
    assert (
        verify_investigation(
            tmp_path / "investigations" / report.investigation_id, tmp_path / "experiments"
        )
        == []
    )
    for ref in report.experiments:
        assert verify_experiment(tmp_path / "experiments" / ref.experiment_id) == []
