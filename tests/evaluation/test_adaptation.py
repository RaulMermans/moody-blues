"""Scoring adaptation at four levels, and the isolation of non-adaptive planning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from moody_blues.contracts.investigation import InvestigationState, Strategy, WorldTier
from moody_blues.evaluation.adaptation import (
    BLIND,
    JUSTIFIED,
    AnswerRecord,
    action_class,
    context_for,
    outcome_of,
    relation,
    score,
    score_case,
)
from moody_blues.evaluation.manifest import Manifest
from moody_blues.investigator.catalog import WORLD_TIERS, target_capability
from moody_blues.investigator.context import build_messages
from moody_blues.investigator.evaluation import FollowUp
from moody_blues.investigator.fixtures import propose
from moody_blues.investigator.observations import observe
from moody_blues.investigator.workflow import InvestigationWorkflow
from tests.evaluation.conftest import run_experiment
from tests.investigator.conftest import CODE, Harness, experiment

SEED = "w-r1|baseline|phantom_failure#1"


@pytest.mark.parametrize(
    ("follow", "expected"),
    [
        (SEED, "same_condition"),
        ("w-r2|baseline|phantom_failure#1", "world_change"),
        ("w-r1|hardened|phantom_failure#1", "config_change"),
        ("w-r1|baseline|phantom_failure#2", "severity_change"),
        ("w-r1|baseline|stale_read#1x6", "family_change"),
        ("w-r1|baseline|none", "fault_removed"),
        ("w-r2|hardened|stale_read#1x6", "family_change"),
    ],
)
def test_what_changed_is_named(follow: str, expected: str) -> None:
    assert relation(SEED, follow) == expected


def _answer(decision: str = "propose") -> FollowUp:
    return FollowUp(
        decision=decision,  # type: ignore[arg-type]
        selection=None,
        source_sha256=None,
        experiment_id=None,
        cited_observation=True,
        hypothesis_status=None,
        prompt_sha256="p",
    )


def test_a_program_that_ran_nothing_is_not_a_changed_experiment() -> None:
    assert action_class(SEED, _answer(), None) == "no_target_run"
    assert action_class(SEED, _answer("conclude"), None) == "conclude"


def _record(case: str, branch: str, action: str, n: int, **extra: Any) -> list[AnswerRecord]:
    base: dict[str, Any] = {
        "decision": "propose",
        "seed_key": SEED,
        "follow_key": None,
        "hypothesis_status": None,
        "cited_observation": True,
        "follow_verdict": None,
        "follow_violations": [],
        "experiment_id": None,
        "source_sha256": None,
        "prompt_sha256": "p",
    }
    fields: dict[str, Any] = base | extra
    return [
        AnswerRecord(
            answer_id=f"{case}-{branch}-{i}",
            case_id=case,
            branch=branch,
            repeat=i,
            action=action,
            **fields,
        )
        for i in range(n)
    ]


def _case_answers(case: str, recovered: str, violation: str, blind: str) -> list[AnswerRecord]:
    return [
        *_record(case, "recovered", recovered, 4),
        *_record(case, "violation", violation, 4),
        *_record(case, BLIND, blind, 4),
    ]


def test_citing_an_observation_earns_nothing(manifest: Manifest) -> None:
    """Every answer cites one, and all do the same thing: no adaptation at any level."""
    suite = manifest.adaptation
    answers = [
        a
        for c in suite.cases
        for a in _case_answers(c.case_id, "same_condition", "same_condition", "same_condition")
    ]
    result = score(suite, answers)
    assert result.cited_total == len(answers)
    assert result.level_1_sensitive_cases == 0
    assert result.level_3_meaningful_cases == 0


def test_answers_a_blind_model_would_also_give_are_not_adaptation(manifest: Manifest) -> None:
    """family_change is justified after recovery, but blind answers do it anyway."""
    case = manifest.adaptation.cases[0]
    answers = _case_answers(case.case_id, "family_change", "same_condition", "family_change")
    scored = score_case(case, manifest.adaptation, answers)
    recovered = next(b for b in scored.branches if b.branch == "recovered")
    assert recovered.justified == recovered.answers
    assert recovered.delta == 0
    assert not scored.meaningful


def test_a_justified_change_beyond_the_blind_control_is_meaningful(manifest: Manifest) -> None:
    case = manifest.adaptation.cases[0]
    answers = _case_answers(case.case_id, "family_change", "config_change", "conclude")
    # "conclude" is justified after a violation, so the blind control must not be that for delta.
    answers = [a for a in answers if a.branch != BLIND] + _record(
        case.case_id, BLIND, "no_target_run", 4
    )
    scored = score_case(case, manifest.adaptation, answers)
    assert scored.sensitive
    assert scored.meaningful


def test_stopping_after_nothing_is_not_justified() -> None:
    assert "conclude" not in JUSTIFIED["recovered"]
    assert "conclude" not in JUSTIFIED["not_reached"]
    assert "conclude" not in JUSTIFIED["insufficient"]
    assert "conclude" in JUSTIFIED["violation"]


def test_repeating_a_condition_that_never_fired_is_not_justified() -> None:
    assert "same_condition" not in JUSTIFIED["not_reached"]


def test_provider_errors_leave_the_denominator_and_are_counted(manifest: Manifest) -> None:
    case = manifest.adaptation.cases[0]
    answers = [
        *_record(case.case_id, "recovered", "family_change", 3),
        *_record(case.case_id, "recovered", "provider_error", 1, decision="provider_error"),
        *_record(case.case_id, BLIND, "same_condition", 4),
    ]
    scored = score_case(case, manifest.adaptation, answers)
    recovered = next(b for b in scored.branches if b.branch == "recovered")
    assert (recovered.answers, recovered.provider_errors) == (3, 1)


def test_an_invalid_answer_stays_in_the_denominator(manifest: Manifest) -> None:
    case = manifest.adaptation.cases[0]
    answers = [
        *_record(case.case_id, "recovered", "family_change", 3),
        *_record(case.case_id, "recovered", "invalid", 1, decision="invalid"),
    ]
    scored = score_case(case, manifest.adaptation, answers)
    recovered = next(b for b in scored.branches if b.branch == "recovered")
    assert (recovered.justified, recovered.answers) == (3, 4)


def test_discovery_is_only_scored_where_a_weakness_exists(manifest: Manifest) -> None:
    case = next(c for c in manifest.adaptation.cases if not c.discovery_possible)
    scored = score_case(case, manifest.adaptation, [])
    assert scored.discovery_improved is None


def test_discovery_counts_verified_violations_not_intent(manifest: Manifest) -> None:
    case = next(c for c in manifest.adaptation.cases if c.discovery_possible)
    answers = [
        *_record(case.case_id, "recovered", "family_change", 3, follow_verdict="VIOLATION"),
        *_record(case.case_id, "recovered", "family_change", 1, follow_verdict="PASS"),
        *_record(case.case_id, BLIND, "family_change", 1, follow_verdict="VIOLATION"),
        *_record(case.case_id, BLIND, "same_condition", 3, follow_verdict="PASS"),
    ]
    scored = score_case(case, manifest.adaptation, answers)
    assert (scored.recovered_discoveries, scored.blind_discoveries) == (3, 1)
    assert scored.discovery_improved is True


# --- the registered branches really produce what they claim --------------------------------------


def test_every_registered_branch_produces_its_outcome(tmp_path: Path, manifest: Manifest) -> None:
    for case in manifest.adaptation.cases:
        for branch in case.branches:
            evidence = run_experiment(
                tmp_path / "e", executor=branch.executor, world=case.world, faults=branch.faults
            )
            observation = observe(evidence, observation_id="obs_1", proposal_id="prop_1")
            assert outcome_of(observation) == branch.outcome, (case.case_id, branch.outcome)


def test_discovery_cases_have_a_real_weakness_elsewhere(tmp_path: Path) -> None:
    stale = [{"kind": "stale_read", "occurrence": 1, "span": 2}]
    weak = run_experiment(
        tmp_path / "e",
        executor="verify_then_report",
        world="w-r2",
        faults=stale,  # type: ignore[arg-type]
    )
    assert outcome_of(observe(weak, observation_id="obs_1", proposal_id="p")) == "violation"


def test_branches_differ_only_by_the_observation(tmp_path: Path, manifest: Manifest) -> None:
    suite = manifest.adaptation
    capability = target_capability(WORLD_TIERS[WorldTier.RESERVED])
    case = suite.cases[0]
    branches = {b.outcome: b for b in case.branches}

    def prompt(outcome: str) -> dict[str, Any]:
        evidence = run_experiment(
            tmp_path / "e",
            executor=branches[outcome].executor,  # type: ignore[index]
            world=case.world,
            faults=branches[outcome].faults,  # type: ignore[index]
        )
        seen = observe(evidence, observation_id="obs_1", proposal_id="prop_1")
        context = context_for(suite, objective="o", capability=capability, observation=seen)
        return json.loads(str(build_messages(context)[-1].content))

    a, b = prompt("recovered"), prompt("violation")
    assert a["observations"] != b["observations"]
    a.pop("observations")
    b.pop("observations")
    assert a == b


def test_the_blind_control_shows_no_observation(manifest: Manifest) -> None:
    capability = target_capability(WORLD_TIERS[WorldTier.RESERVED])
    context = context_for(
        manifest.adaptation, objective="o", capability=capability, observation=None
    )
    assert json.loads(str(build_messages(context)[-1].content))["observations"] == []


# --- leakage -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "known_failure",
        "stale_read#1x6",
        "verify_then_report",
        "blind_retry",
        "idempotent_retry",
        "sprint-06",
        "same_condition",
        "discovery_possible",
        "not_reached",
    ],
)
def test_nothing_about_the_benchmark_reaches_a_prompt(manifest: Manifest, secret: str) -> None:
    capability = target_capability(WORLD_TIERS[WorldTier.RESERVED])
    context = context_for(
        manifest.adaptation, objective="o", capability=capability, observation=None
    )
    text = "\n".join(str(m.content) for m in build_messages(context))
    assert secret not in text


# --- non-adaptive isolation ----------------------------------------------------------------------


def _one_shot(tmp_path: Path, replies: list[Any], steps: list[Any], **extra: Any) -> Harness:
    return Harness(tmp_path, replies=replies, steps=steps, strategy=Strategy.ONE_SHOT, **extra)


def test_planning_never_sees_a_result_even_after_execution_began(tmp_path: Path) -> None:
    h = _one_shot(
        tmp_path,
        [propose(1, CODE), propose(2, CODE), propose(3, CODE)],
        [*experiment("normal-success"), "garbage", *experiment("normal-success")],
        max_experiments=2,
        max_model_calls=4,
    )
    h.workflow._repair_unrun_programs = True  # pyright: ignore[reportPrivateUsage]
    report = h.run()
    assert report.usage.model_calls == 3
    replacement = h.prompt(2)
    assert replacement["observations"] == []
    assert replacement["previous_proposal_rejected"]["problem"] == "invalid_protocol_output"
    assert "oracle" not in json.dumps(replacement["previous_proposal_rejected"])
    assert "planning_note" in replacement
    assert sum(1 for e in report.experiments if e.target_run_ids) == 2


def test_a_replacement_is_refused_when_refinements_are_spent(tmp_path: Path) -> None:
    h = _one_shot(
        tmp_path,
        [propose(1, CODE)],
        ["garbage"],
        max_experiments=1,
        max_refinements=0,
    )
    h.workflow._repair_unrun_programs = True  # pyright: ignore[reportPrivateUsage]
    report = h.run()
    assert report.usage.model_calls == 1
    assert report.state is InvestigationState.INCONCLUSIVE


def test_a_program_that_reached_the_target_is_never_replaced(tmp_path: Path) -> None:
    h = _one_shot(
        tmp_path,
        [propose(1, CODE)],
        experiment("normal-success"),
        max_experiments=1,
    )
    h.workflow._repair_unrun_programs = True  # pyright: ignore[reportPrivateUsage]
    report = h.run()
    assert report.usage.model_calls == 1
    assert report.state is InvestigationState.COMPLETED


def test_a_schedule_belongs_to_the_fixed_strategy_only(tmp_path: Path) -> None:
    h = _one_shot(tmp_path, [], [])
    with pytest.raises(ValueError, match="only the fixed strategy"):
        InvestigationWorkflow(
            request=h.request,
            runner=h.workflow._runner,  # pyright: ignore[reportPrivateUsage]
            root=tmp_path,
            model=h.workflow._model,  # pyright: ignore[reportPrivateUsage]
            fixed_schedule=[("x", "y")],
        )


def test_a_fixed_schedule_runs_exactly_what_was_registered(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[],
        steps=[*experiment("w-e3", []), *experiment("w-e3", [])],
        strategy=Strategy.FIXED,
        worlds=("w-e3",),
        tier=WorldTier.EVALUATION,
    )
    h.workflow._fixed_schedule = [("one", CODE), ("two", CODE)]  # pyright: ignore[reportPrivateUsage]
    report = h.run()
    assert [p.label for p in report.proposals] == ["one", "two"]
    assert report.usage.model_calls == 0
