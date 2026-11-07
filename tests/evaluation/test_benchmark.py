"""The Sprint 19 benchmark's method, offline.

``ProbeSandbox`` is a TEST DOUBLE: it reads the plan out of the trusted probe and answers as that
program would, without running anything. The scripted model is a labeled fixture. Worlds, gateway,
coordinator, workflow and Oracle are real, so results here show the method and no model's behavior.
"""

from __future__ import annotations

import ast
import base64
import json
import re
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.investigation import ProposalStatus
from moody_blues.contracts.sandbox import SandboxRequest, SandboxResult
from moody_blues.contracts.validity import ValidityClass
from moody_blues.evaluation.benchmark import analysis, spec
from moody_blues.evaluation.benchmark.analysis import (
    ADVANTAGE,
    BASELINE_ADVANTAGE,
    INCONCLUSIVE,
    NO_ADVANTAGE,
    Comparison,
    Gates,
    UnitTruth,
)
from moody_blues.evaluation.benchmark.run import build_workflow, journal_path, run_stage
from moody_blues.evaluation.benchmark.spec import Stage, StrategyName
from moody_blues.evaluation.journal import Journal, JournalError
from moody_blues.experiments.workspace import EVIDENCE
from moody_blues.external.local import LocalSession
from moody_blues.investigator.fixtures import (
    FIXTURE_MODEL,
    ScriptedInvestigatorModel,
    tool_result,
)
from moody_blues.investigator.model import CONCLUDE_TOOL, SELECT_TOOL, InvestigatorModel
from moody_blues.investigator.quality import Defect, audit
from tests.conftest import make_settings
from tests.experiment.conftest import sandbox_result

PLAN_LINE = re.compile(r"^PLAN = (.+)$", re.MULTILINE)
PAYLOAD = re.compile(r'b64decode\("([^"]+)"\)')


class ProbeSandbox:
    """TEST DOUBLE. Answers each step as the trusted probe would, and runs nothing."""

    approved_for_generated_code = True

    def ping(self) -> None:
        return None

    def run(self, request: SandboxRequest, *, cancel: Event | None = None) -> SandboxResult:
        plan_text = PLAN_LINE.search(request.code)
        payload = PAYLOAD.search(request.code)
        assert plan_text is not None
        assert payload is not None
        plan: dict[str, Any] = ast.literal_eval(plan_text.group(1))
        seen = json.loads(base64.b64decode(payload.group(1)))["observations"]
        action: dict[str, Any] = {"protocol": "mb-exp/1"}
        if not seen:
            action |= {
                "action": "run_target_agent",
                "scenario_id": plan["scenario_id"],
                "config": plan["config"],
                "faults": plan["faults"],
            }
        elif len(seen) < 3:
            section = "tool_trace" if len(seen) == 1 else "state_summary"
            action |= {
                "action": "inspect_observation",
                "run_ref": seen[0]["run_ref"],
                "section": section,
            }
        else:
            action |= {
                "action": "finish_experiment",
                "conclusion": "inconclusive",
                "summary": "probe",
            }
        return sandbox_result(json.dumps(action) + "\n")


def frozen_spec(**changes: Any) -> spec.Spec:
    built = spec.build_spec(revision=1, reason=None, model=FIXTURE_MODEL, digest="fixture")
    return built.model_copy(update=changes)


def select(candidate: str, number: int, known: list[str], **extra: Any) -> Any:
    fields = {
        "hypothesis_id": f"h{number}",
        "behavior": f"behavior {number}",
        "suspected_mechanism": f"mechanism {number}",
        "motivating_observations": known,
        "predicted_observation": "a failure",
        "failure_discriminator": "the Oracle",
        "rationale": "worth testing",
        "motivated_by": known,
        "candidate_id": candidate,
    }
    return tool_result(SELECT_TOOL, fields | extra)


def conclude(**extra: Any) -> Any:
    return tool_result(
        CONCLUDE_TOOL,
        {"conclusion": "no_violation_found", "reasoning": "done"} | extra,
    )


