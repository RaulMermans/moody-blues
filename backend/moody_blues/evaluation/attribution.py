"""From "a fault was delivered" to "the evidence supports that the fault mattered".

Delivery and temporal order are exposure, not cause. The highest level here needs a controlled
contrast: fresh worlds, one changed factor, a clean arm that stayed clean and a fault arm that
failed often enough to tell apart from it. Even then the claim is that the fault *raised the
chance* of the failure. Model runs are stochastic, so nothing here asserts deterministic causation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from moody_blues.evaluation.trials import TrialRecord


class AttributionLevel(StrEnum):
    FAULT_DELIVERED = "fault_delivered"  # exposure only
    VIOLATION_OBSERVED = "violation_observed"  # a violation, with or without a fault
    CAUSAL_EVIDENCE_SUPPORTS_FAULT = "causal_evidence_supports_fault"
    CAUSALITY_INCONCLUSIVE = "causality_inconclusive"


class ContrastRule(BaseModel):
    """Fixed in the manifest before any trial. Eligible runs only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required_eligible_per_arm: int
    min_failures_in_fault_arm: int


class Attribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: AttributionLevel
    fault_arm: str
    control_arm: str
    changed: str
    rule: ContrastRule
    fault_eligible: int
    fault_failures: int
    fault_arm_exposed: int
    control_eligible: int
    control_failures: int
    # Eligible control runs a fault reached. Zero in a control meant to hold a fault means that
    # arm tested nothing about it: a "met" rule there says nothing about that fault alone.
    control_arm_exposed: int
    # Failures in the fault arm where a stale read came before the duplicating write.
    fault_failures_with_mechanism: int
    reasons: list[str]


def trial_levels(trial: TrialRecord) -> list[AttributionLevel]:
    """What one run alone can show. Never the highest level: that takes a comparison."""
    levels: list[AttributionLevel] = []
    if trial.fault_delivered:
        levels.append(AttributionLevel.FAULT_DELIVERED)
    if trial.violated:
        levels.append(AttributionLevel.VIOLATION_OBSERVED)
    return levels


def assess_contrast(
    *,
    fault_arm: str,
    fault: list[TrialRecord],
    control_arm: str,
    control: list[TrialRecord],
    changed: str,
    rule: ContrastRule,
) -> Attribution:
    fault_eligible = [t for t in fault if t.eligible]
    control_eligible = [t for t in control if t.eligible]
    failures = [t for t in fault_eligible if t.duplicate]
    control_failures = [t for t in control_eligible if t.duplicate]
    with_mechanism = [
        t for t in failures if t.behavior is not None and t.behavior.fault_preceded_duplicate_write
    ]
    reasons: list[str] = []
    need = rule.required_eligible_per_arm
    if len(fault_eligible) < need or len(control_eligible) < need:
        reasons.append(
            f"needs {need} eligible runs per arm; has "
            f"{len(fault_eligible)} and {len(control_eligible)}"
        )
    if len(failures) < rule.min_failures_in_fault_arm:
        reasons.append(
            f"needs {rule.min_failures_in_fault_arm} failures in the fault arm; has {len(failures)}"
        )
    if control_failures:
        reasons.append(f"the control arm also failed {len(control_failures)} time(s)")
    if any(t.fault_delivered for t in control):
        reasons.append("a fault reached the control arm, so it is not a clean control")
    if len(with_mechanism) < len(failures):
        reasons.append("a failure did not follow delivery of the fault")
    return Attribution(
        level=AttributionLevel.CAUSALITY_INCONCLUSIVE
        if reasons
        else AttributionLevel.CAUSAL_EVIDENCE_SUPPORTS_FAULT,
        fault_arm=fault_arm,
        control_arm=control_arm,
        changed=changed,
        rule=rule,
        fault_eligible=len(fault_eligible),
        fault_failures=len(failures),
        fault_arm_exposed=sum(1 for t in fault_eligible if t.fault_delivered),
        control_eligible=len(control_eligible),
        control_failures=len(control_failures),
        control_arm_exposed=sum(1 for t in control_eligible if t.fault_delivered),
        fault_failures_with_mechanism=len(with_mechanism),
        reasons=reasons,
    )
