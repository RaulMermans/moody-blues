"""Deterministic checks on what the model wrote. These make findings more reliable; they do not
make the Investigator's reasoning any better, and nothing here reads what it wrote as prose.

Hypotheses here are suspicions of failure (the system prompt says a target that recovered refutes
one), which is what lets a status be checked against structured records:

- ``supported`` needs an Oracle VIOLATION in a run that could test the hypothesis.
- ``refuted`` is contradicted by such a violation.
- A run whose relevant fault never fired tested nothing, so it can do neither.

A rejected assessment stays in the record, with the model's words, and its effective status says
what the evidence allows. Sprint 17's real errors are the regression cases: see
``tests/investigator/test_validity.py``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

from moody_blues.contracts.experiment_evidence import ExperimentEvidence, TargetRunEvidence
from moody_blues.contracts.investigation import (
    ConcludeInvestigation,
    FindingClass,
    HypothesisAssessment,
    HypothesisRecord,
    InvestigationObservation,
    ProposalRecord,
    VerifiedFinding,
)
from moody_blues.contracts.oracle import Verdict
from moody_blues.contracts.validity import (
    AssessmentCheck,
    AssessmentOutcome,
    EvidenceStrength,
    ExperimentValidity,
    RepeatedHypothesis,
    RunValidity,
    ValidityClass,
)
from moody_blues.experiments.validity import assess_delivery

_PUNCTUATION = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def run_validity(run: TargetRunEvidence) -> RunValidity:
    """As recorded, or read from the run's own trace if the record predates the field."""
    return run.validity or assess_delivery(
        run.authorized.faults, run.target_observed.tool_trace, run.authorized.fault_source
    )