def six_selections() -> list[Any]:
    known = [f"obs_{i}" for i in range(1, 7)]
    picks = [select(f"c{i + 1:02d}", i + 1, known[:i]) for i in range(6)]
    return [*picks, conclude()]


def investigator(replies: list[Any]) -> tuple[InvestigatorModel, ScriptedInvestigatorModel]:
    inference = ScriptedInvestigatorModel(replies)
    model = InvestigatorModel(
        inference=inference,
        evidence="offline_fixture",
        model=FIXTURE_MODEL,
        provider=None,
        spend=None,
        max_completion_tokens=2048,
        temperature=0,
    )
    return model, inference


def plan_of(built: spec.Spec, stage: Stage, unit: str, strategy: StrategyName) -> spec.PlannedTrial:
    return next(
        t
        for t in spec.expand_plan(built)
        if (t.stage, t.unit_id, t.strategy) == (stage, unit, strategy)
    )


def run_trial(
    built: spec.Spec, trial: spec.PlannedTrial, root: Path, model: InvestigatorModel | None = None
) -> Any:
    return build_workflow(
        built,
        trial,
        root=root,
        sandbox=ProbeSandbox(),  # type: ignore[arg-type]
        settings=make_settings(),
        investigator=model,
    ).run()


# --- preregistration ---------------------------------------------------------------------------


def test_the_frozen_plan_is_valid_and_complete() -> None:
    built = frozen_spec()
    assert spec.validate(built) == []
    plan = spec.expand_plan(built)
    main = [t for t in plan if t.stage is Stage.MAIN]
    assert len(main) == len(built.units) * (1 + 2 * len(built.main_seeds))
    assert plan == spec.expand_plan(built)


def test_every_strategy_draws_on_the_same_candidates_and_budget() -> None:
    built = frozen_spec()
    for trial in spec.expand_plan(built):
        if trial.stage is Stage.SWEEP or trial.strategy is StrategyName.ADAPTIVE:
            continue
        unit = next(u for u in built.units if u.unit_id == trial.unit_id)
        pool = {c.key for c in spec.world_candidates(built, unit.world_type)}
        assert set(trial.candidates) <= pool
        assert len(set(trial.candidates)) == built.budget
    unit = built.units[0]
    menu = spec.menu_for(built, unit, 1901)
    assert set(menu.labels.values()) == {
        c.key for c in spec.world_candidates(built, unit.world_type)
    }


def test_seeds_reproduce_and_differ() -> None:
    pool = spec.world_candidates(frozen_spec(), spec.QUEUE)
    first = spec.shuffled(pool, unit_id="u", seed=1)
    assert first == spec.shuffled(pool, unit_id="u", seed=1)
    assert first != spec.shuffled(pool, unit_id="u", seed=2)
    assert first != spec.shuffled(pool, unit_id="v", seed=1)


def test_the_fixed_order_is_a_rule_about_families_not_targets() -> None:
    built = frozen_spec()
    pool = spec.world_candidates(built, spec.CRM)
    assert spec.fixed_order(pool)[:4] == ["crm-01", "crm-02", "crm-03", "crm-04"]
    plan = spec.expand_plan(built)
    fixed = {
        tuple(t.candidates)
        for t in plan
        if t.stage is Stage.MAIN
        and t.strategy is StrategyName.FIXED
        and t.unit_id.startswith("crm/")
    }
    assert len(fixed) == 1


def test_a_candidate_never_relies_on_a_world_default() -> None:
    assert all(isinstance(c.faults, list) for c in frozen_spec().candidates)
    assert all('"faults": None' not in spec.program_for(c) for c in frozen_spec().candidates)


def test_a_frozen_revision_cannot_be_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spec, "SPEC_DIR", tmp_path)
    built = frozen_spec()
    sha = spec.freeze(built)
    with pytest.raises(spec.SpecError, match="frozen already"):
        spec.freeze(built)
    assert spec.spec_sha(spec.load(1)) == sha
    assert spec.drift(built) == []


