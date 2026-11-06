"""Historical CRM evidence stays readable, verifiable and unwritten-to.

The raw records are git-ignored, so the second test is blocked in a clean clone. The committed
bundles are checked by ``test_recorded.py``, which rebuilds them byte for byte from those records.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from moody_blues.contracts.experiment_evidence import ExperimentEvidence
from moody_blues.contracts.explorer import InvestigationBundle
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.investigator.validity import run_validity

REPO = Path(__file__).parents[2]
EXPERIMENTS = REPO / ".artifacts" / "experiments"
BUNDLES = [*sorted((REPO / "evidence/recorded").glob("inv_*.json"))]


@pytest.mark.parametrize("path", BUNDLES, ids=lambda p: p.stem)
def test_a_recorded_bundle_reads_as_the_crm_with_no_new_fields(path: Path) -> None:
    bundle = InvestigationBundle.model_validate_json(path.read_text(encoding="utf-8"))
    assert bundle.validity is None
    for run in bundle.runs:
        assert run.world is None  # mapped when read, never written back
        assert run.validity is None
        assert run.actual.records == []


@pytest.mark.skipif(
    not EXPERIMENTS.is_dir(),
    reason="BLOCKED_BY_LOCAL_DEPENDENCY: raw records are git-ignored and absent from this clone",
)
def test_every_raw_historical_experiment_still_verifies_and_maps_to_the_crm() -> None:
    directories = sorted(p for p in EXPERIMENTS.iterdir() if (p / "evidence.json").is_file())
    assert directories
    for directory in directories:
        raw = (directory / "evidence.json").read_bytes()
        evidence = ExperimentEvidence.model_validate_json(raw)
        assert evidence.schema_version in {1, 2}
        assert verify_experiment(directory) == []
        for run in evidence.target_runs:
            assert run.world is None
            assert run.world_type == "crm"
            assert run.plugin_version == "legacy"
            run_validity(run)  # read from the trace; nothing is stored
        assert (directory / "evidence.json").read_bytes() == raw
