"""Findings, from trusted records only. The Oracle's verdict is the only source of a violation.

Each target run gets one class. A VIOLATION is ``oracle_confirmed_violation`` only if the run
finished normally and its evidence verifies; otherwise it is flagged for review, because a
report must not lean on a run that was cut short or a record that does not check out. A PASS is
not automatically a success: ``run_outcome`` decides that. Rejections and infrastructure failures
have no target run, so they can never appear here.
"""

from __future__ import annotations

from moody_blues.contracts.agent import TerminationReason
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, TargetRunEvidence
from moody_blues.contracts.investigation import (
    ClaimCheck,
    ClaimedFinding,
    FindingClass,
    ReproductionStatus,
    SelectedFault,
    VerifiedFinding,
)
from moody_blues.contracts.oracle import Verdict
from moody_blues.investigator.observations import SHORTFALLS, violation_codes

NO_VIOLATION_STATEMENT = "No verified violation discovered within the tested scenarios and budget."

_IMPAIRED = {TerminationReason.PROVIDER_ERROR.value, TerminationReason.CANCELLED.value}


def classify_run(run: TargetRunEvidence, *, evidence_intact: bool) -> FindingClass:
    termination = run.target_observed.termination
    if run.oracle.verdict is Verdict.VIOLATION:
        if termination in _IMPAIRED or not evidence_intact:
            return FindingClass.IMPAIRED_VIOLATION
        return FindingClass.ORACLE_CONFIRMED_VIOLATION
    if termination in _IMPAIRED:
        return FindingClass.IMPAIRED_RUN
    succeeded = (
        run.oracle.verdict is Verdict.PASS
        and run.run_outcome in {None, "success"}
        and termination not in SHORTFALLS
    )
    if not succeeded:
        return FindingClass.TARGET_SHORTFALL
    if run.target_observed.faults_delivered > 0:
        return FindingClass.CORRECT_RECOVERY
    return FindingClass.CLEAN_SUCCESS


def _notes(run: TargetRunEvidence, finding_class: FindingClass) -> list[str]:
    notes: list[str] = []
    termination = run.target_observed.termination
    if run.evidence_source != "live_provider":
        notes.append(f"{run.evidence_source}: says nothing about model behavior")
    if termination in {TerminationReason.MAX_STEPS.value, TerminationReason.TOKEN_BUDGET.value}:
        notes.append(f"the run hit a budget we set ({termination}); not by itself a model failing")
    if finding_class is FindingClass.IMPAIRED_VIOLATION:
        notes.append("run or evidence impaired; review before relying on this")
    if finding_class is FindingClass.IMPAIRED_RUN:
        notes.append(f"cut off by {termination}; says nothing about the agent")
    return notes


def run_finding(
    evidence: ExperimentEvidence,
    run: TargetRunEvidence,
    *,
    proposal_id: str,
    evidence_intact: bool,
) -> VerifiedFinding:
    finding_class = classify_run(run, evidence_intact=evidence_intact)
    violating = finding_class in {
        FindingClass.ORACLE_CONFIRMED_VIOLATION,
        FindingClass.IMPAIRED_VIOLATION,
    }
    grant = run.authorized
    return VerifiedFinding(
        experiment_id=evidence.experiment_id,
        proposal_id=proposal_id,
        run_id=run.run_id,
        run_ref=run.run_ref,
        world_ref=grant.scenario_id,
        config=grant.config,
        selected_faults=[
            SelectedFault(kind=f.kind.value, occurrence=f.occurrence, span=f.span)
            for f in grant.faults
        ],
        finding_class=finding_class,
        oracle_verdict=run.oracle.verdict,
        run_outcome=run.run_outcome,
        termination=run.target_observed.termination,
        violation_codes=violation_codes(run),
        faults_delivered=run.target_observed.faults_delivered,
        target_evidence_source=run.evidence_source,
        reproduction=ReproductionStatus.UNTESTED
        if violating
        else ReproductionStatus.NOT_APPLICABLE,
        notes=_notes(run, finding_class),
    )


def reproduction_status(
    original: TargetRunEvidence, attempt: ExperimentEvidence
) -> ReproductionStatus:
    """Reproduced means: same conditions, and the Oracle again reports a shared violation.

    A rerun that never reached a target run, or that ran different conditions, tested nothing.
    """
    if not attempt.target_runs:
        return ReproductionStatus.UNTESTED
    run = attempt.target_runs[0]
    same = (
        run.authorized.scenario_id == original.authorized.scenario_id
        and run.authorized.config == original.authorized.config
        and run.authorized.faults == original.authorized.faults
    )
    if not same:
        return ReproductionStatus.UNTESTED
    if run.oracle.verdict is Verdict.VIOLATION and set(violation_codes(run)) & set(
        violation_codes(original)
    ):
        return ReproductionStatus.REPRODUCED
    return ReproductionStatus.NOT_REPRODUCED


def check_claims(
    claims: list[ClaimedFinding], evidence: dict[str, ExperimentEvidence]
) -> list[ClaimCheck]:
    checks: list[ClaimCheck] = []
    for claim in claims:
        experiment = evidence.get(claim.experiment_id)
        if experiment is None:
            checks.append(ClaimCheck(claim=claim, supported=False, reason="unknown_experiment"))
            continue
        violating = [r for r in experiment.target_runs if r.oracle.verdict is Verdict.VIOLATION]
        if not violating:
            checks.append(
                ClaimCheck(claim=claim, supported=False, reason="no_violation_in_experiment")
            )
        elif any(claim.finding_code in violation_codes(r) for r in violating):
            checks.append(ClaimCheck(claim=claim, supported=True, reason="oracle_confirms"))
        else:
            checks.append(
                ClaimCheck(claim=claim, supported=False, reason="finding_code_not_reported")
            )
    return checks


def statement(findings: list[VerifiedFinding]) -> str:
    confirmed = [f for f in findings if f.finding_class is FindingClass.ORACLE_CONFIRMED_VIOLATION]
    if not confirmed:
        return NO_VIOLATION_STATEMENT
    live = [f for f in confirmed if f.is_model_behavior]
    reproduced = [f for f in confirmed if f.reproduction is ReproductionStatus.REPRODUCED]
    basis = "live model target" if live else "non-model target (fixture or reference executor)"
    return (
        f"{len(confirmed)} Oracle-confirmed violation(s) on a {basis}; "
        f"{len(reproduced)} reproduced in a fresh world."
    )
