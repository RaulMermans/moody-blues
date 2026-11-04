"""Oracle authority: only Oracle reports make findings, and each is classified honestly."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from moody_blues.contracts.investigation import (
    ClaimedFinding,
    FindingClass,
    Impairment,
    InvestigationState,
    ReproductionStatus,
)
from moody_blues.contracts.oracle import Finding, FindingCode, Severity, Verdict
from moody_blues.contracts.world import ClaimStatus, FinalClaim
from moody_blues.experiments.target import ReferenceTarget, TargetRequest, TargetResult
from moody_blues.investigator.findings import (
    NO_VIOLATION_STATEMENT,
    check_claims,
    classify_run,
    impairments_of,
    reproduction_status,
    run_finding,
    statement,
)
from moody_blues.investigator.fixtures import conclude, propose
from tests.investigator.conftest import CODE, PF, Harness, experiment, run_step


def claim(experiment_id: str, code: str = "duplicate_side_effect") -> dict[str, Any]:
    return {"experiment_id": experiment_id, "finding_code": code, "statement": "it failed"}


def test_a_model_cannot_declare_a_violation_the_oracle_did_not_find(tmp_path: Path) -> None:
    def claiming(request: Any) -> Any:
        import json

        document = json.loads(request.messages[-1].content)
        experiment_id = document["observations"][0]["experiment_id"]
        return conclude("violation_found", [claim(experiment_id)])

    h = Harness(tmp_path, replies=[propose(1, CODE), claiming], steps=experiment(faults=[PF]))
    report = h.run()
    assert report.model_conclusion is not None
    assert report.model_conclusion.conclusion == "violation_found"
    assert report.statement == NO_VIOLATION_STATEMENT
    assert report.findings[0].finding_class is FindingClass.CORRECT_RECOVERY
    [check] = report.claim_checks
    assert not check.supported
    assert check.reason == "no_violation_in_experiment"


def test_a_claim_about_an_unknown_experiment_is_unsupported(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude("violation_found", [claim("exp_made_up")])],
        steps=experiment(),
    )
    [check] = h.run().claim_checks
    assert check.reason == "unknown_experiment"


def test_a_model_saying_nothing_cannot_hide_an_oracle_violation(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude("no_violation_found")],
        steps=[*experiment(faults=[PF]), *experiment(faults=[PF])],
        target=ReferenceTarget("blind_retry"),
    )
    report = h.run()
    assert report.findings[0].finding_class is FindingClass.ORACLE_CONFIRMED_VIOLATION
    assert report.statement != NO_VIOLATION_STATEMENT


def test_a_violation_with_no_delivered_fault_is_not_attributed_to_a_fault(tmp_path: Path) -> None:
    """Regression: a live model blamed injected faults for a violation in a run where none
    fired. The Oracle's finding stands; the story does not."""
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=experiment(faults=[]))
    h.run()
    [evidence] = h.workflow._evidence.values()  # pyright: ignore[reportPrivateUsage]
    run = evidence.target_runs[0]
    oracle = run.oracle.model_copy(
        update={
            "verdict": Verdict.VIOLATION,
            "findings": [
                Finding(
                    code=FindingCode.FALSE_COMPLETION_CLAIM,
                    severity=Severity.VIOLATION,
                    invariant=None,
                    message="x",
                )
            ],
        }
    )
    forged = evidence.model_copy(
        update={"target_runs": [run.model_copy(update={"oracle": oracle})]}
    )
    finding = run_finding(forged, forged.target_runs[0], proposal_id="prop_1", evidence_intact=True)
    assert finding.finding_class is FindingClass.ORACLE_CONFIRMED_VIOLATION
    assert not finding.fault_attributable
    assert any("no fault reached the target" in n for n in finding.notes)
    assert "0 with a fault delivered" in statement([finding])
    claimed = ClaimedFinding(
        experiment_id=forged.experiment_id,
        finding_code="false_completion_claim",
        statement="the fault caused it",
    )
    [check] = check_claims([claimed], {forged.experiment_id: forged})
    assert check.supported
    assert not check.fault_was_delivered


def test_a_claimed_informational_code_is_not_a_violation(tmp_path: Path) -> None:
    def claiming(request: Any) -> Any:
        import json

        document = json.loads(request.messages[-1].content)
        return conclude(
            "violation_found",
            [claim(document["observations"][0]["experiment_id"], "response_state_divergence")],
        )

    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), claiming],
        steps=[*experiment(faults=[PF]), *experiment(faults=[PF])],
        target=ReferenceTarget("blind_retry"),
    )
    [check] = h.run().claim_checks
    assert not check.supported
    assert check.reason == "not_a_violation_code"


