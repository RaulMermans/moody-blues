"""Runs the frozen plan. What to run and in what order comes from the plan, never from results.

The only decisions taken during a run are the ones the manifest registered, and each reads only
eligibility or the registered stage rule. Replacement of an impaired attempt looks at eligibility,
which is itself read without the outcome, and impaired attempts stay on the record.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, ExperimentState
from moody_blues.contracts.investigation import (
    InvestigationReport,
    ProposalStatus,
)
from moody_blues.evaluation.attribution import Attribution, ContrastRule, assess_contrast
from moody_blues.evaluation.journal import Journal
from moody_blues.evaluation.manifest import (
    CausalSuite,
    Faults,
    Manifest,
    PlannedCausalTrial,
    PlannedInvestigation,
    TrialPlan,
)
from moody_blues.evaluation.trials import TrialRecord, trial_from_run, trial_without_run
from moody_blues.experiments.recovery import verify_experiment


class SuiteStoppedError(RuntimeError):
    """The suite cannot continue, usually because the budget refused further work."""


class CausalExecutor(Protocol):
    root: Path

    def run(
        self, *, trial_id: str, world: str, config: AgentConfigName, faults: Faults
    ) -> ExperimentEvidence: ...

    def remaining_usd(self) -> float: ...

    @property
    def reservation_usd(self) -> float: ...


class InvestigationExecutor(Protocol):
    root: Path

    def run(self, unit: PlannedInvestigation) -> InvestigationReport: ...

    def evidence(self, experiment_id: str) -> ExperimentEvidence: ...


def cell_of(trial: TrialRecord) -> str:
    return f"{trial.condition_id}/{trial.config}"


def _trial(
    evidence: ExperimentEvidence,
    *,
    root: Path,
    suite: str,
    trial_id: str,
    unit_id: str,
    block: int,
    max_tool_calls: int,
    attempt: int = 1,
    strategy: str | None = None,
    condition_id: str | None = None,
) -> TrialRecord:
    if not evidence.target_runs:
        return trial_without_run(
            evidence,
            root=root,
            suite=suite,
            trial_id=trial_id,
            unit_id=unit_id,
            block=block,
            attempt=attempt,
            strategy=strategy,
            condition_id=condition_id,
        )
    intact = not verify_experiment(root / evidence.experiment_id)
    return trial_from_run(
        evidence,
        evidence.target_runs[0],
        root=root,
        suite=suite,
        trial_id=trial_id,
        unit_id=unit_id,
        block=block,
        evidence_intact=intact,
        max_tool_calls=max_tool_calls,
        attempt=attempt,
        strategy=strategy,
        condition_id=condition_id,
    )


def _run_causal_trial(
    planned: PlannedCausalTrial,
    *,
    manifest: Manifest,
    executor: CausalExecutor,
    journal: Journal,
    attempt: int,
) -> TrialRecord:
    suite = manifest.causal
    condition = next(c for c in suite.conditions if c.condition_id == planned.condition_id)
    journal.append(
        "started",
        {
            "id": planned.trial_id,
            "condition_id": planned.condition_id,
            "config": planned.config.value,
        },
    )
    evidence = executor.run(
        trial_id=planned.trial_id,
        world=suite.world,
        config=planned.config,
        faults=condition.faults,
    )
    if evidence.status is ExperimentState.BUDGET_EXHAUSTED and not evidence.target_runs:
        journal.append("abandoned", {"id": planned.trial_id, "reason": "budget_refused"})
        raise SuiteStoppedError(f"budget refused {planned.trial_id}")
    trial = _trial(
        evidence,
        root=executor.root,
        suite="causal",
        trial_id=planned.trial_id,
        unit_id=planned.trial_id,
        block=planned.block,
        max_tool_calls=manifest.target_budget.max_tool_calls,
        attempt=attempt,
        condition_id=planned.condition_id,
    )
    journal.record_trial(trial)
    return trial


def _run_stage(
    planned: Sequence[PlannedCausalTrial],
    target: int,
    *,
    manifest: Manifest,
    executor: CausalExecutor,
    journal: Journal,
) -> None:
    for item in planned:
        if item.trial_id not in {t.trial_id for t in journal.trials()}:
            _run_causal_trial(
                item, manifest=manifest, executor=executor, journal=journal, attempt=1
            )
    suite = manifest.causal
    seen: dict[str, PlannedCausalTrial] = {}
    for item in planned:
        seen.setdefault(f"{item.condition_id}/{item.config.value}", item)
    for cell, first in seen.items():
        while True:
            trials = [t for t in journal.trials() if cell_of(t) == cell]
            eligible = sum(1 for t in trials if t.eligible)
            if eligible >= target or len(trials) >= suite.max_attempts_per_cell:
                break
            attempt = len(trials) + 1
            replacement = first.model_copy(
                update={"trial_id": f"{cell.replace('/', '-')}-replacement-{attempt}"}
            )
            _run_causal_trial(
                replacement,
                manifest=manifest,
                executor=executor,
                journal=journal,
                attempt=attempt,
            )


def contrast(
    suite: CausalSuite, trials: list[TrialRecord], rule: ContrastRule, config: str = "baseline"
) -> Attribution:
    def arm(condition: str) -> list[TrialRecord]:
        return [t for t in trials if t.condition_id == condition and t.config == config]

    return assess_contrast(
        fault_arm=f"{suite.fault_condition}/{config}",
        fault=arm(suite.fault_condition),
        control_arm=f"{suite.control_condition}/{config}",
        control=arm(suite.control_condition),
        changed="only the stale_read fault; same world, seed state, objective, model and policy",
        rule=rule,
    )


def stage_two_decision(
    manifest: Manifest,
    plan: TrialPlan,
    trials: list[TrialRecord],
    *,
    remaining_usd: float,
    reservation_usd: float,
) -> dict[str, JsonValue]:
    """Extend every cell or none: extending only the interesting cells would pick a denominator."""
    suite = manifest.causal
    first = contrast(suite, trials, suite.stage_one_rule)
    costs = [t.estimated_cost_usd for t in trials if t.estimated_cost_usd is not None]
    mean = sum(costs) / len(costs) if costs else 0.0
    needed = (
        manifest.budget.stage_two_safety_factor * mean * len(plan.causal_stage_two)
        + reservation_usd
    )
    conclusive = first.level.value == "causal_evidence_supports_fault"
    return {
        "stage_one_level": first.level.value,
        "extend": not conclusive and remaining_usd >= needed,
        "reason": "stage_one_conclusive"
        if conclusive
        else "inconclusive_and_affordable"
        if remaining_usd >= needed
        else "inconclusive_but_over_budget",
        "needed_usd": round(needed, 4),
        "remaining_usd": round(remaining_usd, 4),
    }


def run_causal(
    manifest: Manifest, plan: TrialPlan, *, executor: CausalExecutor, journal: Journal
) -> list[TrialRecord]:
    journal.close_unfinished(suite="causal")
    suite = manifest.causal
    _run_stage(
        plan.causal_stage_one,
        suite.stage_one_eligible,
        manifest=manifest,
        executor=executor,
        journal=journal,
    )
    decisions = journal.payloads("stage_decision")
    if not decisions:
        decision = stage_two_decision(
            manifest,
            plan,
            journal.trials(),
            remaining_usd=executor.remaining_usd(),
            reservation_usd=executor.reservation_usd,
        )
        journal.append("stage_decision", decision)
    else:
        decision = decisions[0]
    if decision["extend"]:
        _run_stage(
            plan.causal_stage_two,
            suite.stage_two_eligible,
            manifest=manifest,
            executor=executor,
            journal=journal,
        )
    return journal.trials()


class UnitSummary(BaseModel):
    """One investigation. Runs live in trial records; this holds what only the whole shows."""

    model_config = ConfigDict(frozen=True)

    unit_id: str
    block: int
    strategy: str
    investigation_id: str
    state: str
    termination: str | None
    experiments_with_run: int
    programs_generated: int
    programs_rejected: int
    refinements: int
    cited_observations: int
    hypothesis_revisions: int
    model_calls: int
    investigator_tokens: int
    investigator_cost_usd: float
    target_tokens: int
    target_cost_usd: float
    wall_ms: int
    usage_complete: bool
    claims_made: int
    unsupported_claims: int


def unit_summary(report: InvestigationReport, unit: PlannedInvestigation) -> UnitSummary:
    usage = report.usage
    executed = [p for p in report.proposals if p.status is ProposalStatus.EXECUTED]
    return UnitSummary(
        unit_id=unit.unit_id,
        block=unit.block,
        strategy=unit.strategy.value,
        investigation_id=report.investigation_id,
        state=report.state.value,
        termination=report.termination,
        experiments_with_run=sum(1 for e in report.experiments if e.target_run_ids),
        programs_generated=sum(1 for p in report.proposals if p.model_call_seq is not None),
        programs_rejected=sum(
            1 for p in report.proposals if p.status is ProposalStatus.REJECTED_BEFORE_EXECUTION
        ),
        refinements=sum(1 for d in report.decisions if d.kind.value == "refine"),
        cited_observations=sum(1 for p in executed if p.motivated_by),
        hypothesis_revisions=sum(1 for h in report.hypotheses if h.hypothesis.revises is not None),
        model_calls=usage.model_calls,
        investigator_tokens=usage.investigator_prompt_tokens + usage.investigator_completion_tokens,
        investigator_cost_usd=usage.investigator_cost_usd,
        target_tokens=usage.target_tokens,
        target_cost_usd=usage.target_cost_usd,
        wall_ms=usage.wall_ms,
        usage_complete=usage.usage_complete,
        claims_made=len(report.claim_checks),
        unsupported_claims=sum(1 for c in report.claim_checks if not c.supported),
    )


def run_strategies(
    manifest: Manifest, plan: TrialPlan, *, executor: InvestigationExecutor, journal: Journal
) -> list[TrialRecord]:
    journal.close_unfinished(suite="strategies")
    for unit in plan.strategies:
        # A unit that started is never restarted: a crash leaves it on the record as incomplete.
        if unit.unit_id in {str(p["id"]) for p in journal.payloads("started")}:
            continue
        journal.append("started", {"id": unit.unit_id})
        report = executor.run(unit)
        for index, ref in enumerate(report.experiments, start=1):
            journal.record_trial(
                _trial(
                    executor.evidence(ref.experiment_id),
                    root=executor.root,
                    suite="strategies",
                    trial_id=f"{unit.unit_id}-e{index}",
                    unit_id=unit.unit_id,
                    block=unit.block,
                    max_tool_calls=manifest.target_budget.max_tool_calls,
                    strategy=unit.strategy.value,
                )
            )
        journal.append("unit", unit_summary(report, unit).model_dump(mode="json"))
        journal.append("abandoned", {"id": unit.unit_id, "reason": "unit_closed"})
        if report.termination in {"spend_limit", "experiment_budget"}:
            raise SuiteStoppedError(f"budget refused during {unit.unit_id}")
    return journal.trials()
