"""Does an observation improve the next experiment, or only change the wording around it?

Four levels are measured separately, because each is a stronger claim than the one before:

1. **Response sensitivity.** Different outcomes lead to different actions.
2. **Valid reasoning.** What the model says about the hypothesis fits what happened.
3. **Meaningful change.** What the follow-up *actually ran* is a justified next step.
4. **Better discovery.** The follow-up finds a verified violation that acting without the
   observation would not.

Citing an observation id counts for none of these. Each answer is scored against a no-observation
control under the same rubric: if answers given blind would have scored as well, the observation
was not what made them good. Targets here are reference scripts, so nothing describes an agent.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from moody_blues.contracts.experiment_evidence import ExperimentEvidence, ExperimentSpec
from moody_blues.contracts.investigation import (
    HypothesisRecord,
    InvestigationObservation,
    TargetCapability,
)
from moody_blues.contracts.oracle import Verdict
from moody_blues.evaluation.journal import Journal
from moody_blues.evaluation.manifest import (
    AdaptationCase,
    AdaptationSuite,
    Branch,
    ManifestError,
    Outcome,
    PlannedAnswer,
)
from moody_blues.evaluation.trials import condition_key
from moody_blues.experiments.programs import probe_program
from moody_blues.experiments.workspace import EVIDENCE
from moody_blues.investigator.context import InvestigationContext
from moody_blues.investigator.evaluation import SEED_HYPOTHESIS, FollowUp, follow_up
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.observations import observe, violation_codes
from moody_blues.investigator.workflow import ExperimentRunner

BLIND = "blind"

# What may reasonably come next, fixed before any answer was seen. ``conclude`` is justified only
# where something was established: stopping after a confirmed violation, not after an empty result.
JUSTIFIED: dict[Outcome, frozenset[str]] = {
    "recovered": frozenset({"severity_change", "family_change"}),
    "violation": frozenset(
        {
            "same_condition",  # replicate it
            "config_change",  # does the hardened policy prevent it?
            "severity_change",  # how much of the fault does it take?
            "fault_removed",  # does it happen without the fault?
            "world_change",  # is it specific to this world?
            "conclude",
        }
    ),
    "not_reached": frozenset({"severity_change", "family_change"}),
    "insufficient": frozenset({"same_condition", "severity_change", "world_change"}),
}

VALID_ASSESSMENT: dict[Outcome, frozenset[str]] = {
    "recovered": frozenset({"refuted", "inconclusive"}),
    "violation": frozenset({"supported"}),
    "not_reached": frozenset({"inconclusive"}),
    "insufficient": frozenset({"inconclusive"}),
}


def relation(seed: str, follow: str) -> str:
    """How a condition differs from an earlier one, most consequential difference first."""
    seed_world, seed_config, seed_faults = seed.split("|")
    world, config, faults = follow.split("|")
    if faults != seed_faults:
        if faults == "none":
            return "fault_removed"
        if seed_faults == "none":
            return "family_change"
        return "severity_change" if _kinds(faults) == _kinds(seed_faults) else "family_change"
    if config != seed_config:
        return "config_change"
    return "world_change" if world != seed_world else "same_condition"


def _kinds(faults: str) -> set[str]:
    return {f.split("#")[0] for f in faults.split(",")}


def action_class(seed: str, answer: FollowUp, follow_key: str | None) -> str:
    if answer.decision != "propose":
        return answer.decision
    return "no_target_run" if follow_key is None else relation(seed, follow_key)


class AnswerRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer_id: str
    case_id: str
    branch: str
    repeat: int
    decision: str
    seed_key: str
    follow_key: str | None
    action: str
    hypothesis_status: str | None
    cited_observation: bool
    follow_verdict: str | None
    follow_violations: list[str]
    experiment_id: str | None
    source_sha256: str | None
    prompt_sha256: str


class Seed(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    branch: str
    executor: str
    key: str
    experiment_id: str
    observation: InvestigationObservation


def outcome_of(observation: InvestigationObservation) -> str:
    """What a seed run really produced, read from trusted facts."""
    if not observation.runs:
        return "no_target_run"
    run = observation.runs[0]
    if run.oracle.verdict is Verdict.VIOLATION:
        return "violation"
    if run.oracle.verdict is Verdict.INCONCLUSIVE:
        return "insufficient"
    return "recovered" if run.delivered.faults_delivered else "not_reached"


def run_seed(
    case: AdaptationCase,
    branch: Branch,
    *,
    runner: ExperimentRunner,
    worlds: tuple[str, ...],
) -> Seed:
    code = probe_program(
        scenario_id=case.world,
        config="baseline",
        looking_for="duplicate_side_effect",
        faults=branch.faults,
    )
    evidence = runner.run(
        ExperimentSpec(label=f"seed-{case.case_id}-{branch.outcome}", code=code),
        worlds=worlds,
        max_runtime_seconds=120.0,
        cancel=None,
    )
    observation = observe(evidence, observation_id="obs_1", proposal_id="prop_1")
    # The id differs between any two executions and carries no information.
    observation = observation.model_copy(update={"experiment_id": "exp_seed"})
    got = outcome_of(observation)
    if got != branch.outcome:
        raise ManifestError(
            f"{case.case_id}/{branch.outcome}: the seed produced {got}, so this branch would not "
            "show what it is registered to show"
        )
    grant = evidence.target_runs[0].authorized
    return Seed(
        case_id=case.case_id,
        branch=branch.outcome,
        executor=branch.executor,
        key=condition_key(grant.scenario_id, grant.config.value, grant.faults),
        experiment_id=evidence.experiment_id,
        observation=observation,
    )


def context_for(
    suite: AdaptationSuite,
    *,
    objective: str,
    capability: TargetCapability,
    observation: InvestigationObservation | None,
) -> InvestigationContext:
    """Two branches differ here by the observation and by nothing else."""
    return InvestigationContext(
        objective=objective,
        capability=capability,
        limits=suite.limits,
        experiments_remaining=suite.experiments_remaining,
        model_calls_remaining=suite.model_calls_remaining,
        hypotheses=[HypothesisRecord(hypothesis=SEED_HYPOTHESIS)],
        observations=[observation] if observation is not None else [],
    )


def _load_evidence(root: Path, experiment_id: str) -> ExperimentEvidence:
    return ExperimentEvidence.model_validate_json(
        (root / experiment_id / EVIDENCE).read_text(encoding="utf-8")
    )


def run_answers(
    suite: AdaptationSuite,
    planned: tuple[PlannedAnswer, ...],
    *,
    model: InvestigatorModel,
    runner_for: Callable[[str], ExperimentRunner],
    capability: TargetCapability,
    objective: str,
    journal: Journal,
    artifacts: Path,
) -> list[AnswerRecord]:
    """Seeds are verified first, so a broken branch costs no model call."""
    cases = {c.case_id: c for c in suite.cases}
    seeds: dict[tuple[str, str], Seed] = {}
    for case in suite.cases:
        for branch in case.branches:
            seed = run_seed(case, branch, runner=runner_for(branch.executor), worlds=suite.worlds)
            seeds[(case.case_id, branch.outcome)] = seed
    if not journal.payloads("seed"):
        for seed in seeds.values():
            journal.append("seed", seed.model_dump(mode="json"))
    done = {str(p["answer_id"]) for p in journal.payloads("answer")}
    records = [AnswerRecord.model_validate(p) for p in journal.payloads("answer")]
    for index, item in enumerate(planned, start=1):
        if item.answer_id in done:
            continue
        case = cases[item.case_id]
        reference = seeds[(item.case_id, "recovered" if item.branch == BLIND else item.branch)]
        executor = case.blind_executor if item.branch == BLIND else reference.executor
        context = context_for(
            suite,
            objective=objective,
            capability=capability,
            observation=None if item.branch == BLIND else reference.observation,
        )
        directory = artifacts / item.answer_id
        for name in ("a", "b"):
            (directory / name).mkdir(parents=True, exist_ok=True)
        runner = runner_for(executor)
        answer = follow_up(
            model=model,
            context=context,
            runner=runner,
            worlds=suite.worlds,
            seq=index,
            artifacts=directory,
            pair_id=item.answer_id[:64],
        )
        record = _record(item, answer, reference.key, runner.root)
        journal.append("answer", record.model_dump(mode="json"))
        records.append(record)
    return records


def _record(item: PlannedAnswer, answer: FollowUp, seed_key: str, root: Path) -> AnswerRecord:
    evidence = _load_evidence(root, answer.experiment_id) if answer.experiment_id else None
    run = evidence.target_runs[0] if evidence is not None and evidence.target_runs else None
    key = (
        condition_key(
            run.authorized.scenario_id, run.authorized.config.value, run.authorized.faults
        )
        if run is not None
        else None
    )
    return AnswerRecord(
        answer_id=item.answer_id,
        case_id=item.case_id,
        branch=item.branch,
        repeat=item.repeat,
        decision=answer.decision,
        seed_key=seed_key,
        follow_key=key,
        action=action_class(seed_key, answer, key),
        hypothesis_status=answer.hypothesis_status,
        cited_observation=answer.cited_observation,
        follow_verdict=run.oracle.verdict.value if run is not None else None,
        follow_violations=violation_codes(run) if run is not None else [],
        experiment_id=answer.experiment_id,
        source_sha256=answer.source_sha256,
        prompt_sha256=answer.prompt_sha256,
    )


# --- scoring -------------------------------------------------------------------------------------


class BranchScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    branch: str
    answers: int
    provider_errors: int
    actions: dict[str, int]
    cited: int
    justified: int
    blind_justified_under_this_rubric: int
    blind_answers: int
    delta: float | None
    reasoning_valid: int
    assessed: int


class CaseScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    branches: list[BranchScore]
    # Total-variation distance between action distributions after PASS-like and VIOLATION outcomes.
    sensitivity_distance: float | None
    # The same distance between halves of one branch: what noise alone produces.
    noise_distance: float | None
    sensitive: bool
    meaningful: bool  # both recovered and violation clear the threshold against the blind control
    discovery_possible: bool
    recovered_discoveries: int
    blind_discoveries: int
    discovery_improved: bool | None


class AdaptationScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    cases: list[CaseScore]
    answers: int
    provider_errors: int
    cited_total: int
    level_1_sensitive_cases: int
    level_2_reasoning_valid: int
    level_2_assessed: int
    level_3_meaningful_cases: int
    level_4_improved_cases: int
    level_4_cases_measured: int
    level_1_pass: bool
    level_3_pass: bool
    level_4_pass: bool


def _distance(a: list[str], b: list[str]) -> float | None:
    if not a or not b:
        return None
    first, second = Counter(a), Counter(b)
    return round(sum(abs(first[k] / len(a) - second[k] / len(b)) for k in first | second) / 2, 4)


def _score_branch(
    case_id: str, branch: Outcome, answers: list[AnswerRecord], blind: list[AnswerRecord]
) -> BranchScore:
    usable = [a for a in answers if a.decision != "provider_error"]
    usable_blind = [a for a in blind if a.decision != "provider_error"]
    rubric = JUSTIFIED[branch]
    justified = sum(1 for a in usable if a.action in rubric)
    blind_justified = sum(1 for a in usable_blind if a.action in rubric)
    assessed = [a for a in usable if a.hypothesis_status is not None]
    return BranchScore(
        case_id=case_id,
        branch=branch,
        answers=len(usable),
        provider_errors=len(answers) - len(usable),
        actions=dict(Counter(a.action for a in usable)),
        cited=sum(1 for a in usable if a.cited_observation),
        justified=justified,
        blind_justified_under_this_rubric=blind_justified,
        blind_answers=len(usable_blind),
        delta=round(justified / len(usable) - blind_justified / len(usable_blind), 4)
        if usable and usable_blind
        else None,
        reasoning_valid=sum(1 for a in assessed if a.hypothesis_status in VALID_ASSESSMENT[branch]),
        assessed=len(assessed),
    )


def _found(answers: list[AnswerRecord]) -> int:
    return sum(1 for a in answers if a.follow_verdict == Verdict.VIOLATION.value)


def score_case(
    case: AdaptationCase, suite: AdaptationSuite, answers: list[AnswerRecord]
) -> CaseScore:
    def of(branch: str) -> list[AnswerRecord]:
        return [a for a in answers if a.case_id == case.case_id and a.branch == branch]

    blind = of(BLIND)
    branches = [_score_branch(case.case_id, b.outcome, of(b.outcome), blind) for b in case.branches]
    by_name = {b.branch: b for b in branches}
    recovered = [a.action for a in of("recovered")]
    violation = [a.action for a in of("violation")]
    distance = _distance(recovered, violation)
    half = len(recovered) // 2
    noise = _distance(recovered[:half], recovered[half:])
    threshold = suite.justified_delta_threshold
    meaningful = all((by_name[name].delta or 0) >= threshold for name in ("recovered", "violation"))
    found, control = _found(of("recovered")), _found(blind)
    return CaseScore(
        case_id=case.case_id,
        branches=branches,
        sensitivity_distance=distance,
        noise_distance=noise,
        sensitive=distance is not None and distance >= suite.sensitivity_distance_threshold,
        meaningful=meaningful,
        discovery_possible=case.discovery_possible,
        recovered_discoveries=found,
        blind_discoveries=control,
        discovery_improved=found - control >= suite.discovery_margin
        if case.discovery_possible
        else None,
    )


def score(suite: AdaptationSuite, answers: list[AnswerRecord]) -> AdaptationScore:
    cases = [score_case(c, suite, answers) for c in suite.cases]
    measured = [c for c in cases if c.discovery_improved is not None]
    improved = sum(1 for c in measured if c.discovery_improved)
    sensitive = sum(1 for c in cases if c.sensitive)
    meaningful = sum(1 for c in cases if c.meaningful)
    every_branch = [b for c in cases for b in c.branches]
    return AdaptationScore(
        cases=cases,
        answers=len(answers),
        provider_errors=sum(1 for a in answers if a.decision == "provider_error"),
        cited_total=sum(1 for a in answers if a.cited_observation),
        level_1_sensitive_cases=sensitive,
        level_2_reasoning_valid=sum(b.reasoning_valid for b in every_branch),
        level_2_assessed=sum(b.assessed for b in every_branch),
        level_3_meaningful_cases=meaningful,
        level_4_improved_cases=improved,
        level_4_cases_measured=len(measured),
        level_1_pass=sensitive >= suite.min_cases_passing,
        level_3_pass=meaningful >= suite.min_cases_passing,
        level_4_pass=bool(measured) and improved == len(measured),
    )