def test_a_revision_needs_a_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spec, "SPEC_DIR", tmp_path)
    with pytest.raises(spec.SpecError, match="stated reason"):
        spec.freeze(frozen_spec(revision=2))


def test_a_changed_plan_or_prompt_is_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spec, "SPEC_DIR", tmp_path)
    built = frozen_spec()
    spec.freeze(built)
    plan = json.loads(spec.plan_path(1).read_text())
    plan[0]["candidates"] = list(reversed(plan[0]["candidates"]))
    spec.plan_path(1).write_text(json.dumps(plan))
    assert "the plan does not follow from the spec" in spec.drift(built)
    changed = built.fingerprints.model_copy(update={"menu_protocol_sha256": "0" * 64})
    assert "changed since freezing: menu_protocol_sha256" in spec.drift(
        built.model_copy(update={"fingerprints": changed})
    )


def test_a_pilot_seed_cannot_be_a_main_seed() -> None:
    assert spec.validate(frozen_spec(pilot_seeds=[1901])) == ["a pilot seed is also a main seed"]


# --- what a strategy can see -------------------------------------------------------------------


def test_nothing_hidden_reaches_the_model(tmp_path: Path) -> None:
    built = frozen_spec()
    trial = plan_of(built, Stage.MAIN, "queue/job_blind_retry", StrategyName.ADAPTIVE)
    model, inference = investigator(six_selections())
    run_trial(built, trial, tmp_path, model)
    text = "\n".join(r.model_dump_json() for r in inference.requests)
    for scenario in spec.world_scenarios(built.candidates, spec.QUEUE):
        assert scenario not in text
    for hidden in ("job_blind_retry", "reference:", "queue-", "job-queue-0", "expected_verdict"):
        assert hidden not in text
    assert "python_code" not in text
    assert "EXPERIMENT_INPUT" not in text


def test_results_reach_the_model_only_after_they_exist(tmp_path: Path) -> None:
    built = frozen_spec()
    trial = plan_of(built, Stage.MAIN, "crm/blind_retry", StrategyName.ADAPTIVE)
    model, inference = investigator(six_selections())
    run_trial(built, trial, tmp_path, model)
    first = json.loads(str(inference.requests[0].messages[-1].content))
    assert first["observations"] == []
    assert not any(item["already_run"] for item in first["experiment_menu"])
    second = json.loads(str(inference.requests[1].messages[-1].content))
    assert len(second["observations"]) == 1
    assert sum(item["already_run"] for item in second["experiment_menu"]) == 1
    assert second["observations"][0]["runs"][0]["world_ref"].startswith("w")


def test_records_keep_the_real_world_ids(tmp_path: Path) -> None:
    built = frozen_spec()
    trial = plan_of(built, Stage.MAIN, "crm/blind_retry", StrategyName.ADAPTIVE)
    model, _ = investigator(six_selections())
    report = run_trial(built, trial, tmp_path, model)
    worlds = {r.world_ref for o in report.observations for r in o.runs}
    assert worlds <= set(spec.world_scenarios(built.candidates, spec.CRM))


# --- budgets -----------------------------------------------------------------------------------


def test_every_strategy_spends_the_same_budget(tmp_path: Path) -> None:
    built = frozen_spec()
    model, inference = investigator(six_selections())
    unit = "crm/verify_then_report"
    for strategy, chosen in (
        (StrategyName.FIXED, None),
        (StrategyName.RANDOM, None),
        (StrategyName.ADAPTIVE, model),
    ):
        report = run_trial(built, plan_of(built, Stage.MAIN, unit, strategy), tmp_path, chosen)
        assert len(report.experiments) == built.budget
    offered = [[t.name for t in r.tools] for r in inference.requests]
    assert offered == [[SELECT_TOOL]] * 6 + [[CONCLUDE_TOOL]]


