"""Reports are recomputed from records, keep their denominators, and apply the registered rule."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from moody_blues.contracts.investigation import Strategy
from moody_blues.evaluation.adaptation import AdaptationScore
from moody_blues.evaluation.journal import Journal
from moody_blues.evaluation.manifest import Manifest, TrialPlan
from moody_blues.evaluation.report import (
    StrategyMetrics,
    build_results,
    conclude,
    strategy_metrics,
    write_results,
)
from moody_blues.evaluation.suites import UnitSummary, run_causal
from moody_blues.evaluation.trials import TrialRecord
from tests.evaluation.conftest import STALE_6, StubCausalExecutor, trial
from tests.evaluation.test_suites import weak_under_lag


def _unit(strategy: str, block: int = 1) -> UnitSummary:
    return UnitSummary(
        unit_id=f"s{block}-{strategy}",
        block=block,
        strategy=strategy,
        investigation_id="inv",
        state="completed",
        termination="plan_finished",
        experiments_with_run=1,
        programs_generated=0,
        programs_rejected=0,
        refinements=0,
        cited_observations=0,
        hypothesis_revisions=0,
        model_calls=0,
        investigator_tokens=0,
        investigator_cost_usd=0.0,
        target_tokens=0,
        target_cost_usd=0.0,
        wall_ms=0,
        usage_complete=True,
        claims_made=0,
        unsupported_claims=0,
    )


def _as_strategy(t: TrialRecord, strategy: str, unit: str | None = None) -> TrialRecord:
    return t.model_copy(update={"strategy": strategy, "unit_id": unit or f"s1-{strategy}"})


def _metrics(manifest: Manifest, strategy: str, trials: list[TrialRecord]) -> StrategyMetrics:
    return strategy_metrics(manifest, strategy, trials, [_unit(strategy)])


def _adaptation(*, level_3: bool = True, level_4: bool = True) -> AdaptationScore:
    return AdaptationScore(
        cases=[],
        answers=0,
        provider_errors=0,
        cited_total=0,
        level_1_sensitive_cases=0,
        level_2_reasoning_valid=0,
        level_2_assessed=0,
        level_3_meaningful_cases=0,
        level_4_improved_cases=0,
        level_4_cases_measured=0,
        level_1_pass=False,
        level_3_pass=level_3,
        level_4_pass=level_4,
    )


def _discoveries(
    manifest: Manifest, fixed: int, one_shot: int, adaptive: int, root: Path
) -> dict[str, StrategyMetrics]:
    out: dict[str, StrategyMetrics] = {}
    hit = trial(root, executor="verify_then_report", faults=STALE_6)
    for strategy, count in (
        (Strategy.FIXED.value, fixed),
        (Strategy.ONE_SHOT.value, one_shot),
        (Strategy.ADAPTIVE.value, adaptive),
    ):
        trials = [_as_strategy(hit, strategy, f"s{i}") for i in range(count)]
        out[strategy] = _metrics(manifest, strategy, trials)
    return out


def test_advantage_needs_discovery_and_adaptation(tmp_path: Path, manifest: Manifest) -> None:
    metrics = _discoveries(manifest, 0, 1, 3, tmp_path / "e")
    assert conclude(metrics, _adaptation(), complete=True)[0] == "ADAPTIVE_ADVANTAGE_SUPPORTED"
    assert conclude(metrics, _adaptation(level_3=False), complete=True)[0] == "INCONCLUSIVE"
    assert conclude(metrics, _adaptation(level_4=False), complete=True)[0] == "INCONCLUSIVE"


def test_a_tie_is_no_demonstrated_advantage(tmp_path: Path, manifest: Manifest) -> None:
    metrics = _discoveries(manifest, 2, 1, 2, tmp_path / "e")
    assert conclude(metrics, _adaptation(), complete=True)[0] == "NO_DEMONSTRATED_ADVANTAGE"


def test_fixed_winning_is_no_demonstrated_advantage(tmp_path: Path, manifest: Manifest) -> None:
    metrics = _discoveries(manifest, 3, 0, 1, tmp_path / "e")
    assert conclude(metrics, _adaptation(), complete=True)[0] == "NO_DEMONSTRATED_ADVANTAGE"


def test_too_few_discoveries_cannot_separate_strategies(tmp_path: Path, manifest: Manifest) -> None:
    metrics = _discoveries(manifest, 0, 0, 1, tmp_path / "e")
    assert conclude(metrics, _adaptation(), complete=True)[0] == "INCONCLUSIVE"


def test_an_unfinished_evaluation_is_inconclusive(tmp_path: Path, manifest: Manifest) -> None:
    metrics = _discoveries(manifest, 0, 0, 3, tmp_path / "e")
    assert conclude(metrics, _adaptation(), complete=False)[0] == "INCONCLUSIVE"
    assert conclude(metrics, None, complete=True)[0] == "INCONCLUSIVE"


def test_an_impaired_violation_is_not_a_verified_discovery(
    tmp_path: Path, manifest: Manifest
) -> None:
    hit = trial(tmp_path / "e", executor="verify_then_report", faults=STALE_6, truncated=1)
    metrics = _metrics(manifest, "adaptive", [_as_strategy(hit, "adaptive")])
    assert metrics.units_with_any_violation == 1
    assert metrics.units_with_verified_discovery == 0


def test_coverage_is_scored_on_the_condition_that_really_ran(
    tmp_path: Path, manifest: Manifest
) -> None:
    ran = trial(tmp_path / "e", executor="idempotent_retry", faults=STALE_6)
    metrics = _metrics(manifest, "fixed", [_as_strategy(ran, "fixed")])
    assert metrics.units_testing_known_condition == 1
    assert metrics.units_testing_long_stale_baseline == 1
    assert metrics.runs_at_known_condition == 1
    assert metrics.units_with_verified_discovery == 0  # tested it and did not fail: coverage only


def test_results_are_written_inspectably(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    causal = Journal(tmp_path / "causal.jsonl")
    run_causal(
        manifest, plan, executor=StubCausalExecutor(tmp_path / "e", weak_under_lag), journal=causal
    )
    results, trials = build_results(
        manifest,
        plan,
        causal=causal,
        strategies=Journal(tmp_path / "strategies.jsonl"),
        adaptation=Journal(tmp_path / "adaptation.jsonl"),
        registered_at="abc",
    )
    assert results.conclusion == "INCONCLUSIVE"
    assert results.attribution_baseline is not None
    assert results.attribution_baseline.level.value == "causal_evidence_supports_fault"
    out = tmp_path / "out"
    write_results(out, results, trials, manifest)
    assert json.loads((out / "results.json").read_text("utf-8"))["manifest_id"]
    rows = list(csv.DictReader((out / "trials.csv").open(encoding="utf-8")))
    assert len(rows) == len(trials)
    assert {"experiment_id", "evidence_ref", "eligible", "category"} <= set(rows[0])
    text = (out / "results.md").read_text("utf-8")
    assert "stale-6/baseline" in text
    assert "95% exact CI" in text
    assert "NOT_RUN" in text  # the adaptation suite did not run, and the report says so
