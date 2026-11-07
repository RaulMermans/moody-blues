"""Results, computed from the raw records and nothing else.

The source is each run's evidence file: the Oracle's report, the gateway's trace and what the
coordinator authorized. An Investigator's own words never feed a metric. Eligibility is decided
before a verdict is read, and the decision rule is the one frozen in the specification.

Units are target policies. Seeds within a unit are replicates, not independent samples, so they are
averaged first. There are no significance tests: the only interval is the exact one on raw counts
of which strategy did better per unit, used as a registered threshold.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from statistics import mean, median

from pydantic import BaseModel, ConfigDict, JsonValue

from moody_blues.contracts.experiment_evidence import (
    ExperimentEvidence,
    ExperimentState,
    TargetRunEvidence,
)
from moody_blues.contracts.investigation import (
    InvestigationReport,
    ProposalStatus,
    ReproductionStatus,
)
from moody_blues.contracts.oracle import Verdict
from moody_blues.contracts.scenario import FaultKind, FaultSpec
from moody_blues.contracts.validity import ValidityClass
from moody_blues.evaluation.benchmark.run import journal_path
from moody_blues.evaluation.benchmark.spec import (
    Candidate,
    PlannedTrial,
    Spec,
    Stage,
    StrategyName,
    Unit,
    expand_plan,
    spec_sha,
)
from moody_blues.evaluation.journal import Journal
from moody_blues.evaluation.stats import clopper_pearson
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.workspace import EVIDENCE
from moody_blues.investigator.findings import impairments_of, reproduction_status
from moody_blues.investigator.observations import violation_codes
from moody_blues.investigator.quality import QualityAudit, audit
from moody_blues.investigator.validity import run_validity
from moody_blues.investigator.workspace import REPORT, verify_investigation

ADVANTAGE = "ADAPTIVE_ADVANTAGE_SUPPORTED"
BASELINE_ADVANTAGE = "BASELINE_ADVANTAGE_SUPPORTED"
NO_ADVANTAGE = "NO_DEMONSTRATED_ADVANTAGE"
INCONCLUSIVE = "INCONCLUSIVE"


def fault_key(kind: str, occurrence: int, span: int, error_code: str | None) -> str:
    code = error_code if kind == FaultKind.PHANTOM_FAILURE.value else None
    return f"{kind}#{occurrence}x{span}:{code or '-'}"


def candidate_condition(candidate: Candidate) -> tuple[str, tuple[str, ...]]:
    faults: list[str] = []
    for fault in candidate.faults:
        occurrence, span, code = fault["occurrence"], fault.get("span", 1), fault.get("error_code")
        faults.append(
            fault_key(
                str(fault["kind"]),
                occurrence if isinstance(occurrence, int) else 1,
                span if isinstance(span, int) else 1,
                str(code) if code is not None else None,
            )
        )
    return candidate.scenario_id, tuple(sorted(faults))


def run_condition(scenario_id: str, faults: Sequence[FaultSpec]) -> tuple[str, tuple[str, ...]]:
    keys = [fault_key(f.kind.value, f.occurrence, f.span, f.error_code.value) for f in faults]
    return scenario_id, tuple(sorted(keys))


def signatures(world: str, run: TargetRunEvidence) -> list[str]:
    """Canonical: the world and the Oracle's violation code. Wording plays no part."""
    if run.oracle.verdict is not Verdict.VIOLATION:
        return []
    return [f"{world}:{code}" for code in violation_codes(run)]


def state_agrees(run: TargetRunEvidence) -> bool:
    """The Oracle's verdict against what the run's own committed state shows, for the codes that
    can be read back. A disagreement means the Oracle, not the target, needs looking at."""
    codes = set(violation_codes(run))
    new = len(run.committed.new_ids)
    if "duplicate_side_effect" in codes and new < 2:
        return False
    return not ("unintended_record" in codes and new < 1)


class ExperimentRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str
    experiment_id: str
    position: int
    candidate: str | None
    validity: str | None
    eligible: bool
    excluded_because: str | None
    verdict: str | None
    signatures: list[str]
    faults_delivered: int
    repeated_candidate: bool
    state_agrees: bool | None


class TrialRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str
    stage: Stage
    unit_id: str
    world: str
    strategy: StrategyName
    seed: int | None
    state: str
    termination: str | None
    attempted: int
    rejected: int
    executed: int
    eligible: int
    undelivered: int
    distinct_eligible: list[str]
    distinct_any: list[str]
    verified_violation_runs: int
    first_violation_position: int | None
    first_violation_ms: int | None
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    model_latency_ms: int
    tool_calls: int
    wall_ms: int
    sandbox_ms: int
    ollama_rss_kb: int | None
    evidence_complete: bool
    problems: list[str]
    quality: QualityAudit | None
    experiments: list[ExperimentRow]

    @property
    def primary(self) -> float | None:
        return 10 * len(self.distinct_eligible) / self.eligible if self.eligible else None

    def per_attempted(self) -> float | None:
        return 10 * len(self.distinct_any) / self.attempted if self.attempted else None


def _excluded(
    evidence: ExperimentEvidence, candidate: str | None, intact: bool
) -> tuple[str | None, str | None]:
    """Why an experiment is not eligible, and its validity. Reads no verdict."""
    if evidence.unresolved_target_runs:
        return "unresolved_run", None
    if len(evidence.target_runs) != 1 or evidence.status is not ExperimentState.COMPLETED:
        return "no_completed_run", None
    run = evidence.target_runs[0]
    validity = run_validity(run).classification
    if not intact:
        return "evidence_not_intact", validity.value
    if candidate is None:
        return "outside_candidate_space", validity.value
    if impairments_of(run, evidence_intact=True):
        return "impaired_run", validity.value
    if validity is ValidityClass.NOT_EXERCISED:
        return "undelivered_fault", validity.value
    return None, validity.value


def load_evidence(root: Path, experiment_id: str) -> ExperimentEvidence:
    path = root / "experiments" / experiment_id / EVIDENCE
    return ExperimentEvidence.model_validate_json(path.read_text(encoding="utf-8"))