def test_a_bad_choice_gets_one_revision_then_costs_the_slot(tmp_path: Path) -> None:
    built = frozen_spec()
    trial = plan_of(built, Stage.MAIN, "crm/trusting", StrategyName.ADAPTIVE)
    known = [f"obs_{i}" for i in range(1, 6)]
    replies = [
        select("nope", 1, []),
        select("alsonope", 1, []),
        *[select(f"c{i + 1:02d}", i + 1, known[:i]) for i in range(5)],
        conclude(),
    ]
    model, inference = investigator(replies)
    report = run_trial(built, trial, tmp_path, model)
    assert len(report.experiments) == 5
    rejected = [p for p in report.proposals if p.status is ProposalStatus.REJECTED_BEFORE_EXECUTION]
    assert [p.rejection.problem for p in rejected] == ["unknown_candidate"] * 2
    second = json.loads(str(inference.requests[1].messages[-1].content))
    assert second["previous_proposal_rejected"]["problem"] == "unknown_candidate"
    assert "experiment_menu" in second


def test_the_model_call_limit_holds(tmp_path: Path) -> None:
    built = frozen_spec()
    built = built.model_copy(
        update={"limits": built.limits.model_copy(update={"max_model_calls": 2})}
    )
    trial = plan_of(built, Stage.MAIN, "crm/trusting", StrategyName.ADAPTIVE)
    model, inference = investigator(six_selections())
    report = run_trial(built, trial, tmp_path, model)
    assert len(inference.requests) == 2
    assert report.termination == "max_model_calls"


def test_a_menu_is_for_the_adaptive_strategy_only(tmp_path: Path) -> None:
    built = frozen_spec()
    fixed = plan_of(built, Stage.MAIN, "crm/trusting", StrategyName.FIXED)
    assert fixed.candidates
    assert fixed.seed is None
    adaptive = plan_of(built, Stage.MAIN, "crm/trusting", StrategyName.ADAPTIVE)
    with pytest.raises(ValueError, match="needs a model"):
        run_trial(built, adaptive, tmp_path, None)


# --- running and resuming ----------------------------------------------------------------------


class _Session:
    """TEST DOUBLE for ``LocalSession``."""

    def __init__(self, model: InvestigatorModel) -> None:
        self._model = model

    def investigator(self, limits: Any) -> InvestigatorModel:
        return self._model


def small_spec() -> spec.Spec:
    return frozen_spec(pilot_units=["crm/blind_retry"], pilot_seeds=[1801])


def pilot(root: Path, built: spec.Spec, settings: Settings, limit: int | None = None) -> int:
    model, _ = investigator(six_selections())
    session: Any = _Session(model)
    assert not isinstance(session, LocalSession)
    return run_stage(
        built,
        Stage.PILOT,
        root=root,
        settings=settings,
        session=session,
        sandbox=ProbeSandbox(),  # type: ignore[arg-type]
        limit=limit,
    )


def test_a_stage_runs_from_the_plan_and_resumes(tmp_path: Path) -> None:
    built = small_spec()
    settings = make_settings()
    assert pilot(tmp_path, built, settings, limit=1) == 1
    assert pilot(tmp_path, built, settings) == 2
    assert pilot(tmp_path, built, settings) == 0
    rows, missing = analysis.trial_rows(built, tmp_path, [Stage.PILOT])
    assert missing == []
    assert len(rows) == 3
    assert all(r.evidence_complete for r in rows)
    assert {r.strategy for r in rows} == set(StrategyName)


def test_a_trial_left_open_is_abandoned_not_replayed(tmp_path: Path) -> None:
    built = small_spec()
    settings = make_settings()
    pilot(tmp_path, built, settings, limit=1)
    journal = Journal(journal_path(tmp_path, built))
    open_trial = spec.expand_plan(built)[1].trial_id
    journal.append("started", {"id": open_trial})
    assert pilot(tmp_path, built, settings) == 1
    journal = Journal(journal_path(tmp_path, built))
    assert [p["id"] for p in journal.payloads("abandoned")] == [open_trial]
    rows, missing = analysis.trial_rows(built, tmp_path, [Stage.PILOT])
    assert missing == [open_trial]
    assert len(rows) == 2


