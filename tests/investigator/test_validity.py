"""Deterministic checks on model-written conclusions, against the real Sprint 17 errors.

Hypothesis text comes from the committed Sprint 17 evaluation, where a real model wrote it. Runs
come from a real coordinator, real worlds and the real Oracle, with reference scripts as targets.
These checks make findings more reliable. They say nothing about the model getting any better.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from moody_blues.contracts.experiment_evidence import (
    ExperimentAuthorship,
    ExperimentEvidence,
    ExperimentSpec,
)
from moody_blues.contracts.investigation import (
    ClaimedFinding,
    ConcludeInvestigation,
    FindingClass,
    Hypothesis,
    HypothesisAssessment,
    HypothesisRecord,
    InvestigationObservation,
    ProposalRecord,
    ProposalStatus,
)
from moody_blues.contracts.validity import (
    AssessmentCheck,
    AssessmentOutcome,
    EvidenceStrength,
    ValidityClass,
)
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.experiments.target import ReferenceTarget
from moody_blues.experiments.validity import assess_delivery
from moody_blues.investigator.findings import check_claims, run_finding
from moody_blues.investigator.observations import observe
from moody_blues.investigator.validity import (
    check_batch,
    conclusion_matches,
    normalize,
    repeated_hypotheses,
    run_validity,
)
from moody_blues.world.registry import world_plugin
from tests.experiment.conftest import SANDBOX_LIMITS, ScriptedSandbox, finish_action, run_action

SPRINT_17 = Path(__file__).parents[2] / "docs/evaluations/sprint-17/results/local-eval.json"
SPEC = ExperimentSpec(label="validity", code="# the test double supplies stdout\n")
PF = {"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}
UNREACHABLE = {"kind": "phantom_failure", "occurrence": 3, "error_code": "timeout"}


class World:
    """Real experiments, and the bookkeeping the workflow would hold about them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.evidence: dict[str, ExperimentEvidence] = {}
        self.observations: dict[str, InvestigationObservation] = {}
        self.proposals: list[ProposalRecord] = []
        self.links: dict[str, str] = {}

    def run(
        self,
        hypothesis: str,
        executor: str,
        scenario: str,
        faults: list[dict[str, Any]] | None,
        world: str = "crm",
    ) -> str:
        number = len(self.observations) + 1
        extra = {} if faults is None else {"faults": faults}
        evidence = ExperimentCoordinator(
            sandbox=ScriptedSandbox([run_action(scenario, **extra), finish_action()]),
            target=ReferenceTarget(executor),
            root=self.root,
            sandbox_limits=SANDBOX_LIMITS,
            world=world_plugin(world),
        ).run(SPEC)
        proposal_id, observation_id = f"prop_{number}", f"obs_{number}"
        self.evidence[evidence.experiment_id] = evidence
        self.observations[observation_id] = observe(
            evidence, observation_id=observation_id, proposal_id=proposal_id
        )
        self.proposals.append(
            ProposalRecord(
                proposal_id=proposal_id,
                model_call_seq=number,
                authorship=ExperimentAuthorship.MODEL_GENERATED,
                hypothesis_id=hypothesis,
                label="x",
                rationale="x",
                motivated_by=[],
                source_sha256=None,
                source_bytes=None,
                source_path=None,
                status=ProposalStatus.EXECUTED,
            )
        )
        self.links[proposal_id] = evidence.experiment_id
        return observation_id

    def check(
        self, *assessments: HypothesisAssessment, earlier: list[AssessmentCheck] | None = None
    ) -> list[AssessmentCheck]:
        return check_batch(
            assessments,
            earlier=earlier or [],
            observations=self.observations,
            evidence=self.evidence,
            proposals=self.proposals,
            experiment_by_proposal=self.links,
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def assessment(hypothesis: str, status: str, *cited: str) -> HypothesisAssessment:
    return HypothesisAssessment(
        hypothesis_id=hypothesis,
        status=status,  # type: ignore[arg-type]
        cited_observations=list(cited),
        reasoning="what the model wrote is kept and is not parsed",
    )


# --- fault delivery ---------------------------------------------------------------------------


def _validity(world: World, observation: str) -> Any:
    evidence = world.evidence[world.observations[observation].experiment_id]
    return evidence.target_runs[0].validity


def test_a_delivered_fault_is_exercised(world: World) -> None:
    v = _validity(world, world.run("h1", "verify_then_report", "normal-success", [PF]))
    assert v.classification is ValidityClass.EXERCISED
    assert v.eligible_fault_kinds == ["phantom_failure"]
    assert v.faults[0].trigger_reached
    assert v.faults[0].delivered == 1
    assert v.relevant_call_seqs == v.faults[0].delivered_at_calls


def test_a_fault_whose_trigger_never_came_is_not_exercised(world: World) -> None:
    v = _validity(world, world.run("h1", "verify_then_report", "normal-success", [UNREACHABLE]))
    assert v.classification is ValidityClass.NOT_EXERCISED
    assert v.not_exercised_fault_kinds == ["phantom_failure"]
    assert not v.faults[0].trigger_reached
    assert v.faults[0].delivered == 0


def test_a_fault_reached_but_skipped_is_not_exercised(world: World) -> None:
    stale = [{"kind": "stale_read", "occurrence": 1, "span": 1}]
    v = _validity(world, world.run("h1", "trusting", "normal-success", stale))
    assert v.classification is ValidityClass.NOT_EXERCISED  # no read ever happened
    assert not v.faults[0].trigger_reached
    skipped = _validity(
        world, world.run("h2", "job_verify_then_report", "jq-normal", stale, world="job-queue")
    )
    assert skipped.classification is ValidityClass.NOT_EXERCISED
    assert skipped.faults[0].trigger_reached
    assert skipped.faults[0].skipped_effects == ["not_applied_nothing_to_hide"]


def test_a_partly_delivered_window_is_partial(world: World) -> None:
    window = [{"kind": "stale_read", "occurrence": 1, "span": 6}]
    v = _validity(
        world,
        world.run("h1", "job_single_read", "jq-stale-read", window, world="job-queue"),
    )
    assert v.classification is ValidityClass.PARTIALLY_EXERCISED


def test_no_intended_fault_is_a_control(world: World) -> None:
    v = _validity(world, world.run("h1", "verify_then_report", "normal-success", []))
    assert v.classification is ValidityClass.CONTROL


def test_validity_never_touches_the_verdict(world: World) -> None:
    oid = world.run("h1", "blind_retry", "preexisting-email", [UNREACHABLE])
    evidence = world.evidence[world.observations[oid].experiment_id]
    run = evidence.target_runs[0]
    assert run.validity is not None
    assert run.validity.classification is ValidityClass.NOT_EXERCISED
    assert run_finding(evidence, run, proposal_id="p", evidence_intact=True).oracle_verdict is (
        run.oracle.verdict
    )


def test_a_record_without_the_field_gets_the_same_answer_from_its_trace(world: World) -> None:
    oid = world.run("h1", "verify_then_report", "normal-success", [PF])
    run = world.evidence[world.observations[oid].experiment_id].target_runs[0]
    legacy = run.model_copy(update={"validity": None, "world": None})
    assert run_validity(legacy) == run.validity
    assert legacy.world_type == "crm"
    assert legacy.plugin_version == "legacy"


def test_a_world_default_fault_is_kept_from_the_investigators_view(world: World) -> None:
    built_in = world.run("h1", "verify_then_report", "phantom-failure", None)
    chosen = world.run("h2", "verify_then_report", "normal-success", [PF])
    assert world.observations[built_in].runs[0].delivered.fault_validity is None
    assert world.observations[chosen].runs[0].delivered.fault_validity == "exercised"


def test_delivery_is_read_from_older_traces_with_no_effect_field() -> None:
    assert assess_delivery([], [], "scenario").classification is ValidityClass.CONTROL


# --- the real Sprint 17 errors ----------------------------------------------------------------


def _sprint_17() -> list[dict[str, Any]]:
    return json.loads(SPRINT_17.read_text(encoding="utf-8"))["investigations"]


def test_regression_supported_while_the_oracle_found_nothing(world: World) -> None:
    """inv_da2f2c222a1a: h1 marked supported, while its reasoning said no violation occurred."""
    h1 = _sprint_17()[0]["hypotheses"][0]
    assert h1["status"] == "supported"
    assert "no violation" in h1["assessment"]["reasoning"]
    obs = world.run("h1", "verify_then_report", "normal-success", [PF])
    [check] = world.check(
        HypothesisAssessment.model_validate(h1["assessment"] | {"cited_observations": [obs]})
    )
    assert check.outcome is AssessmentOutcome.CONTRADICTS_ORACLE
    assert check.claimed_status == "supported"
    assert check.effective_status == "inconclusive"


def test_regression_a_fault_that_never_fired_supports_nothing(world: World) -> None:
    """inv_7d1316c3da95: the agent's call was refused, so the fault was never delivered."""
    model = _sprint_17()[1]["model_conclusion"]["assessments"][0]
    assert model["status"] == "supported"
    obs = world.run("h2", "verify_then_report", "normal-success", [UNREACHABLE])
    [check] = world.check(
        HypothesisAssessment.model_validate(model | {"cited_observations": [obs]})
    )
    assert check.outcome is AssessmentOutcome.NOT_EXERCISED
    assert check.effective_status == "not_exercised"
    assert check.eligible_observations == []


@pytest.mark.parametrize("status", ["supported", "refuted", "inconclusive"])
def test_an_undelivered_fault_is_neither_evidence_for_nor_against(
    world: World, status: str
) -> None:
    obs = world.run("h1", "verify_then_report", "normal-success", [UNREACHABLE])
    [check] = world.check(assessment("h1", status, obs))
    assert check.effective_status == "not_exercised"


def test_regression_a_repeated_hypothesis_is_labeled(world: World) -> None:
    """Both Sprint 17 investigations: h2 is h1 almost word for word."""
    records = [HypothesisRecord.model_validate(h) for h in _sprint_17()[0]["hypotheses"]]
    [repeat] = repeated_hypotheses(records)
    assert (repeat.hypothesis_id, repeat.repeats) == ("h2", "h1")


def _hypothesis(hid: str, behavior: str, mechanism: str, revises: str | None = None) -> Any:
    return HypothesisRecord(
        hypothesis=Hypothesis(
            hypothesis_id=hid,
            behavior=behavior,
            suspected_mechanism=mechanism,
            motivating_observations=[],
            motivation="m",
            predicted_observation="p",
            failure_discriminator="f",
            revises=revises,
        )
    )


def test_case_spacing_and_punctuation_do_not_hide_a_repeat() -> None:
    a = _hypothesis("h1", "The agent retries.", "A timeout   causes it")
    b = _hypothesis("h2", "the AGENT retries", "a timeout causes it!")
    assert [r.hypothesis_id for r in repeated_hypotheses([a, b])] == ["h2"]


def test_a_declared_refinement_is_never_labeled() -> None:
    a = _hypothesis("h1", "The agent retries", "A timeout causes it")
    b = _hypothesis("h2", "The agent retries", "A timeout causes it", revises="h1")
    assert repeated_hypotheses([a, b]) == []


def test_a_different_mechanism_is_a_different_hypothesis() -> None:
    a = _hypothesis("h1", "The agent retries", "A timeout causes it")
    b = _hypothesis("h2", "The agent retries", "A false success causes it")
    assert repeated_hypotheses([a, b]) == []


def test_normalization_is_bounded_and_exact() -> None:
    assert normalize("  Foo,   BAR!! ") == "foo bar"
    assert normalize("one") != normalize("two")


# --- claim and evidence consistency -----------------------------------------------------------


def test_a_supported_assessment_with_a_real_violation_is_accepted_as_correlation(
    world: World,
) -> None:
    obs = world.run("h1", "blind_retry", "normal-success", [PF])
    [check] = world.check(assessment("h1", "supported", obs))
    assert check.outcome is AssessmentOutcome.ACCEPTED
    assert check.effective_status == "supported"
    assert check.strength is EvidenceStrength.CORRELATION_ONLY


def test_a_paired_control_is_named_and_is_still_not_called_a_cause(world: World) -> None:
    violated = world.run("h1", "blind_retry", "normal-success", [PF])
    control = world.run("h1", "blind_retry", "normal-success", [])
    [check] = world.check(assessment("h1", "supported", violated, control))
    assert check.strength is EvidenceStrength.PAIRED_CONTRAST_OBSERVED


def test_refuted_while_the_oracle_found_a_violation_is_rejected(world: World) -> None:
    obs = world.run("h1", "blind_retry", "normal-success", [PF])
    [check] = world.check(assessment("h1", "refuted", obs))
    assert check.outcome is AssessmentOutcome.CONTRADICTS_ORACLE


def test_a_correct_refutation_stands(world: World) -> None:
    obs = world.run("h1", "verify_then_report", "normal-success", [PF])
    [check] = world.check(assessment("h1", "refuted", obs))
    assert check.outcome is AssessmentOutcome.ACCEPTED
    assert check.effective_status == "refuted"


def test_a_reference_to_nothing_is_refused(world: World) -> None:
    [check] = world.check(assessment("h1", "supported", "obs_404"))
    assert check.outcome is AssessmentOutcome.UNKNOWN_EVIDENCE
    assert check.effective_status == "inconclusive"


def test_two_readings_of_the_same_evidence_conflict(world: World) -> None:
    obs = world.run("h1", "blind_retry", "normal-success", [PF])
    checks = world.check(assessment("h1", "supported", obs), assessment("h1", "refuted", obs))
    assert {c.outcome for c in checks} == {AssessmentOutcome.CONFLICTING}
    assert {c.effective_status for c in checks} == {"inconclusive"}


def test_changing_a_reading_with_nothing_new_conflicts_with_the_earlier_one(world: World) -> None:
    obs = world.run("h1", "blind_retry", "normal-success", [PF])
    earlier = world.check(assessment("h1", "supported", obs))
    [check] = world.check(assessment("h1", "refuted", obs), earlier=earlier)
    assert check.outcome is AssessmentOutcome.CONFLICTING


def test_changing_a_reading_on_new_evidence_is_allowed(world: World) -> None:
    first = world.run("h1", "blind_retry", "normal-success", [PF])
    earlier = world.check(assessment("h1", "supported", first))
    second = world.run("h1", "verify_then_report", "normal-success", [PF])
    [check] = world.check(assessment("h1", "refuted", second), earlier=earlier)
    assert check.outcome is AssessmentOutcome.ACCEPTED


def test_the_checks_work_the_same_in_the_queue(world: World) -> None:
    obs = world.run("h1", "job_blind_retry", "jq-normal", [PF], world="job-queue")
    [check] = world.check(assessment("h1", "supported", obs))
    assert check.outcome is AssessmentOutcome.ACCEPTED
    missed = world.run("h2", "job_trusting", "jq-normal", [UNREACHABLE], world="job-queue")
    [check] = world.check(assessment("h2", "supported", missed))
    assert check.effective_status == "not_exercised"


def _finding(world: World, oid: str) -> Any:
    evidence = world.evidence[world.observations[oid].experiment_id]
    return run_finding(evidence, evidence.target_runs[0], proposal_id="p", evidence_intact=True)


def _conclude(conclusion: str) -> ConcludeInvestigation:
    return ConcludeInvestigation.model_validate(
        {"assessments": [], "conclusion": conclusion, "claimed_findings": [], "reasoning": "r"}
    )


def test_a_conclusion_must_say_what_the_findings_say(world: World) -> None:
    clean = _finding(world, world.run("h1", "verify_then_report", "normal-success", [PF]))
    bad = _finding(world, world.run("h2", "blind_retry", "normal-success", [PF]))
    assert bad.finding_class is FindingClass.ORACLE_CONFIRMED_VIOLATION
    assert conclusion_matches(_conclude("violation_found"), [clean]) is False
    assert conclusion_matches(_conclude("violation_found"), [bad]) is True
    assert conclusion_matches(_conclude("no_violation_found"), [bad]) is False
    assert conclusion_matches(_conclude("inconclusive"), [bad]) is True
    assert conclusion_matches(None, [bad]) is None


def test_a_violation_cannot_be_credited_to_a_fault_that_never_fired(world: World) -> None:
    """The Oracle's finding stands. Only the story blaming the fault does not."""
    oid = world.run("h1", "job_wrong_type", "jq-normal", [UNREACHABLE], world="job-queue")
    experiment = world.observations[oid].experiment_id
    run = world.evidence[experiment].target_runs[0]
    codes = [str(f.code) for f in run.oracle.findings]
    claim = ClaimedFinding(experiment_id=experiment, finding_code=codes[0], statement="the fault")
    [checked] = check_claims([claim], world.evidence)
    assert checked.fault_not_exercised
    assert not checked.fault_was_delivered