def normalize(text: str) -> str:
    """Case, accents, punctuation and spacing. Bounded and exact: no similarity threshold."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _SPACE.sub(" ", _PUNCTUATION.sub(" ", folded)).strip()


def repeated_hypotheses(records: Iterable[HypothesisRecord]) -> list[RepeatedHypothesis]:
    """Same behavior and same mechanism, and not declared a refinement. A label, never a refusal."""
    seen: dict[tuple[str, str], str] = {}
    out: list[RepeatedHypothesis] = []
    for record in records:
        h = record.hypothesis
        key = (normalize(h.behavior), normalize(h.suspected_mechanism))
        first = seen.setdefault(key, h.hypothesis_id)
        if first != h.hypothesis_id and h.revises is None:
            out.append(RepeatedHypothesis(hypothesis_id=h.hypothesis_id, repeats=first))
    return out


def _is_fault_specific(
    hypothesis_id: str,
    proposals: Sequence[ProposalRecord],
    experiment_by_proposal: Mapping[str, str],
    evidence: Mapping[str, ExperimentEvidence],
) -> bool:
    """Whether any experiment run for this hypothesis set out to deliver a fault."""
    for proposal in proposals:
        if proposal.hypothesis_id != hypothesis_id:
            continue
        experiment = evidence.get(experiment_by_proposal.get(proposal.proposal_id, ""))
        if experiment is not None and any(r.authorized.faults for r in experiment.target_runs):
            return True
    return False


def _can_test(run: TargetRunEvidence, *, fault_specific: bool) -> bool:
    classification = run_validity(run).classification
    if fault_specific:
        return classification in {ValidityClass.EXERCISED, ValidityClass.PARTIALLY_EXERCISED}
    return classification is not ValidityClass.NOT_EXERCISED


def _strength(
    violating: list[TargetRunEvidence], clean: Sequence[TargetRunEvidence]
) -> EvidenceStrength:
    """A paired contrast needs the same world and config with no fault and no violation."""
    for run in violating:
        for other in clean:
            same = (run.authorized.scenario_id, run.authorized.config) == (
                other.authorized.scenario_id,
                other.authorized.config,
            )
            if (
                same
                and run_validity(run).classification is not ValidityClass.CONTROL
                and run_validity(other).classification is ValidityClass.CONTROL
                and other.oracle.verdict is not Verdict.VIOLATION
            ):
                return EvidenceStrength.PAIRED_CONTRAST_OBSERVED
    return EvidenceStrength.CORRELATION_ONLY


def check_assessment(
    assessment: HypothesisAssessment,
    *,
    observations: Mapping[str, InvestigationObservation],
    evidence: Mapping[str, ExperimentEvidence],
    proposals: Sequence[ProposalRecord],
    experiment_by_proposal: Mapping[str, str],
) -> AssessmentCheck:
    claimed = assessment.status
    cited = list(assessment.cited_observations)

    def result(
        status: str,
        outcome: AssessmentOutcome,
        eligible: list[str] | None = None,
        strength: EvidenceStrength = EvidenceStrength.NONE,
    ) -> AssessmentCheck:
        return AssessmentCheck.model_validate(
            {
                "hypothesis_id": assessment.hypothesis_id,
                "claimed_status": claimed,
                "effective_status": status,
                "outcome": outcome,
                "strength": strength,
                "cited_observations": cited,
                "eligible_observations": eligible or [],
            }
        )

    if any(o not in observations for o in cited):
        return result("inconclusive", AssessmentOutcome.UNKNOWN_EVIDENCE)
    pairs = [
        (oid, run)
        for oid in cited
        if (experiment := evidence.get(observations[oid].experiment_id)) is not None
        for run in experiment.target_runs
    ]
    if not pairs:
        if claimed == "inconclusive":
            return result(claimed, AssessmentOutcome.ACCEPTED)
        return result("inconclusive", AssessmentOutcome.NO_TARGET_RUN)
    fault_specific = _is_fault_specific(
        assessment.hypothesis_id, proposals, experiment_by_proposal, evidence
    )
    usable = [(oid, r) for oid, r in pairs if _can_test(r, fault_specific=fault_specific)]
    eligible = sorted({oid for oid, _ in usable})
    if not usable:
        # Whatever was claimed, inconclusive included: this is the honest name for what happened.
        return result("not_exercised", AssessmentOutcome.NOT_EXERCISED)
    violating = [r for _, r in usable if r.oracle.verdict is Verdict.VIOLATION]
    if claimed == "supported" and not violating:
        return result("inconclusive", AssessmentOutcome.CONTRADICTS_ORACLE, eligible)
    if claimed == "refuted" and violating:
        return result("inconclusive", AssessmentOutcome.CONTRADICTS_ORACLE, eligible)
    strength = (
        _strength(violating, [r for _, r in pairs])
        if claimed == "supported"
        else EvidenceStrength.NONE
    )
    return result(claimed, AssessmentOutcome.ACCEPTED, eligible, strength)


def check_batch(
    assessments: Sequence[HypothesisAssessment],
    *,
    earlier: Sequence[AssessmentCheck],
    observations: Mapping[str, InvestigationObservation],
    evidence: Mapping[str, ExperimentEvidence],
    proposals: Sequence[ProposalRecord],
    experiment_by_proposal: Mapping[str, str],
) -> list[AssessmentCheck]:
    """Each assessment, then conflicts: one hypothesis read two ways on the same evidence."""
    checks = [
        check_assessment(
            a,
            observations=observations,
            evidence=evidence,
            proposals=proposals,
            experiment_by_proposal=experiment_by_proposal,
        )
        for a in assessments
    ]
    out: list[AssessmentCheck] = []
    for check in checks:
        rivals = [
            c
            for c in (*earlier, *checks)
            if c is not check
            and c.hypothesis_id == check.hypothesis_id
            and c.claimed_status != check.claimed_status
            and set(c.cited_observations) == set(check.cited_observations)
        ]
        if rivals:
            check = check.model_copy(
                update={
                    "effective_status": "inconclusive",
                    "outcome": AssessmentOutcome.CONFLICTING,
                    "strength": EvidenceStrength.NONE,
                }
            )
        out.append(check)
    return out


def experiment_validity(evidence: Iterable[ExperimentEvidence]) -> list[ExperimentValidity]:
    return [
        ExperimentValidity(
            experiment_id=e.experiment_id,
            run_ref=r.run_ref,
            classification=run_validity(r).classification,
        )
        for e in evidence
        for r in e.target_runs
    ]


def conclusion_matches(
    conclusion: ConcludeInvestigation | None, findings: Sequence[VerifiedFinding]
) -> bool | None:
    """Whether the model's conclusion says what the verified findings say."""
    if conclusion is None:
        return None
    confirmed = any(f.finding_class is FindingClass.ORACLE_CONFIRMED_VIOLATION for f in findings)
    match conclusion.conclusion:
        case "violation_found":
            return confirmed
        case "no_violation_found":
            return not confirmed
        case "inconclusive":
            return True
