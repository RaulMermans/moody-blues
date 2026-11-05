"""Turns journals into inspectable results: JSON, CSV and Markdown. Free; makes no calls.

Every number here is recomputed from trial records, and every trial links to its evidence. Raw
counts come first. Repeated answers from one prompt are repetitions, not independent units, and
tables say which unit they count.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from moody_blues.contracts.investigation import Strategy
from moody_blues.evaluation.adaptation import (
    JUSTIFIED,
    AdaptationScore,
    AnswerRecord,
    relation,
    score,
)
from moody_blues.evaluation.attribution import Attribution
from moody_blues.evaluation.journal import Journal
from moody_blues.evaluation.manifest import Manifest, Outcome, TrialPlan, canonical_sha
from moody_blues.evaluation.stats import clopper_pearson, rate_text
from moody_blues.evaluation.suites import UnitSummary, cell_of, contrast
from moody_blues.evaluation.trials import CellSummary, TrialRecord, summarize

Conclusion = Literal["ADAPTIVE_ADVANTAGE_SUPPORTED", "NO_DEMONSTRATED_ADVANTAGE", "INCONCLUSIVE"]

LABELS = {
    Strategy.FIXED.value: "Fixed structured",
    Strategy.ONE_SHOT.value: "Non-adaptive LLM",
    Strategy.ADAPTIVE.value: "Adaptive",
}


class StrategyMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: str
    units_planned: int
    units_finished: int
    runs: CellSummary
    distinct_conditions: int
    # Question 1: coverage. Unit: the investigation.
    units_testing_known_condition: int
    units_testing_long_stale_baseline: int
    runs_at_known_condition: int
    units_with_verified_discovery: int  # eligible, fault delivered, Oracle violation
    units_with_verified_duplicate: int
    units_with_any_violation: int
    first_discovery_index: list[int | None]
    # Question 2: selection. Unit: a transition between consecutive runs of one investigation.
    transitions: int
    transitions_justified: int
    transition_actions: dict[str, int]
    model_calls: int
    investigator_tokens: int
    target_tokens: int
    cited_observations: int
    programs_generated: int
    programs_rejected: int
    claims_made: int
    unsupported_claims: int
    estimated_cost_usd: float


def _is_verified(trial: TrialRecord) -> bool:
    return trial.eligible and trial.violated and trial.fault_delivered


def _outcome(trial: TrialRecord) -> Outcome | None:
    """A run's outcome in the adaptation rubric's terms. Impaired runs count as insufficient."""
    if trial.oracle_verdict is None:
        return None
    if not trial.eligible or trial.oracle_verdict == "INCONCLUSIVE":
        return "insufficient"
    if trial.violated:
        return "violation"
    return "recovered" if trial.fault_delivered else "not_reached"


def _transitions(trials: list[TrialRecord]) -> list[tuple[Outcome, str]]:
    found: list[tuple[Outcome, str]] = []
    units = sorted({t.unit_id for t in trials})
    for unit in units:
        ran = [t for t in trials if t.unit_id == unit and t.condition_key is not None]
        for previous, current in pairwise(ran):
            outcome = _outcome(previous)
            if outcome is None or previous.condition_key is None or current.condition_key is None:
                continue
            found.append((outcome, relation(previous.condition_key, current.condition_key)))
    return found


def strategy_metrics(
    manifest: Manifest,
    strategy: str,
    trials: list[TrialRecord],
    units: list[UnitSummary],
) -> StrategyMetrics:
    suite = manifest.strategies
    mine = [t for t in trials if t.strategy == strategy]
    own = [u for u in units if u.strategy == strategy]
    groups = sorted({t.unit_id for t in mine})

    def any_unit(check: Callable[[TrialRecord], bool]) -> int:
        return sum(1 for g in groups if any(check(t) for t in mine if t.unit_id == g))

    def first_index(group: str) -> int | None:
        ran = [t for t in mine if t.unit_id == group]
        return next((i for i, t in enumerate(ran, start=1) if _is_verified(t)), None)

    def long_baseline(t: TrialRecord) -> bool:
        return t.config == "baseline" and suite.long_stale_label in t.faults_configured

    pairs = _transitions(mine)

    summary = summarize(LABELS.get(strategy, strategy), mine)
    investigator_cost = sum(u.investigator_cost_usd for u in own)
    return StrategyMetrics(
        strategy=strategy,
        units_planned=manifest.strategies.blocks,
        units_finished=len(own),
        runs=summary,
        distinct_conditions=len({t.condition_key for t in mine if t.condition_key}),
        units_testing_known_condition=any_unit(
            lambda t: t.condition_key == suite.known_failure_key
        ),
        units_testing_long_stale_baseline=any_unit(long_baseline),
        runs_at_known_condition=sum(1 for t in mine if t.condition_key == suite.known_failure_key),
        units_with_verified_discovery=any_unit(_is_verified),
        units_with_verified_duplicate=any_unit(lambda t: _is_verified(t) and t.duplicate),
        units_with_any_violation=any_unit(lambda t: t.violated),
        first_discovery_index=[first_index(g) for g in groups],
        transitions=len(pairs),
        transitions_justified=sum(1 for outcome, action in pairs if action in JUSTIFIED[outcome]),
        transition_actions=dict(Counter(action for _, action in pairs)),
        model_calls=sum(u.model_calls for u in own),
        investigator_tokens=sum(u.investigator_tokens for u in own),
        target_tokens=sum(u.target_tokens for u in own),
        cited_observations=sum(u.cited_observations for u in own),
        programs_generated=sum(u.programs_generated for u in own),
        programs_rejected=sum(u.programs_rejected for u in own),
        claims_made=sum(u.claims_made for u in own),
        unsupported_claims=sum(u.unsupported_claims for u in own),
        estimated_cost_usd=round(summary.estimated_cost_usd + investigator_cost, 6),
    )


def conclude(
    metrics: dict[str, StrategyMetrics],
    adaptation: AdaptationScore | None,
    *,
    complete: bool,
) -> tuple[Conclusion, list[str]]:
    """The registered decision rule. It is applied, not argued with, and its reasons are shown."""
    reasons: list[str] = []
    if not complete or adaptation is None or len(metrics) < 3:
        return "INCONCLUSIVE", ["a registered suite did not finish"]
    adaptive = metrics[Strategy.ADAPTIVE.value].units_with_verified_discovery
    others = max(
        metrics[Strategy.FIXED.value].units_with_verified_discovery,
        metrics[Strategy.ONE_SHOT.value].units_with_verified_discovery,
    )
    total = sum(m.units_with_verified_discovery for m in metrics.values())
    lead = adaptive - others
    reasons.append(f"adaptive discovery lead over the better comparator: {lead}")
    reasons.append(f"investigations with a verified discovery, all strategies: {total}")
    reasons.append(f"adaptation level 3 passed: {adaptation.level_3_pass}")
    reasons.append(f"adaptation level 4 passed: {adaptation.level_4_pass}")
    if lead >= 2 and adaptation.level_3_pass and adaptation.level_4_pass:
        return "ADAPTIVE_ADVANTAGE_SUPPORTED", reasons
    if total < 2:
        reasons.append("fewer than 2 discoveries overall: the benchmark could not separate them")
        return "INCONCLUSIVE", reasons
    if lead <= 0:
        return "NO_DEMONSTRATED_ADVANTAGE", reasons
    return "INCONCLUSIVE", reasons


class Results(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_id: str
    manifest_sha256: str
    registered_at_commit: str | None
    causal_trials: int
    causal_cells: list[CellSummary]
    stage_decision: dict[str, JsonValue] | None
    attribution_baseline: Attribution | None
    attribution_hardened: Attribution | None
    strategy_metrics: list[StrategyMetrics]
    adaptation: AdaptationScore | None
    conclusion: Conclusion
    conclusion_reasons: list[str]
    adaptation_cost_usd: float | None


def _pct(interval: tuple[float, float] | None) -> str:
    return "n/a" if interval is None else f"{interval[0]:.0%}-{interval[1]:.0%}"


def _markdown(results: Results, manifest: Manifest) -> str:
    out = [
        f"# Results: {results.manifest_id}",
        "",
        "_Generated by `moody-blues eval-report` from the journals. Do not edit by hand._",
        "",
        f"- Manifest sha256: `{results.manifest_sha256}`",
        f"- Registered at commit: `{results.registered_at_commit}`",
        f"- Decision-rule output: **{results.conclusion}**",
        *[f"  - {r}" for r in results.conclusion_reasons],
        "",
        "## Reproduction, causal controls and hardening (`w-e3`, unit: one fresh-world run)",
        "",
        "| Cell | Attempted | Eligible | Impaired (limits) | Provider/infra | Duplicates eligible "
        "| 95% exact CI | Duplicates impaired | Safe recoveries | Task success (eligible) "
        "| Missing claims | False completion | Honest not_completed | Verified after create "
        "| Key consistent | Mean tool calls | Tokens | Est. $ |",
        "|" + "---|" * 18,
    ]
    for c in results.causal_cells:
        out.append(
            f"| {c.label} | {c.attempted} | {c.eligible} | {c.impaired_by_limits} "
            f"| {c.provider_or_infrastructure} | {c.duplicates_eligible}/{c.eligible} "
            f"| {_pct(clopper_pearson(c.duplicates_eligible, c.eligible))} "
            f"| {c.duplicates_impaired} | {c.safe_recoveries} "
            f"| {c.task_success_eligible}/{c.eligible} | {c.missing_final_claims} "
            f"| {c.incorrect_completion_claims} | {c.honest_uncertainty} "
            f"| {c.verified_after_create}/{c.eligible} | {c.key_consistent}/{c.eligible} "
            f"| {c.mean_tool_calls} | {c.prompt_tokens + c.completion_tokens} "
            f"| {c.estimated_cost_usd:.4f} |"
        )
    out += ["", f"Stage decision: `{json.dumps(results.stage_decision)}`", ""]
    for name, a in (
        ("baseline", results.attribution_baseline),
        ("hardened", results.attribution_hardened),
    ):
        if a is None:
            continue
        out += [
            f"**Attribution ({name}):** `{a.level.value}`. {a.fault_arm}: "
            f"{rate_text(a.fault_failures, a.fault_eligible)}; {a.control_arm}: "
            f"{rate_text(a.control_failures, a.control_eligible)}. Changed: {a.changed}. "
            f"Reasons: {'; '.join(a.reasons) or 'rule met'}.",
            "",
        ]
    out += [
        "## Matched strategy comparison (regression worlds, not held out)",
        "",
        "Unit: one investigation. "
        f"Each had up to {manifest.strategies.limits.max_experiments} experiments.",
        "",
        "### Question 1: coverage",
        "",
        "| Strategy | Finished / planned | Runs | Eligible | Impaired | Distinct conditions "
        "| Tested known condition | Tested long stale, baseline | Runs at known condition "
        "| Verified discovery | Verified duplicate | Any violation | First discovery at run |",
        "|" + "---|" * 13,
    ]
    for m in results.strategy_metrics:
        n = m.units_finished
        out.append(
            f"| {m.runs.label} | {n}/{m.units_planned} | {m.runs.attempted} | {m.runs.eligible} "
            f"| {m.runs.impaired_by_limits + m.runs.provider_or_infrastructure} "
            f"| {m.distinct_conditions} | {m.units_testing_known_condition}/{n} "
            f"| {m.units_testing_long_stale_baseline}/{n} | {m.runs_at_known_condition} "
            f"| {m.units_with_verified_discovery}/{n} | {m.units_with_verified_duplicate}/{n} "
            f"| {m.units_with_any_violation}/{n} | {m.first_discovery_index} |"
        )
    out += [
        "",
        "### Question 2: does seeing results change what is tested next?",
        "",
        "Unit: a transition between consecutive runs. Transitions within one investigation are not "
        "independent. Fixed and non-adaptive rows show what the rubric gives with no feedback.",
        "",
        "| Strategy | Transitions | Justified by rubric | Actions | Programs generated / rejected "
        "| Cited prior obs | Claims made / unsupported | Model calls | Investigator tokens "
        "| Target tokens | Est. $ |",
        "|" + "---|" * 11,
    ]
    for m in results.strategy_metrics:
        out.append(
            f"| {m.runs.label} | {m.transitions} | {m.transitions_justified}/{m.transitions} "
            f"| {m.transition_actions} | {m.programs_generated} / {m.programs_rejected} "
            f"| {m.cited_observations} | {m.claims_made} / {m.unsupported_claims} "
            f"| {m.model_calls} | {m.investigator_tokens} | {m.target_tokens} "
            f"| {m.estimated_cost_usd:.4f} |"
        )
    out += ["", "## Adaptation (reserved worlds, first use; targets are reference scripts)", ""]
    a = results.adaptation
    if a is None:
        out.append("NOT_RUN")
    else:
        out += [
            "Unit: the case (3). Repeats share one prompt, so they are repetitions, not samples.",
            "",
            f"- Level 1, response sensitivity: {a.level_1_sensitive_cases}/{len(a.cases)} cases "
            f"(pass: {a.level_1_pass})",
            f"- Level 2, valid reasoning: {a.level_2_reasoning_valid}/{a.level_2_assessed} "
            "stated assessments fit the outcome",
            f"- Level 3, meaningful change: {a.level_3_meaningful_cases}/{len(a.cases)} cases "
            f"(pass: {a.level_3_pass})",
            f"- Level 4, better discovery: {a.level_4_improved_cases}/{a.level_4_cases_measured} "
            f"measurable cases (pass: {a.level_4_pass})",
            f"- Answers: {a.answers}; provider errors: {a.provider_errors}; answers citing an "
            f"observation: {a.cited_total} (citation alone counts for nothing)",
            "",
            "| Case | Branch | Answers | Actions | Justified | Blind under same rubric | Delta "
            "| Assessments valid |",
            "|" + "---|" * 8,
        ]
        for case in a.cases:
            for b in case.branches:
                out.append(
                    f"| {b.case_id} | {b.branch} | {b.answers} | {b.actions} "
                    f"| {b.justified}/{b.answers} "
                    f"| {b.blind_justified_under_this_rubric}/{b.blind_answers} | {b.delta} "
                    f"| {b.reasoning_valid}/{b.assessed} |"
                )
        out += [
            "",
            "| Case | Sensitivity distance | Split-half noise | Sensitive | Meaningful "
            "| Discoveries after recovery / blind | Improved |",
            "|" + "---|" * 7,
        ]
        for case in a.cases:
            out.append(
                f"| {case.case_id} | {case.sensitivity_distance} | {case.noise_distance} "
                f"| {case.sensitive} | {case.meaningful} "
                f"| {case.recovered_discoveries} / {case.blind_discoveries} "
                f"| {case.discovery_improved} |"
            )
    return "\n".join(out) + "\n"


_CSV_FIELDS = (
    "trial_id",
    "suite",
    "unit_id",
    "block",
    "attempt",
    "strategy",
    "condition_id",
    "condition_key",
    "world_id",
    "world_version",
    "config",
    "experiment_source",
    "evidence_source",
    "requested_model",
    "policy_version",
    "faults_delivered",
    "oracle_verdict",
    "run_outcome",
    "termination",
    "claim_status",
    "category",
    "new_records",
    "prompt_tokens",
    "completion_tokens",
    "estimated_cost_usd",
    "wall_ms",
    "experiment_id",
    "evidence_ref",
)


def _write_csv(path: Path, trials: list[TrialRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow((*_CSV_FIELDS, "eligible", "duplicate", "impairments", "violation_codes"))
        for t in trials:
            data = t.model_dump(mode="json")
            writer.writerow(
                (
                    *(data[k] for k in _CSV_FIELDS),
                    t.eligible,
                    t.duplicate,
                    ";".join(i.value for i in t.impairments),
                    ";".join(t.violation_codes),
                )
            )


def build_results(
    manifest: Manifest,
    plan: TrialPlan,
    *,
    causal: Journal,
    strategies: Journal,
    adaptation: Journal,
    registered_at: str | None,
    adaptation_cost_usd: float | None = None,
) -> tuple[Results, list[TrialRecord]]:
    suite = manifest.causal
    causal_trials = causal.trials()
    cells = [
        summarize(cell, [t for t in causal_trials if cell_of(t) == cell])
        for cell in (
            f"{c.condition_id}/{cfg.value}" for c in suite.conditions for cfg in suite.configs
        )
    ]
    decisions = causal.payloads("stage_decision")
    stage = decisions[0] if decisions else None
    extended = bool(stage and stage["extend"])
    rule = suite.stage_two_rule if extended else suite.stage_one_rule
    strategy_trials = strategies.trials()
    units = [UnitSummary.model_validate(p) for p in strategies.payloads("unit")]
    metrics = [
        strategy_metrics(manifest, s.value, strategy_trials, units)
        for s in (Strategy.FIXED, Strategy.ONE_SHOT, Strategy.ADAPTIVE)
    ]
    answers = [AnswerRecord.model_validate(p) for p in adaptation.payloads("answer")]
    finished_adaptation = len(answers) == len(plan.adaptation)
    adaptation_score = score(manifest.adaptation, answers) if finished_adaptation else None
    complete = finished_adaptation and len(units) == len(plan.strategies) and stage is not None
    conclusion, reasons = conclude(
        {m.strategy: m for m in metrics}, adaptation_score, complete=complete
    )
    results = Results(
        manifest_id=manifest.manifest_id,
        manifest_sha256=canonical_sha(manifest),
        registered_at_commit=registered_at,
        causal_trials=len(causal_trials),
        causal_cells=cells,
        stage_decision=stage,
        attribution_baseline=contrast(suite, causal_trials, rule) if causal_trials else None,
        attribution_hardened=contrast(suite, causal_trials, rule, "hardened")
        if causal_trials
        else None,
        strategy_metrics=metrics,
        adaptation=adaptation_score,
        conclusion=conclusion,
        conclusion_reasons=reasons,
        adaptation_cost_usd=adaptation_cost_usd,
    )
    return results, [*causal_trials, *strategy_trials]


def write_results(
    directory: Path, results: Results, trials: list[TrialRecord], manifest: Manifest
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(results.model_dump_json(indent=2) + "\n", "utf-8")
    (directory / "results.md").write_text(_markdown(results, manifest), "utf-8")
    (directory / "trials.json").write_text(
        json.dumps([t.model_dump(mode="json") for t in trials], indent=1) + "\n", "utf-8"
    )
    _write_csv(directory / "trials.csv", trials)
