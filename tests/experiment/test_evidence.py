"""Evidence integrity and crash recovery over real files (OFFLINE)."""

from __future__ import annotations

from pathlib import Path

from moody_blues.contracts.experiment_evidence import (
    ExperimentSpec,
    ExperimentState,
    ExperimentTermination,
)
from moody_blues.contracts.world import ToolName
from moody_blues.experiments.recovery import recover_interrupted, verify_experiment
from moody_blues.experiments.target import ReferenceTarget
from moody_blues.experiments.workspace import JOURNAL, ExperimentWorkspace, read_journal
from moody_blues.world.engine import World
from tests.experiment.conftest import ScriptedSandbox, coordinator, finish_action, run_action

SPEC = ExperimentSpec(label="test", code="pass\n")


def finished(tmp_path: Path) -> Path:
    sandbox = ScriptedSandbox([run_action("phantom-failure"), finish_action()])
    evidence = coordinator(sandbox, ReferenceTarget("blind_retry"), tmp_path).run(SPEC)
    return tmp_path / evidence.experiment_id


def test_intact_experiment_verifies(tmp_path: Path) -> None:
    assert verify_experiment(finished(tmp_path)) == []


def test_edited_verdict_is_detected(tmp_path: Path) -> None:
    directory = finished(tmp_path)
    path = directory / "evidence.json"
    path.write_text(path.read_text().replace('"VIOLATION"', '"PASS"'))
    assert any("does not match the hash" in p for p in verify_experiment(directory))


def test_edited_run_report_is_detected(tmp_path: Path) -> None:
    directory = finished(tmp_path)
    (report,) = (directory / "runs").iterdir()
    report.write_text(report.read_text() + " ")
    assert any("does not match its recorded hash" in p for p in verify_experiment(directory))


def test_edited_journal_is_detected(tmp_path: Path) -> None:
    directory = finished(tmp_path)
    path = directory / JOURNAL
    path.write_text(path.read_text().replace("phantom-failure", "normal-success"))
    assert any("altered" in p for p in verify_experiment(directory))


def test_removed_journal_line_is_detected(tmp_path: Path) -> None:
    directory = finished(tmp_path)
    path = directory / JOURNAL
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:2] + lines[3:]) + "\n")
    assert any("does not chain" in p for p in verify_experiment(directory))


def test_workspace_is_private_and_worlds_are_removed_after_a_clean_close(tmp_path: Path) -> None:
    directory = finished(tmp_path)
    assert directory.stat().st_mode & 0o077 == 0
    assert not (directory / "worlds").exists()


def test_evidence_is_written_before_the_journal_says_finished(tmp_path: Path) -> None:
    records, problems = read_journal(finished(tmp_path) / JOURNAL)
    assert problems == []
    assert records[-1].kind == "experiment_finished"
    assert records[-1].payload["evidence_sha256"]


# --- recovery -------------------------------------------------------------------------------


def interrupted(tmp_path: Path, *, with_write: bool) -> Path:
    """Reproduce what a killed coordinator leaves: an open journal and, optionally, a world."""
    workspace = ExperimentWorkspace(tmp_path, "exp_dead")
    workspace.journal(
        "experiment_created",
        {
            "experiment_id": "exp_dead",
            "parent_investigation_id": None,
            "label": "dead",
            "code_sha256": "0" * 64,
            "limits": {},
            "protocol": "mb-exp/1",
            "created_at": "2026-11-03T00:00:00+00:00",
        },
    )
    if with_write:
        from moody_blues.world.scenarios import load_scenario

        scenario = load_scenario("normal-success")
        workspace.journal(
            "target_run_intent",
            {"run_ref": "trun_1", "authorized": {"scenario_id": "normal-success"}},
        )
        world = World(scenario, root_dir=workspace.worlds_dir)
        target = scenario.objective.customer
        world.gateway.call(ToolName.CREATE_CUSTOMER, {"name": target.name, "email": target.email})
        world.close(remove=False)
    workspace.release()
    return workspace.directory


def test_interrupted_target_run_is_uncertain_and_reports_committed_rows(tmp_path: Path) -> None:
    directory = interrupted(tmp_path, with_write=True)
    (evidence,) = recover_interrupted(tmp_path)
    assert evidence.status is ExperimentState.UNCERTAIN
    assert evidence.termination is ExperimentTermination.COORDINATOR_INTERRUPTED
    (unresolved,) = evidence.unresolved_target_runs
    assert unresolved.world_found
    assert len(unresolved.committed_new_customer_ids or []) == 1
    assert evidence.target_runs == []  # no verdict is invented
    assert verify_experiment(directory) == []


def test_interruption_with_no_effects_is_failed_not_uncertain(tmp_path: Path) -> None:
    interrupted(tmp_path, with_write=False)
    (evidence,) = recover_interrupted(tmp_path)
    assert evidence.status is ExperimentState.FAILED
    assert evidence.unresolved_target_runs == []


def test_recovery_is_idempotent(tmp_path: Path) -> None:
    interrupted(tmp_path, with_write=True)
    assert len(recover_interrupted(tmp_path)) == 1
    assert recover_interrupted(tmp_path) == []


def test_recovery_leaves_finished_experiments_alone(tmp_path: Path) -> None:
    finished(tmp_path)
    assert recover_interrupted(tmp_path) == []


def test_recovery_skips_an_experiment_with_a_live_owner(tmp_path: Path) -> None:
    workspace = ExperimentWorkspace(tmp_path, "exp_live")
    workspace.journal("experiment_created", {})
    assert recover_interrupted(tmp_path) == []
    workspace.release()


def test_torn_final_line_does_not_block_recovery(tmp_path: Path) -> None:
    directory = interrupted(tmp_path, with_write=False)
    with (directory / JOURNAL).open("a") as f:
        f.write('{"seq": 2, "at"')
    records, problems = read_journal(directory / JOURNAL)
    assert len(records) == 1
    assert problems