def test_a_journal_cannot_be_reused_for_another_specification(tmp_path: Path) -> None:
    built = small_spec()
    settings = make_settings()
    pilot(tmp_path, built, settings, limit=1)
    with pytest.raises(RuntimeError, match="another specification"):
        pilot(tmp_path, built.model_copy(update={"main_seeds": [1, 2, 3]}), settings)


def test_an_edited_journal_stops_the_report(tmp_path: Path) -> None:
    built = small_spec()
    pilot(tmp_path, built, make_settings())
    path = journal_path(tmp_path, built)
    path.write_text(path.read_text().replace("completed", "c0mpleted"))
    with pytest.raises(JournalError):
        analysis.trial_rows(built, tmp_path, [Stage.PILOT])


# --- metrics from evidence ---------------------------------------------------------------------


def _experiment_files(root: Path) -> list[Path]:
    return sorted(root.glob("experiments/*/" + EVIDENCE))


def test_a_tampered_result_is_not_counted(tmp_path: Path) -> None:
    built = small_spec()
    pilot(tmp_path, built, make_settings())
    target = _experiment_files(tmp_path)[0]
    target.write_text(target.read_text().replace('"evidence_source"', '"evidence_source" '))
    rows, _ = analysis.trial_rows(built, tmp_path, [Stage.PILOT])
    damaged = [
        e for r in rows for e in r.experiments if e.excluded_because == "evidence_not_intact"
    ]
    assert len(damaged) == 1
    assert not damaged[0].eligible
    assert not all(r.evidence_complete for r in rows)


def test_a_fault_that_never_fired_is_excluded_from_the_rate(tmp_path: Path) -> None:
    """``trusting`` calls create once, so a fault on the second call cannot reach it."""
    built = frozen_spec()
    trial = plan_of(built, Stage.MAIN, "crm/trusting", StrategyName.FIXED).model_copy(
        update={"candidates": ["crm-07", "crm-01"]}
    )
    report = run_trial(built, trial, tmp_path)
    conditions = {analysis.candidate_condition(c): c.key for c in built.candidates}
    payload = {
        "investigation_id": report.investigation_id,
        "report_sha256": __import__("hashlib")
        .sha256(
            (tmp_path / "investigations" / report.investigation_id / "report.json").read_bytes()
        )
        .hexdigest(),
        "wall_ms": 1,
    }
    row = analysis._trial_row(built, trial, payload, tmp_path, conditions)  # pyright: ignore[reportPrivateUsage]
    assert [e.candidate for e in row.experiments] == ["crm-07", "crm-01"]
    assert row.experiments[0].validity == ValidityClass.NOT_EXERCISED.value
    assert row.experiments[0].excluded_because == "undelivered_fault"
    assert row.experiments[1].eligible
    assert row.eligible == 1
    assert row.executed == 2
    assert row.undelivered == 1


def test_distinctness_is_the_oracle_code_and_nothing_written(tmp_path: Path) -> None:
    built = frozen_spec()
    trial = plan_of(built, Stage.MAIN, "crm/blind_retry", StrategyName.FIXED).model_copy(
        update={"candidates": ["crm-02", "crm-05"]}
    )
    report = run_trial(built, trial, tmp_path)
    found = [
        analysis.signatures("crm", r)
        for ref in report.experiments
        for r in analysis.load_evidence(tmp_path, ref.experiment_id).target_runs
    ]
    assert "crm:duplicate_side_effect" in found[0]
    assert found[0] == found[1]  # one bug under two conditions counts once


