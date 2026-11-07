"""`evidence-verify` on real evidence from a real workflow, over a real process boundary.

The model is the labeled fixture and the agent a local process double: this is about the records.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from moody_blues.cli import evidence_verify
from moody_blues.config import Settings
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, TargetRunEvidence
from moody_blues.contracts.investigation import TargetKind
from moody_blues.contracts.oracle import Verdict
from moody_blues.explorer.integrity import (
    audit_artifacts,
    check_model_calls,
    check_oracle,
    check_tool_calls,
    check_world,
)
from moody_blues.external.bundle import build_bundle
from tests.external.test_investigator_target import CAREFUL, _investigate  # pyright: ignore


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _investigate(tmp_path, build_bundle(CAREFUL), TargetKind.EXTERNAL_SCRIPTED)
    return tmp_path


def _tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _evidence_paths(root: Path) -> list[Path]:
    return sorted((root / "experiments").glob("*/evidence.json"))


def _run(root: Path) -> TargetRunEvidence:
    text = _evidence_paths(root)[0].read_text(encoding="utf-8")
    return ExperimentEvidence.model_validate_json(text).target_runs[0]


def test_intact_evidence_passes_every_check_that_applies(root: Path) -> None:
    audit = audit_artifacts(root)
    assert audit.intact, audit.problems
    assert audit.investigations == 1
    assert audit.runs >= 1
    for check in ("journal and hashes", "run report", "tool calls", "oracle findings"):
        assert audit.checked[check] > 0


def test_it_writes_nothing(root: Path) -> None:
    before = _tree(root)
    audit_artifacts(root)
    assert _tree(root) == before


def test_an_edited_evidence_file_is_caught(root: Path) -> None:
    path = _evidence_paths(root)[0]
    path.write_text(path.read_text(encoding="utf-8").replace("PASS", "VIOLATION"), encoding="utf-8")
    audit = audit_artifacts(root)
    assert not audit.intact
    assert "journal and hashes" in audit.problems


def test_evidence_that_no_longer_parses_is_a_finding_and_not_a_crash(root: Path) -> None:
    path = _evidence_paths(root)[0]
    path.write_text(
        path.read_text(encoding="utf-8").replace('"completed"', '"x"'), encoding="utf-8"
    )
    audit = audit_artifacts(root)
    assert any("schema" in p for p in audit.problems["journal and hashes"])


def test_an_edited_run_report_is_caught(root: Path) -> None:
    run = _run(root)
    path = _evidence_paths(root)[0].parent / run.report_path
    report = json.loads(path.read_text(encoding="utf-8"))
    report["oracle"]["verdict"] = "VIOLATION"
    path.write_text(json.dumps(report), encoding="utf-8")
    audit = audit_artifacts(root)
    assert "journal and hashes" in audit.problems
    assert "run report" in audit.problems


def test_a_verdict_that_does_not_follow_from_its_findings_is_caught(root: Path) -> None:
    run = _run(root)
    assert check_oracle(run) == []
    flipped = run.oracle.model_copy(update={"verdict": Verdict.VIOLATION})
    assert check_oracle(run.model_copy(update={"oracle": flipped}))


def test_a_violated_invariant_with_no_finding_is_caught(root: Path) -> None:
    run = _run(root)
    invented = run.oracle.invariants_evaluated[:1]
    oracle = run.oracle.model_copy(update={"invariants_violated": invented})
    assert check_oracle(run.model_copy(update={"oracle": oracle}))


def test_a_miscounted_fault_is_caught(root: Path) -> None:
    run = _run(root)
    assert check_tool_calls(run) == []
    observed = run.target_observed.model_copy(
        update={"faults_delivered": run.target_observed.faults_delivered + 1}
    )
    assert check_tool_calls(run.model_copy(update={"target_observed": observed}))


def test_a_script_labeled_with_model_calls_is_caught(root: Path) -> None:
    run = _run(root)
    assert run.external is not None
    assert check_model_calls(run) == []
    record = run.external.model_copy(update={"model_calls": 1})
    assert check_model_calls(run.model_copy(update={"external": record}))


def test_two_world_ids_in_one_run_are_caught(root: Path) -> None:
    run = _run(root)
    assert check_world(run) == []
    oracle = run.oracle.model_copy(update={"world_id": "wld_other"})
    assert check_world(run.model_copy(update={"oracle": oracle}))


def test_a_changed_bundle_is_caught(tmp_path: Path, root: Path) -> None:
    job = root / "live-jobs" / "job_x"
    job.mkdir(parents=True)
    (job / "bundle.json").write_text("{}", encoding="utf-8")
    name = next((root / "investigations").iterdir()).name
    (job / "job.json").write_text(
        json.dumps({"evidence_available": True, "bundle_sha256": "0", "investigation_id": name}),
        encoding="utf-8",
    )
    assert "published bundle" in audit_artifacts(root).problems


def test_an_empty_directory_verifies_nothing_and_does_not_pass(tmp_path: Path) -> None:
    assert not audit_artifacts(tmp_path).intact
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert evidence_verify(settings, tmp_path) == 2
    assert not (tmp_path / "investigations").exists()


def test_a_missing_directory_is_refused_and_not_made(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    missing = tmp_path / "nothing"
    assert evidence_verify(settings, missing) == 2
    assert not missing.exists()
