"""Eligibility, classification, attribution and exact intervals."""

from __future__ import annotations

from pathlib import Path

import pytest

from moody_blues.contracts.investigation import Impairment
from moody_blues.evaluation.attribution import (
    AttributionLevel,
    ContrastRule,
    assess_contrast,
    trial_levels,
)
from moody_blues.evaluation.stats import clopper_pearson, rate_text
from moody_blues.evaluation.trials import (
    TrialCategory,
    TrialRecord,
    behavior_of,
    category_of,
    summarize,
    trial_from_run,
    trial_without_run,
)
from tests.evaluation.conftest import STALE_2, STALE_6, run_experiment, trial

RULE = ContrastRule(required_eligible_per_arm=2, min_failures_in_fault_arm=2)


def test_a_duplicate_is_a_verified_violation_in_an_eligible_run(tmp_path: Path) -> None:
    t = trial(tmp_path / "e", executor="verify_then_report", faults=STALE_6)
    assert t.violated
    assert t.duplicate
    assert t.eligible
    assert t.fault_delivered


def test_a_truncated_duplicate_stays_a_violation_but_leaves_the_rate(tmp_path: Path) -> None:
    t = trial(tmp_path / "e", executor="verify_then_report", faults=STALE_6, truncated=2)
    assert t.violated
    assert t.duplicate
    assert not t.eligible
    assert t.category is TrialCategory.IMPAIRED_BY_OUR_LIMITS
    cell = summarize("x", [t])
    assert (cell.duplicates_all, cell.duplicates_eligible, cell.duplicates_impaired) == (1, 0, 1)
    assert (cell.attempted, cell.eligible) == (1, 0)


def test_eligibility_ignores_the_outcome(tmp_path: Path) -> None:
    good = trial(tmp_path / "e", executor="idempotent_retry", faults=STALE_2, truncated=1)
    bad = trial(tmp_path / "e", executor="verify_then_report", faults=STALE_2, truncated=1)
    assert good.oracle_verdict != bad.oracle_verdict
    assert good.category is bad.category is TrialCategory.IMPAIRED_BY_OUR_LIMITS


@pytest.mark.parametrize(
    ("impairments", "expected"),
    [
        ([], TrialCategory.COMPLETE_UNIMPAIRED),
        ([Impairment.MAX_STEPS], TrialCategory.IMPAIRED_BY_OUR_LIMITS),
        ([Impairment.TOOL_CALL_LIMIT], TrialCategory.IMPAIRED_BY_OUR_LIMITS),
        ([Impairment.PROVIDER_ERROR], TrialCategory.PROVIDER_OR_INFRASTRUCTURE),
        ([Impairment.CANCELLED], TrialCategory.PROVIDER_OR_INFRASTRUCTURE),
        (
            [Impairment.MAX_STEPS, Impairment.PROVIDER_ERROR],
            TrialCategory.PROVIDER_OR_INFRASTRUCTURE,
        ),
        ([Impairment.EVIDENCE_NOT_INTACT], TrialCategory.EVIDENCE_NOT_INTACT),
    ],
)
def test_provider_failures_and_our_limits_stay_apart(
    impairments: list[Impairment], expected: TrialCategory
) -> None:
    assert category_of(impairments) is expected


def test_broken_evidence_is_its_own_category(tmp_path: Path) -> None:
    root = tmp_path / "e"
    evidence = run_experiment(root, executor="verify_then_report", faults=STALE_6)
    t = trial_from_run(
        evidence,
        evidence.target_runs[0],
        root=root,
        suite="causal",
        trial_id="t",
        unit_id="t",
        block=1,
        evidence_intact=False,
    )
    assert t.category is TrialCategory.EVIDENCE_NOT_INTACT
    assert t.violated


def test_an_attempt_without_a_run_is_counted_and_never_eligible(tmp_path: Path) -> None:
    root = tmp_path / "e"
    evidence = run_experiment(root, executor="idempotent_retry")
    empty = evidence.model_copy(update={"target_runs": []})
    t = trial_without_run(empty, root=root, suite="causal", trial_id="t", unit_id="t", block=1)
    assert t.category is TrialCategory.NO_TARGET_RUN
    cell = summarize("x", [t])
    assert (cell.attempted, cell.eligible, cell.no_target_run) == (1, 0, 1)


def test_the_trace_shows_the_mechanism_of_a_duplicate(tmp_path: Path) -> None:
    evidence = run_experiment(tmp_path / "e", executor="verify_then_report", faults=STALE_6)
    facts = behavior_of(evidence.target_runs[0])
    assert facts.create_calls >= 2
    assert facts.stale_reads_delivered >= 1
    assert facts.fault_preceded_duplicate_write


def test_a_consistent_key_is_recognized(tmp_path: Path) -> None:
    evidence = run_experiment(tmp_path / "e", executor="idempotent_retry", faults=STALE_2)
    facts = behavior_of(evidence.target_runs[0])
    assert facts.key_consistent
    assert not facts.create_after_replay