def row(unit: str, strategy: StrategyName, distinct: int, eligible: int = 6) -> analysis.TrialRow:
    return analysis.TrialRow(
        trial_id=f"{unit}-{strategy.value}-{distinct}",
        stage=Stage.MAIN,
        unit_id=unit,
        world="crm",
        strategy=strategy,
        seed=None,
        state="completed",
        termination="plan_finished",
        attempted=6,
        rejected=0,
        executed=6,
        eligible=eligible,
        undelivered=0,
        distinct_eligible=[f"crm:s{i}" for i in range(distinct)],
        distinct_any=[f"crm:s{i}" for i in range(distinct)],
        verified_violation_runs=distinct,
        first_violation_position=1 if distinct else None,
        first_violation_ms=1 if distinct else None,
        model_calls=0,
        prompt_tokens=0,
        completion_tokens=0,
        model_latency_ms=0,
        tool_calls=0,
        wall_ms=1,
        sandbox_ms=1,
        ollama_rss_kb=None,
        evidence_complete=True,
        problems=[],
        quality=None,
        experiments=[],
    )


def test_seeds_are_averaged_inside_a_unit_before_comparing() -> None:
    rows = [
        row("a", StrategyName.ADAPTIVE, 3),
        row("a", StrategyName.ADAPTIVE, 1),
        row("a", StrategyName.FIXED, 1),
        row("b", StrategyName.ADAPTIVE, 0),
        row("b", StrategyName.FIXED, 1),
    ]
    result = analysis.compare(rows, StrategyName.FIXED)
    assert (result.units, result.wins, result.losses, result.ties) == (2, 1, 1, 0)
    assert result.mean_adaptive == pytest.approx(10 * 2 / 6 / 2, abs=1e-3)


def test_no_eligible_experiment_means_no_rate_not_zero() -> None:
    assert row("a", StrategyName.FIXED, 0, eligible=0).primary is None
    assert row("a", StrategyName.FIXED, 0).primary == 0


def comparison(
    baseline: str, difference: float, wins: int, losses: int, attempted: float | None = None
) -> Comparison:
    return Comparison(
        baseline=baseline,
        units=14,
        mean_adaptive=5.0,
        mean_baseline=5.0 - difference,
        mean_difference=difference,
        attempted_difference=difference if attempted is None else attempted,
        wins=wins,
        losses=losses,
        ties=14 - wins - losses,
        win_share_interval=analysis.clopper_pearson(wins, wins + losses),
    )


GOOD = Gates(plan_complete=True, adaptive_eligible_share=0.9, incorrect_finding_rate=0.1)


@pytest.mark.parametrize(
    ("first", "second", "gates", "expected"),
    [
        (("fixed", 2.0, 11, 1), ("random", 2.0, 11, 1), GOOD, ADVANTAGE),
        (("fixed", 2.0, 11, 1), ("random", 0.4, 11, 1), GOOD, NO_ADVANTAGE),
        (("fixed", 2.0, 7, 5), ("random", 2.0, 11, 1), GOOD, NO_ADVANTAGE),
        (("fixed", -2.0, 1, 11), ("random", 0.0, 6, 6), GOOD, BASELINE_ADVANTAGE),
        # A shrunken denominator alone cannot carry a claim, in either direction.
        (("fixed", 2.0, 11, 1, 0.5), ("random", 2.0, 11, 1), GOOD, NO_ADVANTAGE),
        (("fixed", -2.0, 1, 11, -0.5), ("random", 0.0, 6, 6), GOOD, NO_ADVANTAGE),
        (("fixed", 2.0, 5, 1), ("random", 2.0, 11, 1), GOOD, INCONCLUSIVE),
        (
            ("fixed", 2.0, 11, 1),
            ("random", 2.0, 11, 1),
            GOOD.model_copy(update={"plan_complete": False}),
            INCONCLUSIVE,
        ),
        (
            ("fixed", 2.0, 11, 1),
            ("random", 2.0, 11, 1),
            GOOD.model_copy(update={"adaptive_eligible_share": 0.5}),
            INCONCLUSIVE,
        ),
        (
            ("fixed", 2.0, 11, 1),
            ("random", 2.0, 11, 1),
            GOOD.model_copy(update={"incorrect_finding_rate": 0.6}),
            NO_ADVANTAGE,
        ),
    ],
)
def test_the_registered_rule(
    first: tuple[Any, ...],
    second: tuple[Any, ...],
    gates: Gates,
    expected: str,
) -> None:
    conclusion, reasons = analysis.decide(
        [comparison(*first), comparison(*second)], gates, frozen_spec()
    )
    assert conclusion == expected
    assert reasons