def _trial_row(
    spec: Spec,
    planned: PlannedTrial,
    payload: dict[str, JsonValue],
    root: Path,
    conditions: dict[tuple[str, tuple[str, ...]], str],
) -> TrialRow:
    unit = next(u for u in spec.units if u.unit_id == planned.unit_id)
    directory = root / "investigations" / str(payload["investigation_id"])
    raw = (directory / REPORT).read_bytes()
    problems = list(verify_investigation(directory, root / "experiments"))
    if hashlib.sha256(raw).hexdigest() != payload["report_sha256"]:
        problems.append("report does not match the journal")
    report = InvestigationReport.model_validate_json(raw)
    rows: list[ExperimentRow] = []
    seen: set[str] = set()
    distinct_eligible: set[str] = set()
    distinct_any: set[str] = set()
    violations = 0
    first_position: int | None = None
    first_ms: int | None = None
    tool_calls = 0
    sandbox_ms = 0
    proposals = {p.proposal_id: p for p in report.proposals}
    for position, ref in enumerate(report.experiments, start=1):
        directory = root / "experiments" / ref.experiment_id
        evidence = load_evidence(root, ref.experiment_id)
        text = (directory / EVIDENCE).read_text(encoding="utf-8")
        same = hashlib.sha256(text.encode()).hexdigest() == ref.evidence_sha256
        intact = same and not verify_experiment(directory)
        if not intact:
            problems.append(f"{ref.experiment_id}: evidence not intact")
        run = evidence.target_runs[0] if evidence.target_runs else None
        candidate = (
            conditions.get(run_condition(run.authorized.scenario_id, run.authorized.faults))
            if run is not None
            else None
        )
        why, validity = _excluded(evidence, candidate, intact)
        found = signatures(unit.world_type, run) if run is not None else []
        if run is not None:
            tool_calls += len(run.target_observed.tool_trace)
        sandbox_ms += evidence.usage.sandbox_ms
        chosen_at = proposals[ref.proposal_id].model_call_seq or 0
        elapsed = sandbox_ms + sum(c.latency_ms for c in report.model_calls if c.seq <= chosen_at)
        distinct_any.update(found)
        if why is None:
            distinct_eligible.update(found)
        if found:
            violations += 1
            if first_position is None and why is None:
                first_position, first_ms = position, elapsed
        rows.append(
            ExperimentRow(
                trial_id=planned.trial_id,
                experiment_id=ref.experiment_id,
                position=position,
                candidate=candidate,
                validity=validity,
                eligible=why is None,
                excluded_because=why,
                verdict=run.oracle.verdict.value if run is not None else None,
                signatures=found,
                faults_delivered=run.target_observed.faults_delivered if run is not None else 0,
                repeated_candidate=candidate in seen if candidate is not None else False,
                state_agrees=state_agrees(run) if run is not None else None,
            )
        )
        if candidate is not None:
            seen.add(candidate)
    rejected = sum(
        1 for p in report.proposals if p.status is ProposalStatus.REJECTED_BEFORE_EXECUTION
    )
    usage = report.usage
    rss = payload.get("ollama_rss_kb")
    wall = payload.get("wall_ms")
    return TrialRow(
        trial_id=planned.trial_id,
        stage=planned.stage,
        unit_id=planned.unit_id,
        world=unit.world_type,
        strategy=planned.strategy,
        seed=planned.seed,
        state=report.state.value,
        termination=report.termination,
        attempted=len(rows) + rejected,
        rejected=rejected,
        executed=len(rows),
        eligible=sum(r.eligible for r in rows),
        undelivered=sum(r.excluded_because == "undelivered_fault" for r in rows),
        distinct_eligible=sorted(distinct_eligible),
        distinct_any=sorted(distinct_any),
        verified_violation_runs=violations,
        first_violation_position=first_position,
        first_violation_ms=first_ms,
        model_calls=usage.model_calls,
        prompt_tokens=usage.investigator_prompt_tokens,
        completion_tokens=usage.investigator_completion_tokens,
        model_latency_ms=usage.investigator_latency_ms,
        tool_calls=tool_calls,
        wall_ms=wall if isinstance(wall, int) else usage.wall_ms,
        sandbox_ms=usage.sandbox_ms,
        ollama_rss_kb=rss if isinstance(rss, int) else None,
        evidence_complete=not problems,
        problems=problems,
        quality=audit(report) if planned.strategy is StrategyName.ADAPTIVE else None,
        experiments=rows,
    )


def trial_rows(spec: Spec, root: Path, stages: Iterable[Stage]) -> tuple[list[TrialRow], list[str]]:
    """Every journaled trial of these stages, and the planned ones with no record."""
    journal = Journal(journal_path(root, spec))
    registered = journal.payloads("registered")
    if not registered or registered[0]["spec_sha256"] != spec_sha(spec):
        raise RuntimeError("this journal does not belong to this specification")
    payloads = {str(p["trial_id"]): p for p in journal.payloads("bench_trial")}
    conditions = {candidate_condition(c): c.key for c in spec.candidates}
    wanted = set(stages)
    rows: list[TrialRow] = []
    missing: list[str] = []
    for planned in expand_plan(spec):
        if planned.stage not in wanted:
            continue
        payload = payloads.get(planned.trial_id)
        if payload is None:
            missing.append(planned.trial_id)
        else:
            rows.append(_trial_row(spec, planned, payload, root, conditions))
    return rows, missing


def _unit_means(rows: Sequence[TrialRow], strategy: StrategyName) -> dict[str, float]:
    """Seeds are averaged inside a unit first, because they are not independent of each other."""
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.strategy is strategy and row.primary is not None:
            grouped[row.unit_id].append(row.primary)
    return {unit: mean(values) for unit, values in grouped.items()}


def _attempted_means(rows: Sequence[TrialRow], strategy: StrategyName) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row.per_attempted()
        if row.strategy is strategy and value is not None:
            grouped[row.unit_id].append(value)
    return {unit: mean(values) for unit, values in grouped.items()}


class Comparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline: str
    units: int
    mean_adaptive: float
    mean_baseline: float
    mean_difference: float
    attempted_difference: float  # the same comparison per 10 attempted (revision 2)
    wins: int
    losses: int
    ties: int
    win_share_interval: tuple[float, float] | None


def compare(rows: Sequence[TrialRow], baseline: StrategyName) -> Comparison:
    adaptive = _unit_means(rows, StrategyName.ADAPTIVE)
    other = _unit_means(rows, baseline)
    shared = sorted(set(adaptive) & set(other))
    differences = [adaptive[u] - other[u] for u in shared]
    wins = sum(d > 1e-9 for d in differences)
    losses = sum(d < -1e-9 for d in differences)
    mine, theirs = _attempted_means(rows, StrategyName.ADAPTIVE), _attempted_means(rows, baseline)
    both = sorted(set(mine) & set(theirs))
    return Comparison(
        baseline=baseline.value,
        units=len(shared),
        mean_adaptive=round(mean(adaptive[u] for u in shared), 4) if shared else 0.0,
        mean_baseline=round(mean(other[u] for u in shared), 4) if shared else 0.0,
        mean_difference=round(mean(differences), 4) if shared else 0.0,
        attempted_difference=round(mean(mine[u] - theirs[u] for u in both), 4) if both else 0.0,
        wins=wins,
        losses=losses,
        ties=len(shared) - wins - losses,
        win_share_interval=clopper_pearson(wins, wins + losses),
    )


