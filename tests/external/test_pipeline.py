"""An external agent inside the real coordinator, investigation and evidence pipeline.

Scenarios 14 and 15 of the evaluation plan, and the failure rules that live at this level. The
experiment sandbox and the agent's sandbox are labeled test doubles; everything else is real. The
same flow runs with no doubles in tests/integration/test_external_agent.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient

from moody_blues.contracts.agent import AgentRunReport
from moody_blues.contracts.experiment_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    EXTERNAL_EVIDENCE_SCHEMA_VERSION,
    ExperimentAuthorship,
    ExperimentEvidence,
    ExperimentLimits,
    ExperimentSpec,
    ExperimentState,
    ExperimentTermination,
    OutcomeClass,
)
from moody_blues.contracts.explorer import ExecutionMode, InvestigationBundle
from moody_blues.contracts.investigation import (
    InvestigationLimits,
    InvestigationReport,
    InvestigationRequest,
    WorldTier,
)
from moody_blues.contracts.oracle import Verdict
from moody_blues.experiments import coordinator as coordinator_module
from moody_blues.experiments.recovery import recover_interrupted, verify_experiment
from moody_blues.experiments.target import ReferenceTarget, TargetPort
from moody_blues.experiments.workspace import JOURNAL
from moody_blues.explorer.factories import REHEARSAL_SEQUENCE
from moody_blues.explorer.projection import build_bundle as project
from moody_blues.external.bundle import build_bundle
from moody_blues.external.commands import publish_run
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.investigator.fixtures import FIXTURE_MODEL, ObservationDrivenFixture
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow
from moody_blues.investigator.workspace import verify_investigation
from tests.conftest import make_settings
from tests.experiment.conftest import (
    SANDBOX_LIMITS,
    ScriptedSandbox,
    coordinator,
    finish_action,
    inspect_action,
    run_action,
)
from tests.explorer.conftest import explorer_app
from tests.external.conftest import EXAMPLES, FAST, LIMITS, LocalProcessRunner, fixture_manifest
from tests.investigator.conftest import PF, PS, ApprovedSandbox, experiment

SPEC = ExperimentSpec(label="adapter test", code="# the test double supplies stdout\n")


def _target(tmp_path: Path, manifest: Path) -> ExternalAgentTarget:
    return ExternalAgentTarget(
        runner=LocalProcessRunner(tmp_path / "procs"),
        bundle=build_bundle(manifest),
        sandbox_limits=LIMITS,
        limits=FAST,
    )


def _example(tmp_path: Path, name: str) -> ExternalAgentTarget:
    return _target(tmp_path, EXAMPLES / f"{name}.agent.toml")


def _experiment(
    tmp_path: Path, target: TargetPort, steps: list[Any], limits: ExperimentLimits | None = None
) -> ExperimentEvidence:
    root = tmp_path / "experiments"
    root.mkdir(exist_ok=True)
    return coordinator(ScriptedSandbox(steps), target, root, limits).run(SPEC)


def test_the_coordinator_runs_an_external_agent_unchanged(tmp_path: Path) -> None:
    evidence = _experiment(
        tmp_path,
        _example(tmp_path, "unsafe"),
        [run_action("phantom-failure"), inspect_action("state_summary"), finish_action()],
    )
    assert evidence.status is ExperimentState.COMPLETED
    run = evidence.target_runs[0]
    assert run.target_kind == "external_agent"
    assert run.evidence_source == "external_scripted"
    assert run.oracle.verdict is Verdict.VIOLATION
    assert OutcomeClass.ORACLE_VIOLATION in evidence.classifications
    assert OutcomeClass.EXPECTED_ENVIRONMENTAL_FAULT in evidence.classifications
    assert run.authorized.faults  # the coordinator's grant, not the agent's choice
    assert evidence.observations[0].kind == "target_run"


def test_external_evidence_verifies_and_is_marked_version_2(tmp_path: Path) -> None:
    evidence = _experiment(tmp_path, _example(tmp_path, "careful"), [run_action(), finish_action()])
    directory = tmp_path / "experiments" / evidence.experiment_id
    assert evidence.schema_version == EXTERNAL_EVIDENCE_SCHEMA_VERSION
    assert verify_experiment(directory) == []
    stored = ExperimentEvidence.model_validate_json((directory / "evidence.json").read_text())
    assert stored.target_runs[0].external == evidence.target_runs[0].external
    report = directory / evidence.target_runs[0].report_path
    assert AgentRunReport.model_validate_json(report.read_text()).external is not None


def test_an_edited_external_record_fails_verification(tmp_path: Path) -> None:
    evidence = _experiment(tmp_path, _example(tmp_path, "careful"), [run_action(), finish_action()])
    directory = tmp_path / "experiments" / evidence.experiment_id
    path = directory / "evidence.json"
    path.write_text(path.read_text().replace('"PASS"', '"VIOLATION"', 1))
    assert verify_experiment(directory)


def test_an_internal_run_is_written_exactly_as_before(tmp_path: Path) -> None:
    evidence = _experiment(
        tmp_path, ReferenceTarget("verify_then_report"), [run_action(), finish_action()]
    )
    assert evidence.schema_version == EVIDENCE_SCHEMA_VERSION
    directory = tmp_path / "experiments" / evidence.experiment_id
    raw = json.loads((directory / "evidence.json").read_text())
    assert "external" not in raw["target_runs"][0]
    assert raw["schema_version"] == 1


def test_an_agent_that_never_ran_ends_the_experiment(tmp_path: Path) -> None:
    target = _target(tmp_path, fixture_manifest(tmp_path, "CrashesAtImport"))
    evidence = _experiment(tmp_path, target, [run_action()])
    assert evidence.status is ExperimentState.FAILED
    assert evidence.termination is ExperimentTermination.TARGET_FAILED
    assert OutcomeClass.TARGET_AGENT_FAILURE in evidence.classifications
    assert len(evidence.target_runs) == 1  # it stays on the record


def test_a_crashed_agent_is_a_finding_about_the_agent_and_the_experiment_goes_on(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path, fixture_manifest(tmp_path, "CreatesThenCrashes"))
    evidence = _experiment(tmp_path, target, [run_action(), finish_action()])
    assert evidence.status is ExperimentState.COMPLETED
    assert OutcomeClass.TARGET_AGENT_FAILURE in evidence.classifications
    assert OutcomeClass.ORACLE_VIOLATION in evidence.classifications


def test_cancellation_reaches_the_agent_and_closes_the_experiment(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    root.mkdir()
    cancel = Event()
    target = _target(tmp_path, fixture_manifest(tmp_path, "ObeysCancel"))

    class Cancels(ScriptedSandbox):
        def run(self, request: Any, *, cancel: Event | None = None) -> Any:
            result = super().run(request, cancel=cancel)
            import threading

            threading.Timer(0.5, self._cancel.set).start()
            return result

        _cancel = cancel

    evidence = coordinator(Cancels([run_action()]), target, root).run(SPEC, cancel=cancel)
    assert evidence.status is ExperimentState.CANCELLED
    assert OutcomeClass.CANCELLATION in evidence.classifications
    assert evidence.target_runs[0].oracle is not None  # the Oracle still read the world


def test_evidence_write_failure_is_uncertain_and_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run happened and its report could not be saved. Nothing may pretend otherwise."""
    target = _target(tmp_path, fixture_manifest(tmp_path, "CreatesThenCrashes"))
    real = coordinator_module.atomic_write

    def fails_on_reports(path: Path, text: str) -> str:
        if path.parent.name == "runs":
            raise OSError("disk full")
        return real(path, text)

    monkeypatch.setattr(coordinator_module, "atomic_write", fails_on_reports)
    evidence = _experiment(tmp_path, target, [run_action()])
    assert evidence.status is ExperimentState.UNCERTAIN
    unresolved = evidence.unresolved_target_runs[0]
    assert unresolved.world_found
    assert unresolved.committed_new_customer_ids  # the real commits, read back from the world
    assert evidence.target_runs == []
    assert len(target._runner.sessions) == 1  # pyright: ignore  # never retried