def test_time_to_first_violation_includes_the_model(tmp_path: Path) -> None:
    built = small_spec()
    pilot(tmp_path, built, make_settings())
    rows, _ = analysis.trial_rows(built, tmp_path, [Stage.PILOT])
    adaptive = next(r for r in rows if r.strategy is StrategyName.ADAPTIVE)
    assert adaptive.model_calls == 7
    # The fixture reports 1 ms a call, so a first violation at position n carries n of them.
    if adaptive.first_violation_position is not None:
        assert adaptive.first_violation_ms is not None
        assert adaptive.first_violation_ms >= adaptive.first_violation_position


def test_the_exact_expectation_for_a_random_schedule() -> None:
    truth = UnitTruth(
        {"a": frozenset({"x"}), "b": frozenset(), "c": frozenset(), "d": frozenset({"y"})}
    )
    assert truth.reachable == {"x", "y"}
    assert truth.expected_random(2) == pytest.approx(1.0)
    assert truth.expected_random(4) == 2


def test_candidates_stay_in_their_world() -> None:
    built = frozen_spec()
    for world in (spec.CRM, spec.QUEUE):
        names = spec.world_scenarios(built.candidates, world)
        assert all(
            analysis.candidate_condition(c)[0] in names for c in spec.world_candidates(built, world)
        )
    assert not set(spec.world_scenarios(built.candidates, spec.CRM)) & set(
        spec.world_scenarios(built.candidates, spec.QUEUE)
    )


# --- reasoning quality -------------------------------------------------------------------------


def _assess(status: str, hypothesis: str, observation: str) -> dict[str, Any]:
    return {
        "previous_hypothesis_id": hypothesis,
        "previous_status": status,
        "previous_cited_observations": [observation],
        "previous_reasoning": "my reading",
    }


def test_a_contradiction_a_false_claim_and_a_repeat_are_all_named(tmp_path: Path) -> None:
    """Both no-fault candidates, on a target that does not fail: every claim here is wrong."""
    built = frozen_spec()
    built = built.model_copy(
        update={"limits": built.limits.model_copy(update={"max_experiments": 2})}
    )
    trial = plan_of(built, Stage.MAIN, "crm/verify_then_report", StrategyName.ADAPTIVE)
    repeat = {"behavior": "behavior 1", "suspected_mechanism": "mechanism 1"}
    assert trial.seed is not None
    menu = spec.menu_for(built, built.units[2], trial.seed)
    by_key = {key: candidate for candidate, key in menu.labels.items()}
    model, _ = investigator(
        [
            select(by_key["crm-01"], 1, []),
            select(by_key["crm-06"], 2, ["obs_1"], **repeat, **_assess("supported", "h1", "obs_1")),
            conclude(
                conclusion="violation_found",
                claimed_findings=["exp_unknown:duplicate_side_effect"],
            ),
        ]
    )
    report = run_trial(built, trial, tmp_path, model)
    result = audit(report)
    assert result.defects[Defect.REPEATED_HYPOTHESIS.value] == 1
    assert result.defects[Defect.MISSING_EVIDENCE_REFERENCE.value] == 1
    assert result.defects[Defect.UNSUPPORTED_CONCLUSION.value] == 1
    assert result.defects[Defect.CONTRADICTS_ORACLE.value] == 1
    assert result.incorrect_statements == 3
    assert report.findings  # what the Oracle said stands, whatever the model wrote
    assert all(f.oracle_verdict.value != "VIOLATION" for f in report.findings)
