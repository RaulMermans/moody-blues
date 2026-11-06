"""The developer CLI performs real runs (no canned output)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from moody_blues import cli


def test_world_demo_runs_real_cases_and_writes_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MOODY_ARTIFACTS_DIR", str(tmp_path))
    code = cli.main(["world-demo", "--no-color", "--case", "unsafe-retry", "--case", "normal"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Layer B" in out
    assert "Layer A" in out
    assert "Truth Oracle: VIOLATION" in out
    report = json.loads((tmp_path / "world-demo" / "unsafe-retry.json").read_text())
    assert report["oracle"]["verdict"] == "VIOLATION"
    assert len(report["oracle"]["observation"]["objective_matching_ids"]) == 2
    # The printed ids are the ids actually persisted in this run.
    for cid in report["oracle"]["observation"]["objective_matching_ids"]:
        assert cid in out


def test_world_run_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        ["world-run", "--scenario", "phantom-success", "--executor", "trusting", "--json"]
    )
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["oracle"]["verdict"] == "VIOLATION"
    assert report["final_state"]
    assert all(c["created_by_call"] == 0 for c in report["final_state"])


def test_world_run_rejects_unknown_executor() -> None:
    with pytest.raises(SystemExit):
        cli.main(["world-run", "--scenario", "normal-success", "--executor", "nope"])