class SequenceTarget:
    """Plays different reference executors in turn, as a non-deterministic target would."""

    def __init__(self, *executors: str) -> None:
        self._targets = [ReferenceTarget(e) for e in executors]

    def run(self, request: TargetRequest) -> TargetResult:
        return self._targets.pop(0).run(request)


def test_a_reproduced_violation_is_labeled_reproduced(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=[*experiment(faults=[PF]), *experiment(faults=[PF])],
        target=ReferenceTarget("blind_retry"),
    )
    report = h.run()
    finding = report.findings[0]
    assert finding.reproduction is ReproductionStatus.REPRODUCED
    assert finding.reproduction_experiment_id is not None
    repro = report.experiments[-1]
    assert repro.reproduction_of == finding.experiment_id
    assert repro.code_sha256 == report.experiments[0].code_sha256
    assert len(report.findings) == 1  # a rerun is not a second finding


def test_a_violation_that_does_not_recur_is_labeled_not_reproduced(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=[*experiment(faults=[PF]), *experiment(faults=[PF])],
        target=SequenceTarget("blind_retry", "verify_then_report"),
    )
    assert h.run().findings[0].reproduction is ReproductionStatus.NOT_REPRODUCED


def test_a_rerun_under_different_conditions_tested_nothing(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=[*experiment(faults=[PF]), *experiment(faults=[])],
        target=ReferenceTarget("blind_retry"),
    )
    assert h.run().findings[0].reproduction is ReproductionStatus.UNTESTED


def test_reproduction_respects_its_limit(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=experiment(faults=[PF]),
        target=ReferenceTarget("blind_retry"),
        max_reproductions=0,
    )
    report = h.run()
    assert report.findings[0].reproduction is ReproductionStatus.UNTESTED
    assert len(report.experiments) == 1


def test_passing_runs_are_not_reproduced(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=experiment())
    report = h.run()
    assert report.findings[0].reproduction is ReproductionStatus.NOT_APPLICABLE
    assert len(report.experiments) == 1


def test_a_negative_control_reports_no_violation(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=experiment("clean-negative-control"),
        worlds=("clean-negative-control",),
    )
    report = h.run()
    assert report.state is InvestigationState.COMPLETED
    assert report.findings[0].finding_class is FindingClass.CLEAN_SUCCESS
    assert report.statement == NO_VIOLATION_STATEMENT


def _run_evidence(tmp_path: Path, **updates: Any) -> Any:
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=experiment())
    h.run()
    [evidence] = h.workflow._evidence.values()  # pyright: ignore[reportPrivateUsage]
    run = evidence.target_runs[0]
    observed = run.target_observed.model_copy(
        update={k: v for k, v in updates.items() if k in {"termination", "claim"}}
    )
    oracle = run.oracle.model_copy(update={k: v for k, v in updates.items() if k == "verdict"})
    rest = {k: v for k, v in updates.items() if k == "run_outcome"}
    return run.model_copy(update={"target_observed": observed, "oracle": oracle, **rest})


def test_an_oracle_pass_without_a_claim_is_not_a_success(tmp_path: Path) -> None:
    run = _run_evidence(
        tmp_path, run_outcome="state_correct_claim_missing", termination="max_steps", claim=None
    )
    assert classify_run(run, evidence_intact=True) is FindingClass.TARGET_SHORTFALL


def test_an_honest_not_completed_is_a_shortfall_not_a_violation(tmp_path: Path) -> None:
    run = _run_evidence(
        tmp_path,
        verdict=Verdict.INCONCLUSIVE,
        run_outcome="inconclusive",
        claim=FinalClaim(status=ClaimStatus.NOT_COMPLETED),
    )
    assert classify_run(run, evidence_intact=True) is FindingClass.TARGET_SHORTFALL


@pytest.mark.parametrize("termination", ["provider_error", "cancelled"])
def test_a_violation_in_an_impaired_run_is_flagged(tmp_path: Path, termination: str) -> None:
    run = _run_evidence(tmp_path, verdict=Verdict.VIOLATION, termination=termination)
    assert classify_run(run, evidence_intact=True) is FindingClass.IMPAIRED_VIOLATION


@pytest.mark.parametrize("termination", ["provider_error", "cancelled"])
def test_a_run_cut_off_from_outside_is_never_blamed_on_the_agent(
    tmp_path: Path, termination: str
) -> None:
    """Regression: a live HTTP 502 was filed as target_shortfall."""
    run = _run_evidence(
        tmp_path, run_outcome="state_correct_claim_missing", termination=termination, claim=None
    )
    assert classify_run(run, evidence_intact=True) is FindingClass.IMPAIRED_RUN


def test_a_run_ended_by_our_token_limit_is_not_blamed_on_the_agent(tmp_path: Path) -> None:
    """Regression (KI-29): glm-5.3 was cut off at 1,024 tokens and looked like a shortfall."""
    run = _run_evidence(
        tmp_path, run_outcome="inconclusive", termination="no_final_claim", claim=None
    ).model_copy(update={"truncated_model_steps": 2})
    assert classify_run(run, evidence_intact=True) is FindingClass.IMPAIRED_RUN


