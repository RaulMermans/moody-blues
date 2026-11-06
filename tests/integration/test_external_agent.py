"""External agents in the real sandbox: real containers, worlds, Oracle and evidence.

No test double anywhere here. The agents are deterministic scripts, so this proves the integration
path and says nothing about how any LLM agent behaves.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from threading import Event, Timer

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.adapter import AdapterRejectionCode
from moody_blues.contracts.agent import AgentConfigName, TerminationReason
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, TargetRunEvidence
from moody_blues.contracts.investigation import InvestigationReport
from moody_blues.contracts.oracle import Verdict
from moody_blues.contracts.sandbox import SandboxRequest
from moody_blues.experiments.target import TargetRequest, TargetResult
from moody_blues.explorer.jobs import JobStore
from moody_blues.external.bundle import build_bundle
from moody_blues.external.commands import EXAMPLES, external_workflow, publish_run
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.investigator.preflight import generated_code_runner, run_preflight, sandbox_limits
from moody_blues.investigator.workspace import verify_investigation
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from moody_blues.sandbox.session import ReadStatus, SessionClosedError
from moody_blues.world.scenarios import load_scenario
from tests.external.conftest import FAST, fixture_manifest

pytestmark = pytest.mark.docker
T = TerminationReason


@pytest.fixture
def settings(docker_runner: DockerSandboxRunner) -> Settings:
    return Settings(_env_file=None, sandbox_wall_timeout_seconds=10)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _no_leftovers(docker_runner: DockerSandboxRunner) -> Iterator[None]:
    before = {c.id for c in docker_runner.list_sandbox_containers()}
    yield
    assert {c.id for c in docker_runner.list_sandbox_containers()} <= before


def _run(
    settings: Settings,
    tmp_path: Path,
    manifest: Path,
    *,
    scenario: str = "normal-success",
    cancel: Event | None = None,
    limits: object = FAST,
) -> TargetResult:
    target = ExternalAgentTarget(
        runner=generated_code_runner(settings),
        bundle=build_bundle(manifest),
        sandbox_limits=sandbox_limits(settings),
        limits=limits,  # pyright: ignore[reportArgumentType]
    )
    root = tmp_path / f"worlds-{time.monotonic_ns()}"
    root.mkdir()
    return target.run(
        TargetRequest(
            scenario=load_scenario(scenario),
            config=AgentConfigName.BASELINE,
            world_root=root,
            max_wall_seconds=30,
            cancel=cancel,
        )
    )


def _investigate(settings: Settings, tmp_path: Path, name: str) -> InvestigationReport:
    return external_workflow(
        settings, build_bundle(EXAMPLES / f"{name}.agent.toml"), artifacts=tmp_path
    ).run()


def _runs(tmp_path: Path, report: InvestigationReport) -> list[TargetRunEvidence]:
    out: list[TargetRunEvidence] = []
    for ref in report.experiments:
        text = (tmp_path / "experiments" / ref.experiment_id / "evidence.json").read_text()
        out.extend(ExperimentEvidence.model_validate_json(text).target_runs)
    return out


def test_the_preflight_passes_on_this_host(settings: Settings) -> None:
    assert run_preflight(settings).status == "PASS"


def test_a_full_investigation_separates_the_two_example_agents(
    settings: Settings, tmp_path: Path
) -> None:
    careful_root, unsafe_root = tmp_path / "careful", tmp_path / "unsafe"
    careful_root.mkdir()
    unsafe_root.mkdir()
    careful = _investigate(settings, careful_root, "careful")
    unsafe = _investigate(settings, unsafe_root, "unsafe")

    careful_runs = _runs(careful_root, careful)
    unsafe_runs = _runs(unsafe_root, unsafe)
    assert careful_runs
    assert unsafe_runs
    assert all(r.oracle.verdict is Verdict.PASS for r in careful_runs)
    assert any(r.oracle.verdict is Verdict.VIOLATION for r in unsafe_runs)
    for root, report in ((careful_root, careful), (unsafe_root, unsafe)):
        directory = root / "investigations" / report.investigation_id
        assert verify_investigation(directory, root / "experiments") == []


def test_evidence_names_the_real_environment(settings: Settings, tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    report = _investigate(settings, tmp_path / "a", "careful")
    run = _runs(tmp_path / "a", report)[0]
    record = run.external
    assert record is not None
    assert record.environment is not None
    assert record.exit is not None
    assert run.target_kind == "external_agent"
    assert run.evidence_source == "external_scripted"
    assert record.environment.execution_mode == "docker_sandbox"
    assert record.environment.network_enabled is False
    assert "@sha256:" in record.environment.image
    assert record.environment.image_id
    assert record.exit.cleaned_up
    assert record.exit.exit_code == 0
    assert not record.exit.killed_by_host


def test_a_published_run_lands_where_the_pages_read_it(settings: Settings, tmp_path: Path) -> None:
    report = _investigate(settings, tmp_path, "unsafe")
    job_id = publish_run(report, tmp_path, settings)
    record = JobStore(tmp_path / "live-jobs").read(job_id)
    assert record is not None
    assert record.evidence_available
    assert record.mission_id == "external:acme-crm-unsafe"


def test_recovery_from_a_misleading_response_in_a_real_container(
    settings: Settings, tmp_path: Path
) -> None:
    result = _run(settings, tmp_path, EXAMPLES / "careful.agent.toml", scenario="phantom-failure")
    assert any(t.fault_injected for t in result.world_trace)
    assert result.oracle.verdict is Verdict.PASS


def test_a_verified_duplicate_in_a_real_container(settings: Settings, tmp_path: Path) -> None:
    result = _run(settings, tmp_path, EXAMPLES / "unsafe.agent.toml", scenario="phantom-failure")
    assert result.oracle.verdict is Verdict.VIOLATION
    assert len(result.oracle.observation.objective_matching_ids) == 2


def test_a_protocol_mismatch_in_a_real_container(settings: Settings, tmp_path: Path) -> None:
    result = _run(settings, tmp_path, fixture_manifest(tmp_path, "FutureProtocol"))
    assert result.termination == T.PROTOCOL_VERSION_MISMATCH.value
    assert result.external is not None
    assert result.external.rejection is not None
    assert result.external.rejection.code is AdapterRejectionCode.UNSUPPORTED_PROTOCOL


def test_a_crash_in_a_real_container_keeps_the_commits(settings: Settings, tmp_path: Path) -> None:
    result = _run(settings, tmp_path, fixture_manifest(tmp_path, "CreatesThenCrashes"))
    assert result.termination == T.ADAPTER_CRASHED.value
    assert result.external is not None
    assert result.external.exit is not None
    assert result.external.exit.exit_code == 9
    assert result.oracle.verdict is Verdict.VIOLATION


def test_a_hang_in_a_real_container_is_killed_and_removed(
    settings: Settings, tmp_path: Path
) -> None:
    started = time.monotonic()
    limits = FAST.model_copy(update={"run_timeout_seconds": 2})
    result = _run(settings, tmp_path, fixture_manifest(tmp_path, "Hangs"), limits=limits)
    assert result.termination == T.WALL_TIMEOUT.value
    assert result.external is not None
    assert result.external.exit is not None
    assert result.external.exit.killed_by_host
    assert result.external.exit.cleaned_up
    assert time.monotonic() - started < 15


def test_cancellation_in_a_real_container(settings: Settings, tmp_path: Path) -> None:
    cancel = Event()
    timer = Timer(2.0, cancel.set)
    timer.start()
    result = _run(settings, tmp_path, fixture_manifest(tmp_path, "ObeysCancel"), cancel=cancel)
    timer.cancel()
    assert result.termination == T.CANCELLED.value
    assert result.external is not None
    assert result.external.final is not None
    assert result.external.final.completion == "cancelled"


def test_malformed_output_in_a_real_container(settings: Settings, tmp_path: Path) -> None:
    result = _run(settings, tmp_path, fixture_manifest(tmp_path, "Oversized"))
    assert result.termination == T.MALFORMED_MESSAGE.value
    assert result.external is not None
    assert result.external.rejection is not None
    assert result.external.rejection.code is AdapterRejectionCode.OVERSIZED


def test_a_session_line_that_arrives_in_pieces_is_still_one_line(settings: Settings) -> None:
    code = """
import os, time
os.write(1, b'{"a"')
time.sleep(0.2)
os.write(1, b':1}\\n')
"""
    session = generated_code_runner(settings).open_session(
        SandboxRequest(code=code, limits=sandbox_limits(settings)), max_line_bytes=1_000
    )
    try:
        read = session.read_line(10)
        assert read.status is ReadStatus.LINE
        assert read.line == b'{"a":1}'
        assert session.read_line(10).status is ReadStatus.CLOSED
    finally:
        session.close()


def test_a_process_that_stops_reading_cannot_hold_the_host(settings: Settings) -> None:
    code = "import time\ntime.sleep(60)\n"
    session = generated_code_runner(settings).open_session(
        SandboxRequest(code=code, limits=sandbox_limits(settings)), max_line_bytes=1_000
    )
    started = time.monotonic()

    def flood() -> None:
        for _ in range(10_000):
            session.send(b"x" * 1_048_576)

    try:
        with pytest.raises(SessionClosedError):
            flood()
    finally:
        session.close()
    assert time.monotonic() - started < 30
