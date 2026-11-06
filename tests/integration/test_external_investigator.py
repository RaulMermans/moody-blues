"""The Investigator's workflow against external targets, with no sandbox doubles.

Real containers run the agents and the experiments; worlds, gateway and Oracle are real. The
Investigator's model and the agent's model are labeled fixtures, so this proves the path and the
boundaries. It says nothing about how any LLM behaves.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.adapter import ExternalAgentRecord, ModelCallStatus
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, TargetRunEvidence
from moody_blues.contracts.investigation import InvestigationReport, TargetKind
from moody_blues.contracts.oracle import Verdict
from moody_blues.explorer.jobs import BUNDLE
from moody_blues.external.bundle import build_bundle
from moody_blues.external.commands import (
    EXAMPLES,
    LiveRequest,
    external_workflow,
    fixture_broker,
    investigate,
    publish_run,
)
from moody_blues.external.fixtures import Policy
from moody_blues.external.selection import external_provenance
from moody_blues.external.target import LiveInference
from moody_blues.investigator.preflight import run_preflight
from moody_blues.investigator.workspace import verify_investigation
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from tests.conftest import make_settings

pytestmark = pytest.mark.docker
WORLD = "normal-success"


@pytest.fixture
def settings(docker_runner: DockerSandboxRunner, tmp_path: Path) -> Settings:
    resolved = make_settings(artifacts_dir=tmp_path / "artifacts")
    report = run_preflight(resolved)
    assert report.status == "PASS", [c.name for c in report.checks if c.status != "PASS"]
    return resolved


@pytest.fixture(autouse=True)
def _no_leftovers(docker_runner: DockerSandboxRunner) -> Iterator[None]:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    yield
    assert {c.id for c in docker_runner.list_sandbox_containers()} <= before


def _investigate(
    settings: Settings, name: str, kind: TargetKind, policy: Policy | None = None
) -> tuple[InvestigationReport, list[TargetRunEvidence]]:
    artifacts = settings.artifacts_dir
    assert artifacts is not None
    bundle = build_bundle(EXAMPLES / f"{name}.agent.toml")
    broker = fixture_broker(WORLD, policy=policy) if policy else None
    report = external_workflow(
        settings,
        bundle,
        artifacts=artifacts,
        live=LiveInference(broker=broker, ledger=None) if broker else None,
        provenance=external_provenance(kind, bundle, broker),
    ).run()
    directory = artifacts / "investigations" / report.investigation_id
    assert verify_investigation(directory, artifacts / "experiments") == []
    runs = [
        run
        for ref in report.experiments
        for run in ExperimentEvidence.model_validate_json(
            (artifacts / "experiments" / ref.experiment_id / "evidence.json").read_text("utf-8")
        ).target_runs
    ]
    return report, runs


def _external(run: TargetRunEvidence) -> ExternalAgentRecord:
    assert run.external is not None
    return run.external


def test_case_a_a_careful_script_in_a_real_container(settings: Settings) -> None:
    report, runs = _investigate(settings, "careful", TargetKind.EXTERNAL_SCRIPTED)
    assert len(runs) == 2
    assert all(r.oracle.verdict is Verdict.PASS for r in runs)
    assert all(_external(r).environment.execution_mode == "docker_sandbox" for r in runs)  # pyright: ignore[reportOptionalMemberAccess]
    assert report.hypotheses[1].hypothesis.revises == "h1"


def test_case_b_an_unsafe_script_in_a_real_container(settings: Settings) -> None:
    _, runs = _investigate(settings, "unsafe", TargetKind.EXTERNAL_SCRIPTED)
    assert runs[0].oracle.verdict is Verdict.VIOLATION


def test_case_c_the_llm_agent_in_a_real_container_on_a_fixture(settings: Settings) -> None:
    report, runs = _investigate(settings, "llm", TargetKind.EXTERNAL_LLM, "verify")
    run = runs[0]
    record = _external(run)
    assert run.evidence_source == "offline_fixture"
    assert record.model_calls >= 3
    assert all(r.status is ModelCallStatus.COMPLETED for r in record.model_requests)
    assert run.target_observed.tool_trace
    assert run.oracle.verdict is Verdict.PASS
    assert report.request.target is not None
    assert report.request.target.model_broker == "offline_fixture"


def test_case_c_a_blind_fixture_model_is_caught_in_a_real_container(settings: Settings) -> None:
    _, runs = _investigate(settings, "llm", TargetKind.EXTERNAL_LLM, "blind")
    assert runs[0].oracle.verdict is Verdict.VIOLATION
    assert runs[0].evidence_source == "offline_fixture"


def test_case_e_the_command_runs_and_publishes_an_investigation(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    code = investigate(
        settings,
        kind=TargetKind.EXTERNAL_LLM,
        manifest=EXAMPLES / "llm.agent.toml",
        world=WORLD,
        live=LiveRequest(),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "labeled fixture" in out
    assert settings.artifacts_dir is not None
    assert list((settings.artifacts_dir / "live-jobs").rglob(BUNDLE))


def test_the_internal_target_still_runs_through_the_same_command(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    code = investigate(
        settings, kind=TargetKind.INTERNAL_LLM, manifest=None, world=WORLD, live=LiveRequest()
    )
    assert code == 0
    assert "internal_llm" in capsys.readouterr().out


def test_a_published_llm_run_projects_into_a_bundle(settings: Settings) -> None:
    report, _ = _investigate(settings, "llm", TargetKind.EXTERNAL_LLM, "verify")
    assert settings.artifacts_dir is not None
    assert publish_run(report, settings.artifacts_dir, settings).startswith("job_")
