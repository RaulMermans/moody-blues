"""The export path: determinism, labeling, refusal, and the committed bundles themselves."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from moody_blues.contracts.explorer import ExecutionMode, InvestigationBundle
from moody_blues.explorer import recorded
from moody_blues.explorer.paths import REPO_ROOT
from moody_blues.explorer.projection import build_bundle
from moody_blues.explorer.sanitize import (
    EvidenceRefusedError,
    bounded,
    require_clean,
    scan,
)
from moody_blues.investigator.fixtures import conclude, propose
from tests.explorer.conftest import RECORDED
from tests.investigator.conftest import CODE, PS, Harness, experiment

SECRET = "not-a-real-key-for-this-test-only"


def investigated(root: Path) -> tuple[Path, Path]:
    h = Harness(
        root,
        replies=[propose(1, CODE), conclude()],
        steps=experiment(faults=[PS]),
    )
    report = h.run()
    return h.investigations / report.investigation_id, h.experiments


def test_committed_export_verifies() -> None:
    assert recorded.verify_export(RECORDED, None) == []


def test_committed_bundles_are_labeled_recorded_and_real() -> None:
    manifest = recorded.load_manifest(RECORDED)
    assert len(manifest.cases) == len(recorded.CURATED_CASES)
    for entry in manifest.cases:
        bundle = InvestigationBundle.model_validate_json((RECORDED / entry.file).read_text())
        assert bundle.summary.mode is ExecutionMode.RECORDED
        assert bundle.summary.investigator_evidence == "live_provider"
        assert "offline_fixture" not in bundle.summary.target_evidence
        assert bundle.provenance.source_report_sha256 == entry.source_report_sha256


def test_committed_bundles_carry_no_raw_prompts_or_paths() -> None:
    for path in RECORDED.glob("inv_*.json"):
        text = path.read_text(encoding="utf-8")
        for field in ("artifact_path", "report_path", "source_path", "spend_entry", "response_id"):
            assert f'"{field}"' not in text
        assert "You are a CRM Operations Agent" not in text  # the policy prompt stays private
        assert "You are the Investigator" not in text


def test_committed_files_stay_small() -> None:
    assert sum(p.stat().st_size for p in RECORDED.iterdir()) < 1_000_000


@pytest.mark.skipif(
    not (REPO_ROOT / ".artifacts" / "investigations").is_dir(),
    reason="BLOCKED_BY_LOCAL_DEPENDENCY: raw records are git-ignored and absent from this clone",
)
def test_committed_export_rebuilds_byte_for_byte_from_source() -> None:
    assert recorded.verify_export(RECORDED, REPO_ROOT / ".artifacts") == []


def test_projection_is_deterministic(tmp_path: Path) -> None:
    directory, experiments = investigated(tmp_path)
    one = build_bundle(directory, experiments, mode=ExecutionMode.REHEARSAL)
    two = build_bundle(directory, experiments, mode=ExecutionMode.REHEARSAL)
    assert recorded.render(one) == recorded.render(two)


def test_projection_refuses_an_edited_report(tmp_path: Path) -> None:
    directory, experiments = investigated(tmp_path)
    report = directory / "report.json"
    report.write_text(report.read_text().replace("completed", "failed", 1), encoding="utf-8")
    with pytest.raises(EvidenceRefusedError, match="does not verify"):
        build_bundle(directory, experiments, mode=ExecutionMode.REHEARSAL)


def test_projection_refuses_an_investigation_with_no_report(tmp_path: Path) -> None:
    directory, experiments = investigated(tmp_path)
    (directory / "report.json").unlink()
    with pytest.raises(EvidenceRefusedError):
        build_bundle(directory, experiments, mode=ExecutionMode.REHEARSAL)


def test_projection_refuses_missing_experiment_evidence(tmp_path: Path) -> None:
    directory, experiments = investigated(tmp_path)
    evidence = next(experiments.glob("exp_*/evidence.json"))
    evidence.unlink()
    with pytest.raises(EvidenceRefusedError):
        build_bundle(directory, experiments, mode=ExecutionMode.REHEARSAL)


def test_a_case_note_contradicted_by_evidence_stops_the_export(tmp_path: Path) -> None:
    directory, experiments = investigated(tmp_path)
    bundle = build_bundle(directory, experiments, mode=ExecutionMode.RECORDED)
    with pytest.raises(EvidenceRefusedError):
        recorded._check_case(recorded.CURATED_CASES[0], bundle)  # pyright: ignore[reportPrivateUsage]


def test_a_fixture_run_can_never_be_exported_as_recorded(tmp_path: Path) -> None:
    directory, experiments = investigated(tmp_path)
    bundle = build_bundle(directory, experiments, mode=ExecutionMode.RECORDED)
    case = recorded.CuratedCase(
        investigation_id=bundle.summary.investigation_id,
        kind=recorded.CaseKind.SUCCESSFUL_RECOVERY,
        title="t",
        summary="s",
        primary_run_id=None,
        expected_outcome=bundle.summary.outcome,
    )
    with pytest.raises(EvidenceRefusedError, match="fixture"):
        recorded._check_case(case, bundle)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("see /Users/someone/.env", "absolute_path"),
        ("mounted at /home/app/secrets", "absolute_path"),
        ("C:\\Users\\app", "windows_path"),
        ("wrote .artifacts/live-spend", "artifact_path"),
        ("Authorization: Bearer abcdef0123456789", "bearer_token"),
        ("key sk-abcdefghijklmnopqrstuvwx", "api_key_shape"),
        ("MOODY_VULTR_API_KEY=abc", "env_setting"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
    ],
)
def test_scan_catches_forbidden_content(text: str, hit: str) -> None:
    assert hit in scan(text)


def test_scan_finds_a_configured_secret_of_any_shape() -> None:
    assert scan(f"leaked {SECRET} here", secrets=(SECRET,)) == ["configured_secret"]


def test_scan_never_returns_the_match() -> None:
    with pytest.raises(EvidenceRefusedError) as caught:
        require_clean(json.dumps({"a": f"x {SECRET}"}), secrets=(SECRET,))
    assert SECRET not in str(caught.value)


def test_scan_reads_decoded_strings() -> None:
    """Regression: scanning escaped JSON read ``a:\\nb`` as the Windows path ``a:\\n``."""
    require_clean(json.dumps({"code": "if x:\n    y = 1\n", "key": "region: us-west"}))


def test_scan_covers_dictionary_keys() -> None:
    with pytest.raises(EvidenceRefusedError):
        require_clean(json.dumps({"/Users/x/.env": 1}))


def test_bounded_text_records_what_it_cut() -> None:
    cut = bounded("x" * 50, 10)
    assert (cut.text, cut.truncated, cut.original_chars) == ("x" * 10, True, 50)
    whole = bounded("short", 10)
    assert (whole.truncated, whole.original_chars) == (False, 5)
