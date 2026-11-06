"""Experiment validity: did the condition an experiment set up actually happen?

This is not an Oracle verdict and never changes one. The Oracle says what is true of a world. This
says whether a run can bear on a hypothesis about a fault: a fault that never fired tested nothing,
so its run is neither evidence for that hypothesis nor against it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ValidityClass(StrEnum):
    CONTROL = "control"  # no fault was intended
    EXERCISED = "exercised"  # every intended target was delivered
    PARTIALLY_EXERCISED = "partially_exercised"  # some were
    NOT_EXERCISED = "not_exercised"  # a fault was intended and none was delivered


class FaultDelivery(BaseModel):
    """One intended fault, against what the gateway recorded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    operation: str
    occurrence: int
    span: int
    source: Literal["scenario", "experiment_selection"]
    trigger_reached: bool  # an eligible operation reached this occurrence
    delivered: int = Field(ge=0)  # how many of its targets changed what the agent saw
    skipped_effects: list[str] = Field(default_factory=list[str])
    delivered_at_calls: list[int] = Field(default_factory=list[int])


class RunValidity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    classification: ValidityClass
    faults: list[FaultDelivery]
    # Calls whose delivered response a fault changed or skipped: the observations that matter.
    relevant_call_seqs: list[int]
    eligible_fault_kinds: list[str]  # hypotheses about these may cite this run
    not_exercised_fault_kinds: list[str]  # hypotheses about these may not


class AssessmentOutcome(StrEnum):
    ACCEPTED = "accepted"
    NOT_EXERCISED = "not_exercised"  # the hypothesis's fault never fired in the cited runs
    CONTRADICTS_ORACLE = "contradicts_oracle"  # the status disagrees with the cited verdicts
    CONFLICTING = "conflicting"  # the same hypothesis, assessed two ways on the same evidence
    NO_TARGET_RUN = "no_target_run"  # nothing cited ever ran a target
    UNKNOWN_EVIDENCE = "unknown_evidence"  # an observation that does not exist


class EvidenceStrength(StrEnum):
    # Seen together. Says nothing about cause, whatever an explanation says.
    CORRELATION_ONLY = "correlation_only"
    # A violation with the fault and none without it, on the same world and config. One pair: a
    # contrast worth following up, and still not a demonstration of cause.
    PAIRED_CONTRAST_OBSERVED = "paired_contrast_observed"
    NONE = "none"


class AssessmentCheck(BaseModel):
    """What trusted code made of one model-written assessment. The model's text is kept as is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis_id: str
    claimed_status: str
    effective_status: Literal["supported", "refuted", "inconclusive", "not_exercised"]
    outcome: AssessmentOutcome
    strength: EvidenceStrength = EvidenceStrength.NONE
    cited_observations: list[str]
    eligible_observations: list[str]


class RepeatedHypothesis(BaseModel):
    """A label, not a rejection. A hypothesis that says it revises another is never labeled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hypothesis_id: str
    repeats: str


class ExperimentValidity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str
    run_ref: str
    classification: ValidityClass


class InvestigationValidity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiments: list[ExperimentValidity]
    assessments: list[AssessmentCheck]
    repeated_hypotheses: list[RepeatedHypothesis]
    # None until the model concludes. False: its conclusion disagrees with the verified findings.
    conclusion_matches_findings: bool | None = None
