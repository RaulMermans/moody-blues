"""What was wrong with an Investigator's reasoning, as reason codes over structured records.

Three layers stay apart, and nothing here changes any of them:

- experiment validity: did the condition really happen (``contracts/validity.py``);
- Oracle verdict: was the world right, from the Oracle alone;
- Investigator finding: what the model concluded, recorded word for word and checked.

Prose is never parsed, so a causal claim is only visible where the model made a structured one: a
``supported`` status. Rejected proposals keep their own list and are never accepted conclusions.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from moody_blues.contracts.investigation import InvestigationReport, ProposalStatus
from moody_blues.contracts.validity import AssessmentOutcome, EvidenceStrength


class Defect(StrEnum):
    UNSUPPORTED_CONCLUSION = "unsupported_conclusion"
    CONTRADICTS_ORACLE = "contradicts_oracle"
    CONTRADICTORY_ASSESSMENTS = "contradictory_assessments"
    MISSING_EVIDENCE_REFERENCE = "missing_evidence_reference"
    UNDELIVERED_FAULT = "undelivered_fault_treated_as_evidence"
    REPEATED_HYPOTHESIS = "repeated_hypothesis"
    INVALID_PROPOSAL = "invalid_proposal"
    CORRELATION_ONLY = "supported_without_contrast"
    MISREPORTED_ORACLE = "misreported_oracle"


_ASSESSMENT_DEFECTS: dict[AssessmentOutcome, Defect] = {
    AssessmentOutcome.CONTRADICTS_ORACLE: Defect.CONTRADICTS_ORACLE,
    AssessmentOutcome.CONFLICTING: Defect.CONTRADICTORY_ASSESSMENTS,
    AssessmentOutcome.NOT_EXERCISED: Defect.UNDELIVERED_FAULT,
    AssessmentOutcome.NO_TARGET_RUN: Defect.MISSING_EVIDENCE_REFERENCE,
    AssessmentOutcome.UNKNOWN_EVIDENCE: Defect.MISSING_EVIDENCE_REFERENCE,
}

_CLAIM_DEFECTS: dict[str, Defect] = {
    "unknown_experiment": Defect.MISSING_EVIDENCE_REFERENCE,
    "no_violation_in_experiment": Defect.MISREPORTED_ORACLE,
    "not_a_violation_code": Defect.MISREPORTED_ORACLE,
    "finding_code_not_reported": Defect.MISREPORTED_ORACLE,
}

# A wrong statement of what happened. A repeat or a rejected proposal wastes budget but states
# nothing false, and a correlation is true as far as it goes.
INCORRECT: frozenset[Defect] = frozenset(
    {
        Defect.UNSUPPORTED_CONCLUSION,
        Defect.CONTRADICTS_ORACLE,
        Defect.CONTRADICTORY_ASSESSMENTS,
        Defect.MISSING_EVIDENCE_REFERENCE,
        Defect.UNDELIVERED_FAULT,
        Defect.MISREPORTED_ORACLE,
    }
)


class RejectedProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: str
    reason: str
    invalid_fields: list[str]


class QualityAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    defects: dict[str, int]
    statements: int  # assessments, claims and the conclusion: what could have been wrong
    incorrect_statements: int
    hypotheses: int
    repeated_hypotheses: int
    rejected_proposals: list[RejectedProposal]
    accepted_assessments: int


def audit(report: InvestigationReport) -> QualityAudit:
    counts: Counter[Defect] = Counter()
    checks = report.validity.assessments if report.validity is not None else []
    accepted = 0
    for check in checks:
        defect = _ASSESSMENT_DEFECTS.get(check.outcome)
        if defect is not None:
            counts[defect] += 1
            continue
        accepted += 1
        if check.effective_status == "supported" and (
            check.strength is not EvidenceStrength.PAIRED_CONTRAST_OBSERVED
        ):
            counts[Defect.CORRELATION_ONLY] += 1
    for claim in report.claim_checks:
        if not claim.supported:
            counts[_CLAIM_DEFECTS.get(claim.reason, Defect.MISREPORTED_ORACLE)] += 1
        elif claim.fault_not_exercised:
            counts[Defect.UNDELIVERED_FAULT] += 1
    concluded = report.validity is not None and (
        report.validity.conclusion_matches_findings is not None
    )
    if report.validity is not None and report.validity.conclusion_matches_findings is False:
        counts[Defect.UNSUPPORTED_CONCLUSION] += 1
    repeated = len(report.validity.repeated_hypotheses) if report.validity is not None else 0
    if repeated:
        counts[Defect.REPEATED_HYPOTHESIS] += repeated
    rejected = [
        RejectedProposal(
            proposal_id=p.proposal_id,
            reason=p.rejection.problem if p.rejection is not None else "unknown",
            invalid_fields=list(p.rejection.invalid_fields) if p.rejection is not None else [],
        )
        for p in report.proposals
        if p.status is ProposalStatus.REJECTED_BEFORE_EXECUTION
    ]
    if rejected:
        counts[Defect.INVALID_PROPOSAL] += len(rejected)
    return QualityAudit(
        defects={d.value: n for d, n in sorted(counts.items())},
        statements=len(checks) + len(report.claim_checks) + int(concluded),
        incorrect_statements=sum(n for d, n in counts.items() if d in INCORRECT),
        hypotheses=len(report.hypotheses),
        repeated_hypotheses=repeated,
        rejected_proposals=rejected,
        accepted_assessments=accepted,
    )