def test_recovery_reads_external_runs_and_keeps_their_version(tmp_path: Path) -> None:
    """A coordinator that died after a finished run, read back from its journal."""
    evidence = _experiment(tmp_path, _example(tmp_path, "careful"), [run_action(), finish_action()])
    directory = tmp_path / "experiments" / evidence.experiment_id
    journal = directory / JOURNAL
    lines = journal.read_text().splitlines()
    kept = [line for line in lines if json.loads(line)["kind"] != "experiment_finished"]
    journal.write_text("\n".join(kept) + "\n")
    (directory / "evidence.json").unlink()
    [recovered] = recover_interrupted(tmp_path / "experiments")
    assert recovered.schema_version == EXTERNAL_EVIDENCE_SCHEMA_VERSION
    assert recovered.status is ExperimentState.FAILED
    assert recovered.termination is ExperimentTermination.COORDINATOR_INTERRUPTED
    assert recovered.target_runs[0].external is not None
    assert recovered.target_runs[0].oracle.verdict is Verdict.PASS


def _investigation(
    artifacts: Path, agent: str
) -> tuple[InvestigationReport, InvestigationWorkflow]:
    limits = InvestigationLimits(max_experiments=2, max_model_calls=3, max_wall_seconds=120)
    target = _example(artifacts, agent)
    (artifacts / "experiments").mkdir(parents=True, exist_ok=True)
    workflow = InvestigationWorkflow(
        request=InvestigationRequest(
            objective="test objective",
            tier=WorldTier.DEVELOPMENT,
            world_ids=("normal-success",),
            investigator_model=FIXTURE_MODEL,
            target_model=f"external:acme-crm-{agent}",
            limits=limits,
        ),
        runner=ExperimentRunner(
            sandbox=ApprovedSandbox(
                [*experiment(faults=[PF]), *experiment(faults=[PS])],
            ),
            target=target,
            root=artifacts / "experiments",
            sandbox_limits=SANDBOX_LIMITS,
        ),
        root=artifacts / "investigations",
        model=InvestigatorModel(
            inference=ObservationDrivenFixture("normal-success", REHEARSAL_SEQUENCE),
            evidence="offline_fixture",
            model=FIXTURE_MODEL,
            provider=None,
            spend=None,
            max_completion_tokens=limits.max_completion_tokens,
            temperature=limits.temperature,
        ),
    )
    return workflow.run(), workflow