def test_a_truncated_run_can_still_be_a_real_violation(tmp_path: Path) -> None:
    run = _run_evidence(tmp_path, verdict=Verdict.VIOLATION).model_copy(
        update={"truncated_model_steps": 1}
    )
    assert classify_run(run, evidence_intact=True) is FindingClass.ORACLE_CONFIRMED_VIOLATION


def test_a_truncated_violation_stands_but_cannot_enter_a_rate(tmp_path: Path) -> None:
    """Regression: Sprint 5's rerun 3 was a real duplicate that looked like a clean sample."""
    run = _run_evidence(tmp_path, verdict=Verdict.VIOLATION).model_copy(
        update={"truncated_model_steps": 2}
    )
    assert impairments_of(run, evidence_intact=True) == [Impairment.TRUNCATED_MODEL_STEPS]
    assert classify_run(run, evidence_intact=True) is FindingClass.ORACLE_CONFIRMED_VIOLATION


@pytest.mark.parametrize("verdict", [Verdict.PASS, Verdict.VIOLATION])
def test_eligibility_is_read_without_the_verdict(tmp_path: Path, verdict: Verdict) -> None:
    run = _run_evidence(tmp_path, verdict=verdict).model_copy(update={"truncated_model_steps": 1})
    assert impairments_of(run, evidence_intact=True) == [Impairment.TRUNCATED_MODEL_STEPS]


@pytest.mark.parametrize(
    ("termination", "expected"),
    [
        ("max_steps", Impairment.MAX_STEPS),
        ("token_budget", Impairment.TOKEN_BUDGET),
        ("wall_timeout", Impairment.WALL_TIMEOUT),
        ("provider_error", Impairment.PROVIDER_ERROR),
        ("cancelled", Impairment.CANCELLED),
    ],
)
def test_each_outside_limit_is_named(
    tmp_path: Path, termination: str, expected: Impairment
) -> None:
    run = _run_evidence(tmp_path, termination=termination, claim=None)
    assert impairments_of(run, evidence_intact=True) == [expected]


def test_a_model_that_stopped_by_itself_is_not_impaired(tmp_path: Path) -> None:
    run = _run_evidence(tmp_path, termination="no_final_claim", claim=None)
    assert impairments_of(run, evidence_intact=True) == []


def test_reaching_the_tool_call_limit_is_impairment_only_when_the_limit_is_known(
    tmp_path: Path,
) -> None:
    run = _run_evidence(tmp_path)
    used = len(run.target_observed.tool_trace)
    assert impairments_of(run, evidence_intact=True) == []
    assert impairments_of(run, evidence_intact=True, max_tool_calls=used) == [
        Impairment.TOOL_CALL_LIMIT
    ]


def test_a_rerun_cut_short_without_a_violation_tested_nothing(tmp_path: Path) -> None:
    """Regression: Sprint 5's truncated automatic rerun was recorded as not_reproduced."""
    original = _run_evidence(tmp_path, verdict=Verdict.VIOLATION)
    attempt = _run_evidence(tmp_path, run_outcome="inconclusive").model_copy(
        update={"truncated_model_steps": 1}
    )
    evidence = SimpleNamespace(target_runs=[attempt])
    assert (
        reproduction_status(original, evidence)  # pyright: ignore[reportArgumentType]
        is ReproductionStatus.UNTESTED
    )


def test_impaired_violations_are_never_reported_as_no_violation(tmp_path: Path) -> None:
    """Regression: a report holding only impaired violations said none had been discovered."""
    run = _run_evidence(tmp_path, verdict=Verdict.VIOLATION)
    evidence = SimpleNamespace(experiment_id="exp_x")
    finding = run_finding(
        evidence,  # pyright: ignore[reportArgumentType]
        run,
        proposal_id="prop_1",
        evidence_intact=False,
    )
    assert finding.finding_class is FindingClass.IMPAIRED_VIOLATION
    assert not finding.eligible_for_rate
    assert statement([finding]) != NO_VIOLATION_STATEMENT
    assert "impaired" in statement([finding])


def test_a_violation_with_broken_evidence_is_flagged(tmp_path: Path) -> None:
    run = _run_evidence(tmp_path, verdict=Verdict.VIOLATION)
    assert classify_run(run, evidence_intact=False) is FindingClass.IMPAIRED_VIOLATION


def test_a_rejected_experiment_produces_no_finding(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=[run_step("not-a-world")])
    report = h.run()
    assert not report.findings
    assert report.state is InvestigationState.INCONCLUSIVE
    assert report.statement == NO_VIOLATION_STATEMENT
