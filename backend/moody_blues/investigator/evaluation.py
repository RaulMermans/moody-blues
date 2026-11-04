"""Does the Investigator adapt, and does adapting help? Two separate measurements.

**Paired counterfactual (adaptation).** A first experiment is fixed, and run against two
reference executors that really behave differently, so two valid observations exist. The model
then decides the next step from prompts that differ only in that observation. Each branch is
asked twice: if the two answers within a branch disagree as much as answers across branches do,
a difference is noise rather than adaptation. Follow-up programs are executed, so what is
compared is what they *did*, not what they said. Reference targets cost nothing, and no result
here describes a target agent.

**Strategy comparison (value).** Fixed, one-shot and adaptive get the same worlds, experiment
budget, target model and verification. Generated, adaptively chosen and discovered are counted
separately because they are different achievements.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from moody_blues.contracts.experiment_evidence import (
    ExperimentAuthorship,
    ExperimentEvidence,
    ExperimentSpec,
    GenerationRecord,
)
from moody_blues.contracts.investigation import (
    ConcludeInvestigation,
    FindingClass,
    GenerationDiagnostic,
    Hypothesis,
    HypothesisRecord,
    InvestigationLimits,
    InvestigationObservation,
    InvestigationReport,
    ProposalStatus,
    ProposePlan,
    ReproductionStatus,
    Strategy,
    TargetCapability,
)
from moody_blues.experiments.programs import probe_program
from moody_blues.experiments.workspace import sha256_text
from moody_blues.investigator.context import InvestigationContext, build_messages
from moody_blues.investigator.model import (
    CONCLUDE_TOOL,
    PROPOSE_TOOL,
    InvestigatorModel,
    parse_decision,
)
from moody_blues.investigator.observations import observe
from moody_blues.investigator.workflow import ExperimentRunner

PairDecision = Literal["propose", "conclude", "invalid", "provider_error"]


@dataclass(frozen=True, slots=True)
class PairCase:
    case_id: str
    world: str
    faults: list[dict[str, Any]]
    executor_a: str
    executor_b: str


PAIR_CASES: tuple[PairCase, ...] = (
    PairCase(
        "timeout-retry",
        "w-v1",
        [{"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}],
        "verify_then_report",
        "blind_retry",
    ),
    PairCase(
        "false-success",
        "w-v2",
        [{"kind": "phantom_success", "occurrence": 1}],
        "verify_then_report",
        "trusting",
    ),
    PairCase(
        "lagging-read",
        "w-v1",
        [{"kind": "stale_read", "occurrence": 1, "span": 2}],
        "idempotent_retry",
        "verify_then_report",
    ),
)

SEED_HYPOTHESIS = Hypothesis(
    hypothesis_id="h1",
    behavior="how the target handles the injected distortion",
    suspected_mechanism="the target acts on the delivered response without checking state",
    motivating_observations=[],
    motivation="first experiment, fixed by the evaluation so that only its result varies",
    predicted_observation="an Oracle violation in the first run",
    failure_discriminator="the Oracle verdict and finding codes of the run",
)


class FollowUp(BaseModel):
    """One answer, reduced to what it actually did."""

    model_config = ConfigDict(frozen=True)

    decision: PairDecision
    selection: str | None  # world, config and faults of the run the program really performed
    source_sha256: str | None
    experiment_id: str | None
    cited_observation: bool
    hypothesis_status: str | None
    prompt_sha256: str


class PairResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    verdict_a: str
    verdict_b: str
    observations_differ: bool
    context_identical_except_observation: bool
    a: list[FollowUp]
    b: list[FollowUp]
    within_a_stable: bool
    within_b_stable: bool
    across_differs: bool
    # Across-branch difference with both branches stable: the only result counted as adaptation.
    adaptation_shown: bool


def _signature(item: FollowUp) -> tuple[str, str | None]:
    return item.decision, item.selection


def selection_of(evidence: ExperimentEvidence) -> str | None:
    if not evidence.target_runs:
        return None
    grant = evidence.target_runs[0].authorized
    faults = sorted(f"{f.kind.value}#{f.occurrence}x{f.span}" for f in grant.faults)
    return f"{grant.scenario_id}|{grant.config.value}|{grant.fault_source}|{','.join(faults)}"


def _follow_up(
    *,
    model: InvestigatorModel,
    context: InvestigationContext,
    runner: ExperimentRunner,
    worlds: tuple[str, ...],
    seq: int,
    artifacts: Path,
    pair_id: str,
) -> FollowUp:
    messages = build_messages(context)
    offered = [PROPOSE_TOOL, CONCLUDE_TOOL]
    call = model.call(
        seq=seq, purpose="paired", messages=messages, offered=offered, artifact_dir=artifacts
    )
    prompt = call.record.prompt_sha256
    empty = {"selection": None, "source_sha256": None, "experiment_id": None}
    if call.result is None:
        return FollowUp(
            decision="provider_error",
            cited_observation=False,
            hypothesis_status=None,
            prompt_sha256=prompt,
            **empty,
        )
    decision = parse_decision(call.result, offered)
    if isinstance(decision, GenerationDiagnostic):
        return FollowUp(
            decision="invalid",
            cited_observation=False,
            hypothesis_status=None,
            prompt_sha256=prompt,
            **empty,
        )
    assert not isinstance(decision, ProposePlan)  # noqa: S101 - never offered here
    assessed = next((a.status for a in decision.assessments), None)
    if isinstance(decision, ConcludeInvestigation):
        return FollowUp(
            decision="conclude",
            cited_observation=any(a.cited_observations for a in decision.assessments),
            hypothesis_status=assessed,
            prompt_sha256=prompt,
            **empty,
        )
    code = decision.experiment.python_code
    evidence = runner.run(
        ExperimentSpec(
            label=decision.experiment.label,
            code=code,
            parent_investigation_id=pair_id,
            authorship=ExperimentAuthorship.MODEL_GENERATED,
            generation=GenerationRecord(
                proposal_id=f"pair-{seq}", model=model.model, evidence_source=model.evidence
            ),
        ),
        worlds=worlds,
        max_runtime_seconds=60.0,
        cancel=None,
    )
    return FollowUp(
        decision="propose",
        selection=selection_of(evidence),
        source_sha256=sha256_text(code),
        experiment_id=evidence.experiment_id,
        cited_observation=bool(decision.experiment.motivated_by),
        hypothesis_status=assessed,
        prompt_sha256=prompt,
    )


def run_pair(
    case: PairCase,
    *,
    model: InvestigatorModel,
    runner_for: Callable[[str], ExperimentRunner],
    capability: TargetCapability,
    worlds: tuple[str, ...],
    objective: str,
    limits: InvestigationLimits,
    artifacts: Path,
    repeats: int = 2,
) -> PairResult:
    artifacts.mkdir(parents=True, exist_ok=True)
    pair_id = f"pair_{uuid4().hex[:12]}"
    seed_code = probe_program(
        scenario_id=case.world,
        config="baseline",
        looking_for="duplicate_side_effect",
        faults=case.faults,
    )
    contexts: list[InvestigationContext] = []
    observations: list[InvestigationObservation] = []
    for executor in (case.executor_a, case.executor_b):
        evidence = runner_for(executor).run(
            ExperimentSpec(label=f"pair-seed-{case.case_id}", code=seed_code),
            worlds=worlds,
            max_runtime_seconds=60.0,
            cancel=None,
        )
        observation = observe(evidence, observation_id="obs_1", proposal_id="prop_1")
        # The experiment id differs between any two executions and carries no information.
        observation = observation.model_copy(update={"experiment_id": "exp_seed"})
        observations.append(observation)
        contexts.append(
            InvestigationContext(
                objective=objective,
                capability=capability,
                limits=limits,
                experiments_remaining=2,
                model_calls_remaining=4,
                hypotheses=[HypothesisRecord(hypothesis=SEED_HYPOTHESIS)],
                observations=[observation],
            )
        )
    seq = 0
    answers: list[list[FollowUp]] = [[], []]
    for branch, executor in enumerate((case.executor_a, case.executor_b)):
        for _ in range(repeats):
            seq += 1
            answers[branch].append(
                _follow_up(
                    model=model,
                    context=contexts[branch],
                    runner=runner_for(executor),
                    worlds=worlds,
                    seq=seq,
                    artifacts=artifacts,
                    pair_id=pair_id,
                )
            )
    a, b = answers
    verdicts = [o.runs[0].oracle.verdict.value if o.runs else "none" for o in observations]
    within_a = len({_signature(x) for x in a}) == 1
    within_b = len({_signature(x) for x in b}) == 1
    across = not ({_signature(x) for x in a} & {_signature(x) for x in b})
    differ = observations[0] != observations[1]
    same_rest = (
        contexts[0].model_copy(update={"observations": []}).model_dump_json()
        == contexts[1].model_copy(update={"observations": []}).model_dump_json()
    )
    return PairResult(
        case_id=case.case_id,
        verdict_a=verdicts[0],
        verdict_b=verdicts[1],
        observations_differ=differ,
        context_identical_except_observation=same_rest,
        a=a,
        b=b,
        within_a_stable=within_a,
        within_b_stable=within_b,
        across_differs=across,
        adaptation_shown=differ and same_rest and within_a and within_b and across,
    )


class StrategyRow(BaseModel):
    """One investigation, in the terms the comparison reports."""

    model_config = ConfigDict(frozen=True)

    investigation_id: str
    strategy: Strategy
    trial: int
    state: str
    termination: str | None
    programs_generated: int
    programs_rejected: int
    refinements: int
    experiments_with_target_run: int
    distinct_conditions: int
    adaptively_selected: int  # executed programs citing an earlier observation
    hypothesis_revisions: int
    live_confirmed_violations: int
    reproduced: int
    not_reproduced: int
    violation_codes: list[str]
    correct_recoveries: int
    target_shortfalls: int
    unsupported_claims: int
    model_calls: int
    investigator_tokens: int
    target_tokens: int
    investigator_latency_ms: int
    wall_ms: int
    estimated_cost_usd: float


def strategy_row(report: InvestigationReport, trial: int) -> StrategyRow:
    r, u = report, report.usage
    original = [e for e in r.experiments if e.reproduction_of is None]
    conditions = {
        (
            f.world_ref,
            f.config.value,
            tuple((x.kind, x.occurrence, x.span) for x in f.selected_faults),
        )
        for f in r.findings
    }
    generated = [p for p in r.proposals if p.authorship is ExperimentAuthorship.MODEL_GENERATED]
    executed = [p for p in generated if p.status is ProposalStatus.EXECUTED]
    confirmed = [
        f
        for f in r.findings
        if f.finding_class is FindingClass.ORACLE_CONFIRMED_VIOLATION and f.is_model_behavior
    ]
    return StrategyRow(
        investigation_id=r.investigation_id,
        strategy=r.request.strategy,
        trial=trial,
        state=r.state.value,
        termination=r.termination,
        programs_generated=len(generated),
        programs_rejected=len(generated) - len(executed),
        refinements=sum(1 for d in r.decisions if d.kind.value == "refine"),
        experiments_with_target_run=sum(1 for e in original if e.target_run_ids),
        distinct_conditions=len(conditions),
        adaptively_selected=sum(1 for p in executed if p.motivated_by),
        hypothesis_revisions=sum(1 for h in r.hypotheses if h.hypothesis.revises is not None),
        live_confirmed_violations=len(confirmed),
        reproduced=sum(1 for f in confirmed if f.reproduction is ReproductionStatus.REPRODUCED),
        not_reproduced=sum(
            1 for f in confirmed if f.reproduction is ReproductionStatus.NOT_REPRODUCED
        ),
        violation_codes=sorted({c for f in confirmed for c in f.violation_codes}),
        correct_recoveries=sum(
            1 for f in r.findings if f.finding_class is FindingClass.CORRECT_RECOVERY
        ),
        target_shortfalls=sum(
            1 for f in r.findings if f.finding_class is FindingClass.TARGET_SHORTFALL
        ),
        unsupported_claims=sum(1 for c in r.claim_checks if not c.supported),
        model_calls=u.model_calls,
        investigator_tokens=u.investigator_prompt_tokens + u.investigator_completion_tokens,
        target_tokens=u.target_tokens,
        investigator_latency_ms=u.investigator_latency_ms,
        wall_ms=u.wall_ms,
        estimated_cost_usd=round(u.investigator_cost_usd + u.target_cost_usd, 6),
    )


def render_comparison(rows: list[StrategyRow]) -> str:
    header = (
        "| Strategy | Trial | State | Generated | Rejected | Runs | Conditions | Cited prior obs "
        "| Revisions | Live violations | Reproduced | Codes | Recoveries | Shortfalls "
        "| Unsupported claims | Model calls | Inv tokens | Target tokens | Est. $ |"
    )
    lines = [header, "|" + "---|" * 19]
    for r in rows:
        lines.append(
            f"| {r.strategy.value} | {r.trial} | {r.state} | {r.programs_generated} "
            f"| {r.programs_rejected} | {r.experiments_with_target_run} "
            f"| {r.distinct_conditions} | {r.adaptively_selected} | {r.hypothesis_revisions} "
            f"| {r.live_confirmed_violations} | {r.reproduced} "
            f"| {', '.join(r.violation_codes) or '-'} | {r.correct_recoveries} "
            f"| {r.target_shortfalls} | {r.unsupported_claims} | {r.model_calls} "
            f"| {r.investigator_tokens} | {r.target_tokens} | {r.estimated_cost_usd:.4f} |"
        )
    return "\n".join(lines) + "\n"


def render_pairs(results: list[PairResult]) -> str:
    lines = [
        "| Case | Seed verdicts A/B | Observations differ | A answers | B answers "
        "| Stable A/B | Differ across | Adaptation shown |",
        "|" + "---|" * 8,
    ]

    def show(items: list[FollowUp]) -> str:
        return "; ".join(f"{i.decision}:{i.selection or '-'}" for i in items)

    for r in results:
        lines.append(
            f"| {r.case_id} | {r.verdict_a}/{r.verdict_b} | {r.observations_differ} "
            f"| {show(r.a)} | {show(r.b)} | {r.within_a_stable}/{r.within_b_stable} "
            f"| {r.across_differs} | {r.adaptation_shown} |"
        )
    return "\n".join(lines) + "\n"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