class Gates(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_complete: bool
    adaptive_eligible_share: float
    incorrect_finding_rate: float | None


def decide(comparisons: Sequence[Comparison], gates: Gates, spec: Spec) -> tuple[str, list[str]]:
    """The registered rule. It reads only the comparisons and the gates."""
    t = spec.thresholds
    reasons: list[str] = []
    if not gates.plan_complete:
        reasons.append("not every planned main trial has a record")
    if gates.adaptive_eligible_share < t.min_eligible_share:
        reasons.append(
            f"adaptive eligible share {gates.adaptive_eligible_share:.2f} is below "
            f"{t.min_eligible_share}"
        )
    for c in comparisons:
        if c.wins + c.losses < t.min_nontied_units:
            reasons.append(
                f"against {c.baseline}: {c.wins + c.losses} units differ; "
                f"{t.min_nontied_units} are needed"
            )
    if reasons:
        return INCONCLUSIVE, reasons

    margin = t.min_mean_difference_per_10

    def ahead(c: Comparison) -> bool:
        """Eligibility shrinks a denominator, so the attempted rate has to agree (revision 2)."""
        i = c.win_share_interval
        return (
            c.mean_difference >= margin
            and c.attempted_difference >= margin
            and i is not None
            and i[0] > 0.5
        )

    def behind(c: Comparison) -> bool:
        i = c.win_share_interval
        return (
            c.mean_difference <= -margin
            and c.attempted_difference <= -margin
            and i is not None
            and i[1] < 0.5
        )

    if all(ahead(c) for c in comparisons):
        rate = gates.incorrect_finding_rate
        if rate is not None and rate > t.max_incorrect_finding_rate:
            return NO_ADVANTAGE, [f"incorrect finding rate {rate:.2f} is above the registered cap"]
        return ADVANTAGE, ["ahead of both baselines by the margin, with the win share above half"]
    if any(behind(c) for c in comparisons):
        return BASELINE_ADVANTAGE, [
            f"behind {c.baseline} by the margin" for c in comparisons if behind(c)
        ]
    return NO_ADVANTAGE, ["the registered margin and win share were not both met"]


class StrategyRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str
    investigations: int
    attempted: int
    rejected: int
    executed: int
    eligible: int
    excluded: dict[str, int]
    per_10_eligible: float | None
    per_10_attempted: float | None
    per_10_budget: float | None
    verified_violation_runs: int
    distinct_found_per_investigation: float | None
    distinct_signatures_overall: list[str]
    median_first_violation_position: float | None
    median_first_violation_ms: float | None
    investigations_with_a_violation: int
    invalid_rate: float | None
    undelivered_rate: float | None
    repeated_candidate_rate: float | None
    model_calls: int
    tool_calls: int
    prompt_tokens: int
    completion_tokens: int
    model_seconds: float
    wall_seconds: float
    sandbox_seconds: float
    evidence_complete: int
    peak_ollama_rss_mb_sampled: float | None
    model_seconds_per_distinct: float | None


def _mean_of_units(values: dict[str, list[float]]) -> float | None:
    means = [mean(v) for v in values.values() if v]
    return round(mean(means), 4) if means else None


def strategy_row(rows: Sequence[TrialRow], strategy: StrategyName, budget: int) -> StrategyRow:
    mine = [r for r in rows if r.strategy is strategy]
    experiments = [e for r in mine for e in r.experiments]
    by_unit: dict[str, list[float]] = defaultdict(list)
    attempted: dict[str, list[float]] = defaultdict(list)
    slots: dict[str, list[float]] = defaultdict(list)
    found: dict[str, list[float]] = defaultdict(list)
    for r in mine:
        if r.primary is not None:
            by_unit[r.unit_id].append(r.primary)
        value = r.per_attempted()
        if value is not None:
            attempted[r.unit_id].append(value)
        slots[r.unit_id].append(10 * len(r.distinct_eligible) / budget)
        found[r.unit_id].append(float(len(r.distinct_eligible)))
    positions = [r.first_violation_position for r in mine if r.first_violation_position]
    times = [r.first_violation_ms for r in mine if r.first_violation_ms is not None]
    total_attempted = sum(r.attempted for r in mine)
    executed = sum(r.executed for r in mine)
    rss = [r.ollama_rss_kb for r in mine if r.ollama_rss_kb is not None]
    model_seconds = sum(r.model_latency_ms for r in mine) / 1000
    distinct_total = sum(len(r.distinct_eligible) for r in mine)
    return StrategyRow(
        strategy=strategy.value,
        investigations=len(mine),
        attempted=total_attempted,
        rejected=sum(r.rejected for r in mine),
        executed=executed,
        eligible=sum(r.eligible for r in mine),
        excluded=dict(Counter(e.excluded_because for e in experiments if e.excluded_because)),
        per_10_eligible=_mean_of_units(by_unit),
        per_10_attempted=_mean_of_units(attempted),
        per_10_budget=_mean_of_units(slots),
        verified_violation_runs=sum(r.verified_violation_runs for r in mine),
        distinct_found_per_investigation=_mean_of_units(found),
        distinct_signatures_overall=sorted({s for r in mine for s in r.distinct_eligible}),
        median_first_violation_position=median(positions) if positions else None,
        median_first_violation_ms=median(times) if times else None,
        investigations_with_a_violation=sum(bool(r.distinct_eligible) for r in mine),
        invalid_rate=round(sum(r.rejected for r in mine) / total_attempted, 4)
        if total_attempted
        else None,
        undelivered_rate=round(sum(r.undelivered for r in mine) / executed, 4)
        if executed
        else None,
        repeated_candidate_rate=round(sum(e.repeated_candidate for e in experiments) / executed, 4)
        if executed
        else None,
        model_calls=sum(r.model_calls for r in mine),
        tool_calls=sum(r.tool_calls for r in mine),
        prompt_tokens=sum(r.prompt_tokens for r in mine),
        completion_tokens=sum(r.completion_tokens for r in mine),
        model_seconds=round(model_seconds, 1),
        wall_seconds=round(sum(r.wall_ms for r in mine) / 1000, 1),
        sandbox_seconds=round(sum(r.sandbox_ms for r in mine) / 1000, 1),
        evidence_complete=sum(r.evidence_complete for r in mine),
        peak_ollama_rss_mb_sampled=round(max(rss) / 1024, 1) if rss else None,
        model_seconds_per_distinct=round(model_seconds / distinct_total, 1)
        if distinct_total and model_seconds
        else None,
    )


class QualitySummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    investigations: int
    defects: dict[str, int]
    statements: int
    incorrect_statements: int
    incorrect_finding_rate: float | None
    hypotheses: int
    repeated_hypotheses: int
    duplicate_hypothesis_rate: float | None
    rejected_by_reason: dict[str, int]


def quality_summary(rows: Sequence[TrialRow]) -> QualitySummary:
    audits = [r.quality for r in rows if r.quality is not None]
    defects: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    for a in audits:
        defects.update(a.defects)
        rejected.update(p.reason for p in a.rejected_proposals)
    statements = sum(a.statements for a in audits)
    incorrect = sum(a.incorrect_statements for a in audits)
    hypotheses = sum(a.hypotheses for a in audits)
    repeated = sum(a.repeated_hypotheses for a in audits)
    return QualitySummary(
        investigations=len(audits),
        defects=dict(sorted(defects.items())),
        statements=statements,
        incorrect_statements=incorrect,
        incorrect_finding_rate=round(incorrect / statements, 4) if statements else None,
        hypotheses=hypotheses,
        repeated_hypotheses=repeated,
        duplicate_hypothesis_rate=round(repeated / hypotheses, 4) if hypotheses else None,
        rejected_by_reason=dict(sorted(rejected.items())),
    )


@dataclass(frozen=True, slots=True)
class UnitTruth:
    """What every candidate did for a unit, from the sweep. No strategy ever sees it."""

    signatures_by_candidate: dict[str, frozenset[str]]

    @property
    def reachable(self) -> set[str]:
        return {s for found in self.signatures_by_candidate.values() for s in found}

    def expected_random(self, budget: int) -> float:
        """Exact mean distinct signatures over every subset of ``budget`` candidates."""
        sets = list(self.signatures_by_candidate.values())
        chosen = list(combinations(sets, budget))
        return mean(len({s for found in c for s in found}) for c in chosen) if chosen else 0.0


def truth_by_unit(sweep: Sequence[TrialRow]) -> dict[str, UnitTruth]:
    grouped: dict[str, dict[str, frozenset[str]]] = defaultdict(dict)
    for row in sweep:
        for e in row.experiments:
            if e.candidate is not None:
                grouped[row.unit_id][e.candidate] = (
                    frozenset(e.signatures) if e.eligible else frozenset()
                )
    return {unit: UnitTruth(found) for unit, found in grouped.items()}


class UnitResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    reachable: list[str]
    fixed: float | None
    random: float | None
    adaptive: float | None
    found_fixed: float | None
    found_random: float | None
    found_adaptive: float | None
    expected_random_found: float | None


def unit_results(
    units: Sequence[Unit], rows: Sequence[TrialRow], truth: dict[str, UnitTruth], budget: int
) -> list[UnitResult]:
    means = {s: _unit_means(rows, s) for s in StrategyName}

    def found(unit: str, strategy: StrategyName) -> float | None:
        values = [
            len(r.distinct_eligible) for r in rows if r.unit_id == unit and r.strategy is strategy
        ]
        return round(mean(values), 3) if values else None

    out: list[UnitResult] = []
    for unit in units:
        t = truth.get(unit.unit_id)
        out.append(
            UnitResult(
                unit_id=unit.unit_id,
                reachable=sorted(t.reachable) if t is not None else [],
                fixed=_round(means[StrategyName.FIXED].get(unit.unit_id)),
                random=_round(means[StrategyName.RANDOM].get(unit.unit_id)),
                adaptive=_round(means[StrategyName.ADAPTIVE].get(unit.unit_id)),
                found_fixed=found(unit.unit_id, StrategyName.FIXED),
                found_random=found(unit.unit_id, StrategyName.RANDOM),
                found_adaptive=found(unit.unit_id, StrategyName.ADAPTIVE),
                expected_random_found=round(t.expected_random(budget), 3)
                if t is not None
                else None,
            )
        )
    return out


def _round(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


class ReproductionRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    signature: str
    candidate: str
    original_experiment: str
    reproduction_experiment: str | None
    control_experiment: str | None
    reproduction: str
    contrast: str


def contrast_of(
    original: TargetRunEvidence, control: ExperimentEvidence | None, world: str, signature: str
) -> str:
    """What a run of the same world without the fault says. Never more than an association."""
    if not original.authorized.faults:
        return "no_fault_in_original"
    if control is None or not control.target_runs:
        return "not_attempted"
    run = control.target_runs[0]
    if signature in signatures(world, run):
        return "also_occurs_without_fault"
    if run.oracle.verdict is Verdict.VIOLATION:
        return "different_violation_without_fault"
    return "absent_without_fault"


def reproduction_row(
    *,
    unit: Unit,
    signature: str,
    candidate: str,
    root: Path,
    original_id: str,
    repro_id: str | None,
    control_id: str | None,
) -> ReproductionRow:
    original = load_evidence(root, original_id)
    run = original.target_runs[0]
    status = ReproductionStatus.UNTESTED.value
    if repro_id is not None:
        status = reproduction_status(run, load_evidence(root, repro_id)).value
    control = load_evidence(root, control_id) if control_id is not None else None
    return ReproductionRow(
        unit_id=unit.unit_id,
        signature=signature,
        candidate=candidate,
        original_experiment=original_id,
        reproduction_experiment=repro_id,
        control_experiment=control_id,
        reproduction=status,
        contrast=contrast_of(run, control, unit.world_type, signature),
    )


class Results(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark_id: str
    revision: int
    spec_sha256: str
    conclusion: str
    conclusion_reasons: list[str]
    planned_main: int
    recorded_main: int
    missing_main: list[str]
    gates: Gates
    strategies: list[StrategyRow]
    by_world: dict[str, list[StrategyRow]]
    comparisons: list[Comparison]
    units: list[UnitResult]
    quality: QualitySummary
    oracle_state_disagreements: int
    sweep_trials: int
    reproduction: list[ReproductionRow]


def build_results(spec: Spec, root: Path) -> tuple[Results, list[TrialRow]]:
    rows, missing = trial_rows(spec, root, [Stage.MAIN])
    sweep, _ = trial_rows(spec, root, [Stage.SWEEP])
    truth = truth_by_unit(sweep)
    adaptive = [r for r in rows if r.strategy is StrategyName.ADAPTIVE]
    attempted = sum(r.attempted for r in adaptive)
    summary = quality_summary(rows)
    gates = Gates(
        plan_complete=not missing,
        adaptive_eligible_share=round(sum(r.eligible for r in adaptive) / attempted, 4)
        if attempted
        else 0.0,
        incorrect_finding_rate=summary.incorrect_finding_rate,
    )
    comparisons = [compare(rows, StrategyName.FIXED), compare(rows, StrategyName.RANDOM)]
    conclusion, reasons = decide(comparisons, gates, spec)
    journal = Journal(journal_path(root, spec))
    reproduction = [ReproductionRow.model_validate(p) for p in journal.payloads("reproduction")]
    disagreements = sum(e.state_agrees is False for r in [*rows, *sweep] for e in r.experiments)
    worlds = sorted({u.world_type for u in spec.units})
    results = Results(
        benchmark_id=spec.benchmark_id,
        revision=spec.revision,
        spec_sha256=spec_sha(spec),
        conclusion=conclusion,
        conclusion_reasons=reasons,
        planned_main=len(rows) + len(missing),
        recorded_main=len(rows),
        missing_main=missing,
        gates=gates,
        strategies=[strategy_row(rows, s, spec.budget) for s in StrategyName],
        by_world={
            w: [
                strategy_row([r for r in rows if r.world == w], s, spec.budget)
                for s in StrategyName
            ]
            for w in worlds
        },
        comparisons=comparisons,
        units=unit_results(spec.units, rows, truth, spec.budget),
        quality=summary,
        oracle_state_disagreements=disagreements,
        sweep_trials=len(sweep),
        reproduction=reproduction,
    )
    return results, rows


def dumps(results: Results) -> str:
    return json.dumps(results.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"