@pytest.fixture
def unsafe_investigation(tmp_path: Path) -> InvestigationReport:
    report, _ = _investigation(tmp_path, "unsafe")
    return report


def test_a_whole_investigation_can_target_an_external_agent(
    tmp_path: Path, unsafe_investigation: InvestigationReport
) -> None:
    report = unsafe_investigation
    directory = tmp_path / "investigations" / report.investigation_id
    assert verify_investigation(directory, tmp_path / "experiments") == []
    assert report.experiments
    assert any(f.oracle_verdict is Verdict.VIOLATION for f in report.findings)
    assert all(f.target_evidence_source == "external_scripted" for f in report.findings)


def test_the_existing_projection_shows_who_ran_and_says_it_is_no_model(
    tmp_path: Path, unsafe_investigation: InvestigationReport
) -> None:
    bundle = project(
        tmp_path / "investigations" / unsafe_investigation.investigation_id,
        tmp_path / "experiments",
        mode=ExecutionMode.REHEARSAL,
    )
    assert bundle.summary.target_evidence == ["external_scripted"]
    assert bundle.summary.target_model == "external:acme-crm-unsafe"
    run = bundle.runs[0]
    assert run.target_kind == "external_agent"
    assert run.external is not None
    assert run.external.name == "Acme CRM agent (unsafe script)"
    assert run.external.uses_model is False
    assert run.agent.mission is not None
    assert run.agent.mission.text.startswith("Mission:")
    assert "submit_final_claim" not in run.agent.mission.text
    assert any(d for d in run.discrepancies)  # the same reality comparison as any other run


def test_a_published_run_is_served_by_the_real_api_to_an_operator_only(
    tmp_path: Path, unsafe_investigation: InvestigationReport
) -> None:
    investigation = unsafe_investigation.investigation_id
    token = "t" * 40
    settings = make_settings(artifacts_dir=tmp_path)
    publish_run(unsafe_investigation, tmp_path, settings)
    app = explorer_app(tmp_path, operator_token=token)
    with TestClient(app) as client:
        public = client.get(f"/investigations/{investigation}")
        operator = client.get(
            f"/investigations/{investigation}",
            headers={"authorization": f"Bearer {token}"},
        )
        listed = client.get("/investigations", headers={"authorization": f"Bearer {token}"})
    assert public.status_code == 404
    assert operator.status_code == 200, operator.text
    assert investigation in listed.text
    body = operator.json()
    assert body["summary"]["target_evidence"] == ["external_scripted"]


def test_bundle_round_trips_through_its_schema(
    tmp_path: Path, unsafe_investigation: InvestigationReport
) -> None:
    bundle = project(
        tmp_path / "investigations" / unsafe_investigation.investigation_id,
        tmp_path / "experiments",
        mode=ExecutionMode.REHEARSAL,
    )
    assert InvestigationBundle.model_validate_json(bundle.model_dump_json()) == bundle


def test_authorship_is_unchanged_by_the_target(tmp_path: Path) -> None:
    evidence = _experiment(tmp_path, _example(tmp_path, "careful"), [run_action(), finish_action()])
    assert evidence.authorship is ExperimentAuthorship.DEVELOPER_SCRIPT
    assert SANDBOX_LIMITS.network_enabled is False