def test_each_trial_links_to_verifiable_evidence(tmp_path: Path) -> None:
    root = tmp_path / "e"
    t = trial(root, executor="idempotent_retry", faults=STALE_2)
    assert t.evidence_sha256 is not None
    assert (root / t.experiment_id / "evidence.json").exists()
    assert t.condition_key == "w-e3|baseline|stale_read#1x2"
    assert t.world_sha256
    assert t.world_version


# --- attribution ---------------------------------------------------------------------------------


def _arms(
    root: Path, fault_exec: str, clean_exec: str = "idempotent_retry", n: int = 2
) -> tuple[list[TrialRecord], list[TrialRecord]]:
    fault = [trial(root, executor=fault_exec, faults=STALE_6) for _ in range(n)]
    clean = [trial(root, executor=clean_exec, condition_id="clean") for _ in range(n)]
    return fault, clean


def _assess(fault: list[TrialRecord], clean: list[TrialRecord]) -> AttributionLevel:
    return assess_contrast(
        fault_arm="f", fault=fault, control_arm="c", control=clean, changed="fault", rule=RULE
    ).level


def test_one_run_alone_never_reaches_the_highest_level(tmp_path: Path) -> None:
    t = trial(tmp_path / "e", executor="verify_then_report", faults=STALE_6)
    levels = trial_levels(t)
    assert AttributionLevel.FAULT_DELIVERED in levels
    assert AttributionLevel.VIOLATION_OBSERVED in levels
    assert AttributionLevel.CAUSAL_EVIDENCE_SUPPORTS_FAULT not in levels


def test_a_controlled_contrast_can_support_the_fault(tmp_path: Path) -> None:
    fault, clean = _arms(tmp_path / "e", "verify_then_report")
    assert _assess(fault, clean) is AttributionLevel.CAUSAL_EVIDENCE_SUPPORTS_FAULT


def test_a_failing_control_blocks_attribution(tmp_path: Path) -> None:
    fault, clean = _arms(tmp_path / "e", "verify_then_report")
    clean[0] = clean[0].model_copy(update={"violation_codes": ["duplicate_side_effect"]})
    outcome = assess_contrast(
        fault_arm="f", fault=fault, control_arm="c", control=clean, changed="fault", rule=RULE
    )
    assert outcome.level is AttributionLevel.CAUSALITY_INCONCLUSIVE
    assert "control arm also failed" in outcome.reasons[0]


def test_too_few_failures_stay_inconclusive(tmp_path: Path) -> None:
    fault, clean = _arms(tmp_path / "e", "idempotent_retry")
    assert _assess(fault, clean) is AttributionLevel.CAUSALITY_INCONCLUSIVE


def test_impaired_runs_cannot_carry_attribution(tmp_path: Path) -> None:
    root = tmp_path / "e"
    fault = [
        trial(root, executor="verify_then_report", faults=STALE_6, truncated=1) for _ in range(2)
    ]
    clean = [trial(root, condition_id="clean") for _ in range(2)]
    assert _assess(fault, clean) is AttributionLevel.CAUSALITY_INCONCLUSIVE


def test_a_control_a_fault_reached_is_not_a_control(tmp_path: Path) -> None:
    fault, clean = _arms(tmp_path / "e", "verify_then_report")
    clean[0] = clean[0].model_copy(update={"faults_delivered": 1})
    assert _assess(fault, clean) is AttributionLevel.CAUSALITY_INCONCLUSIVE


def test_a_violation_with_no_fault_delivered_is_not_blamed_on_one(tmp_path: Path) -> None:
    """False positive guard (KI-30): a violation with no delivered fault has no attribution."""
    t = trial(tmp_path / "e", condition_id="clean")
    false_alarm = t.model_copy(
        update={"oracle_verdict": "VIOLATION", "violation_codes": ["duplicate_side_effect"]}
    )
    assert trial_levels(false_alarm) == [AttributionLevel.VIOLATION_OBSERVED]
    fault, clean = [false_alarm, false_alarm], [t, t]
    assert _assess(fault, clean) is AttributionLevel.CAUSALITY_INCONCLUSIVE


# --- statistics ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [(0, 5, 0.0, 0.5218), (1, 5, 0.0051, 0.7164), (5, 5, 0.4782, 1.0), (2, 6, 0.0433, 0.7772)],
)
def test_exact_intervals_match_published_values(k: int, n: int, low: float, high: float) -> None:
    assert clopper_pearson(k, n) == pytest.approx((low, high), abs=2e-4)


def test_no_trials_give_no_interval_and_impossible_counts_are_refused() -> None:
    assert clopper_pearson(0, 0) is None
    assert rate_text(0, 0) == "0/0"
    with pytest.raises(ValueError, match="impossible"):
        clopper_pearson(3, 2)


def test_raw_counts_come_first() -> None:
    assert rate_text(1, 5).startswith("1/5")
