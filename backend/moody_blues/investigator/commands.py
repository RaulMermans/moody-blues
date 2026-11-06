"""Command implementations. ``cli.py`` only wires arguments to these.

Live commands are refused unless explicitly confirmed, unless the free preflight passes, and
unless both configured models appear in the provider's catalog. The Investigator and the Target
Agent reserve from the same ledger under one scope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentBudget
from moody_blues.contracts.common import MoodyBluesError
from moody_blues.contracts.experiment_evidence import (
    ExperimentAuthorship,
    ExperimentEvidence,
    ExperimentSpec,
    ExperimentState,
)
from moody_blues.contracts.investigation import (
    InvestigationLimits,
    InvestigationReport,
    InvestigationRequest,
    Strategy,
    WorldTier,
)
from moody_blues.experiments.budget import (
    ScopedSpend,
    SpendLedger,
    ledger_path,
)
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.target import AgentTarget, ReferenceTarget
from moody_blues.experiments.workspace import EVIDENCE
from moody_blues.explorer.paths import default_artifacts
from moody_blues.inference.vultr import PROVIDER, VultrInferenceClient
from moody_blues.investigator.catalog import WORLD_TIERS, target_capability
from moody_blues.investigator.evaluation import (
    PAIR_CASES,
    StrategyRow,
    hardened_rates,
    render_comparison,
    render_pairs,
    run_pair,
    strategy_row,
    write_json,
)
from moody_blues.investigator.findings import classify_run, impairments_of, reproduction_status
from moody_blues.investigator.fixtures import FIXTURE_MODEL, ObservationDrivenFixture
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.observations import violation_codes
from moody_blues.investigator.preflight import (
    PreflightReport,
    generated_code_runner,
    run_preflight,
    sandbox_limits,
)
from moody_blues.investigator.render import render_report
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow
from moody_blues.investigator.workspace import verify_investigation
from moody_blues.world.crm_plugin import INVESTIGATION_OBJECTIVE

ARTIFACTS = default_artifacts()
EXPERIMENTS = ARTIFACTS / "experiments"
INVESTIGATIONS = ARTIFACTS / "investigations"
EVALUATIONS = ARTIFACTS / "investigator-eval"

DEFAULT_OBJECTIVE = INVESTIGATION_OBJECTIVE
# The per-step cap includes hidden reasoning. At the default 1,024 the agent was cut off exactly
# when a hard world made it think (KI-29), which would have been degrading the target.
LIVE_TARGET_BUDGET = AgentBudget(
    max_steps=10,
    max_tool_calls=16,
    max_total_tokens=30_000,
    max_completion_tokens=4_096,
    max_wall_seconds=180,
)
MAX_EVAL_TRIALS = 3
MAX_REPRO_RUNS = 8
# The world each tier's fixed first experiment runs in. Reference executors behave cleanly in it.
PAIR_SEED_WORLDS = {WorldTier.VALIDATION: "w-v1", WorldTier.EVALUATION: "w-e3"}


def preflight(settings: Settings) -> int:
    report = run_preflight(settings)
    INVESTIGATIONS.mkdir(parents=True, exist_ok=True)
    (INVESTIGATIONS / "preflight.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print(report.model_dump_json(indent=2))
    return 0 if report.status == "PASS" else 1


def _gate(settings: Settings) -> PreflightReport | None:
    report = run_preflight(settings)
    if report.status == "PASS":
        return report
    failed = [c.name for c in report.checks if c.status == "FAIL"]
    print(json.dumps({"status": "BLOCKED_BY_LOCAL_DEPENDENCY", "failed_checks": failed}))
    return None


def demo(settings: Settings) -> int:
    """Real Docker, worlds and Oracle. The model is a labeled fixture, the target a script."""
    if _gate(settings) is None:
        return 2
    print("OFFLINE DEMONSTRATION. The Investigator here is a scripted fixture, not a model, and")
    print("the target is a reference executor. Sandboxes, worlds and the Oracle are real.")
    print("The same fixture runs against two targets, so its second step differs by observation.\n")
    runner_sandbox = generated_code_runner(settings)
    limits = InvestigationLimits()
    sequence = [
        [{"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}],
        [{"kind": "phantom_success", "occurrence": 1}],
    ]
    worked = True
    for executor in ("verify_then_report", "blind_retry"):
        request = InvestigationRequest(
            objective=DEFAULT_OBJECTIVE,
            tier=WorldTier.DEVELOPMENT,
            world_ids=("normal-success",),
            investigator_model=FIXTURE_MODEL,
            target_model=f"reference:{executor}",
            limits=limits,
        )
        workflow = InvestigationWorkflow(
            request=request,
            runner=ExperimentRunner(
                sandbox=runner_sandbox,
                target=ReferenceTarget(executor),
                root=EXPERIMENTS,
                sandbox_limits=sandbox_limits(settings),
            ),
            root=INVESTIGATIONS,
            model=InvestigatorModel(
                inference=ObservationDrivenFixture("normal-success", sequence),
                evidence="offline_fixture",
                model=FIXTURE_MODEL,
                provider=None,
                spend=None,
                max_completion_tokens=limits.max_completion_tokens,
                temperature=limits.temperature,
            ),
        )
        report = workflow.run()
        print(f"--- target: reference executor {executor} ---")
        print(render_report(report))
        problems = verify_investigation(INVESTIGATIONS / report.investigation_id, EXPERIMENTS)
        print(f"evidence verification: {problems or 'intact'}\n")
        worked = worked and not problems
    return 0 if worked else 1


@dataclass(frozen=True, slots=True)
class LiveContext:
    ledger: SpendLedger
    client: VultrInferenceClient


def open_live(settings: Settings, *, limit_usd: float | None = None) -> LiveContext | None:
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    if not key:
        print(json.dumps({"status": "BLOCKED_BY_CREDENTIALS"}))
        return None
    if _gate(settings) is None:
        return None
    ledger = SpendLedger.from_settings(
        settings, ledger_path(settings, ARTIFACTS), limit_usd=limit_usd
    )
    try:
        status = ledger.status()  # refuses a corrupt ledger before anything is spent
        client = VultrInferenceClient(
            api_key=key,
            model=settings.investigator_model,
            base_url=settings.vultr_base_url,
            timeout_seconds=settings.investigator_timeout_seconds,
            max_retries=settings.investigator_max_retries,
        )
        catalog = client.list_models()
    except MoodyBluesError as exc:
        print(json.dumps({"status": "BLOCKED_BY_BUDGET", "reason": exc.detail.message[:300]}))
        return None
    missing = {settings.investigator_model, settings.investigator_target_model} - set(catalog)
    if missing:
        print(json.dumps({"status": "BLOCKED", "models_not_in_catalog": sorted(missing)}))
        return None
    print(f"ledger before: ${status.settled_usd:.4f} of ${status.limit_usd:.2f} (estimate)")
    return LiveContext(ledger, client)


def target_client(settings: Settings, key: str) -> VultrInferenceClient:
    return VultrInferenceClient(
        api_key=key,
        model=settings.investigator_target_model,
        base_url=settings.vultr_base_url,
        timeout_seconds=settings.investigator_timeout_seconds,
        max_retries=settings.investigator_max_retries,
    )


def live_workflow(
    settings: Settings,
    live: LiveContext,
    *,
    strategy: Strategy,
    tier: WorldTier,
    worlds: tuple[str, ...],
    limits: InvestigationLimits,
    investigation_id: str | None = None,
    cancel: Event | None = None,
    artifacts: Path = ARTIFACTS,
) -> InvestigationWorkflow:
    investigation_id = investigation_id or f"inv_{uuid4().hex[:12]}"
    spend = ScopedSpend(live.ledger, investigation_id, settings.investigator_max_spend_usd)
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    target = AgentTarget(
        inference=target_client(settings, key),
        evidence="live_provider",
        provider=PROVIDER,
        model=settings.investigator_target_model,
        budget=LIVE_TARGET_BUDGET,
        ledger=spend,
    )
    model = InvestigatorModel(
        inference=live.client,
        evidence="live_provider",
        model=settings.investigator_model,
        provider=PROVIDER,
        spend=spend,
        max_completion_tokens=limits.max_completion_tokens,
        temperature=limits.temperature,
        provider_attempts=settings.investigator_max_retries + 1,
        reasoning_effort=limits.reasoning_effort,
    )
    return InvestigationWorkflow(
        request=InvestigationRequest(
            objective=DEFAULT_OBJECTIVE,
            strategy=strategy,
            tier=tier,
            world_ids=worlds,
            investigator_model=settings.investigator_model,
            target_model=settings.investigator_target_model,
            limits=limits,
        ),
        runner=ExperimentRunner(
            sandbox=generated_code_runner(settings),
            target=target,
            root=artifacts / "experiments",
            sandbox_limits=sandbox_limits(settings),
        ),
        root=artifacts / "investigations",
        model=None if strategy is Strategy.FIXED else model,
        spend=spend,
        investigation_id=investigation_id,
        cancel=cancel,
    )


def not_confirmed(command: str) -> int:
    print(
        json.dumps(
            {
                "status": "NOT_RUN",
                "reason": f"{command} is billable; pass --confirm-billable "
                f"(make {command} CONFIRM=1)",
            }
        )
    )
    return 2


def _finish_live(live: LiveContext, reports: list[InvestigationReport]) -> int:
    status = live.ledger.status()
    print(
        f"ledger after: ${status.settled_usd:.4f} settled, ${status.remaining_usd:.4f} of "
        f"${status.limit_usd:.2f} left. Estimate at assumed ceiling prices; confirm in the "
        "Vultr console."
    )
    return 3 if any(r.state.value == "budget_exhausted" for r in reports) else 0


def investigate_live(
    settings: Settings, *, confirmed: bool, tier: WorldTier, strategy: Strategy
) -> int:
    if not confirmed:
        return not_confirmed("investigator-live")
    live = open_live(settings)
    if live is None:
        return 2
    workflow = live_workflow(
        settings,
        live,
        strategy=strategy,
        tier=tier,
        worlds=WORLD_TIERS[tier],
        limits=InvestigationLimits(),
    )
    report = workflow.run()
    print(render_report(report))
    directory = INVESTIGATIONS / report.investigation_id
    print(f"evidence verification: {verify_investigation(directory, EXPERIMENTS) or 'intact'}")
    print(f"record: {directory}")
    return _finish_live(live, [report])


def evaluate(
    settings: Settings,
    *,
    confirmed: bool,
    tier: WorldTier,
    trials: int,
    pairs: bool,
    compare: bool,
    repeats: int = 2,
) -> int:
    if not confirmed:
        return not_confirmed("investigator-eval")
    if not 1 <= trials <= MAX_EVAL_TRIALS:
        print(json.dumps({"status": "NOT_RUN", "reason": f"trials must be 1-{MAX_EVAL_TRIALS}"}))
        return 2
    live = open_live(settings)
    if live is None:
        return 2
    limits = InvestigationLimits()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = EVALUATIONS / stamp
    directory.mkdir(parents=True, exist_ok=True)
    reports: list[InvestigationReport] = []
    if pairs:
        reports_text = _evaluate_pairs(settings, live, limits, directory, tier, repeats)
        print(reports_text)
    if compare:
        rows: list[StrategyRow] = []
        for trial in range(1, trials + 1):
            for strategy in (Strategy.FIXED, Strategy.ONE_SHOT, Strategy.ADAPTIVE):
                report = live_workflow(
                    settings,
                    live,
                    strategy=strategy,
                    tier=tier,
                    worlds=WORLD_TIERS[tier],
                    limits=limits,
                ).run()
                reports.append(report)
                rows.append(strategy_row(report, trial))
                print(f"trial {trial} {strategy.value}: {report.state.value}: {report.statement}")
        table = render_comparison(rows)
        write_json(directory / "comparison.json", [r.model_dump(mode="json") for r in rows])
        (directory / "comparison.md").write_text(table, encoding="utf-8")
        print(table)
    print(f"record: {directory}")
    return _finish_live(live, reports)


def reproduce(
    settings: Settings,
    *,
    confirmed: bool,
    experiment_id: str,
    runs: int,
    budget: AgentBudget = LIVE_TARGET_BUDGET,
    limit_usd: float | None = None,
) -> int:
    """Rerun one generated program unchanged in fresh worlds, to estimate how often it recurs."""
    if not confirmed:
        return not_confirmed("investigator-repro")
    if not 1 <= runs <= MAX_REPRO_RUNS:
        print(json.dumps({"status": "NOT_RUN", "reason": f"runs must be 1-{MAX_REPRO_RUNS}"}))
        return 2
    directory = EXPERIMENTS / experiment_id
    original = ExperimentEvidence.model_validate_json(
        (directory / EVIDENCE).read_text(encoding="utf-8")
    )
    if original.generation is None or original.source_path is None or not original.target_runs:
        print(json.dumps({"status": "NOT_RUN", "reason": "not a generated experiment with a run"}))
        return 2
    if verify_experiment(directory):
        print(json.dumps({"status": "NOT_RUN", "reason": "original evidence does not verify"}))
        return 2
    live = open_live(settings, limit_usd=limit_usd)
    if live is None:
        return 2
    code = (directory / original.source_path).read_text(encoding="utf-8")
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    scope = f"repro_{experiment_id}_{uuid4().hex[:6]}"
    spend = ScopedSpend(live.ledger, scope, settings.investigator_max_spend_usd)
    runner = ExperimentRunner(
        sandbox=generated_code_runner(settings),
        target=AgentTarget(
            inference=target_client(settings, key),
            evidence="live_provider",
            provider=PROVIDER,
            model=settings.investigator_target_model,
            budget=budget,
            ledger=spend,
        ),
        root=EXPERIMENTS,
        sandbox_limits=sandbox_limits(settings),
    )
    first = original.target_runs[0]
    rows: list[dict[str, object]] = []
    for index in range(1, runs + 1):
        evidence = runner.run(
            ExperimentSpec(
                label=f"repro-rate-{index}",
                code=code,
                parent_investigation_id=scope[:64],
                authorship=ExperimentAuthorship.MODEL_GENERATED,
                generation=original.generation,
                reproduction_of=experiment_id,
            ),
            worlds=(first.authorized.scenario_id,),
            max_runtime_seconds=300.0,
            cancel=None,
        )
        status = reproduction_status(first, evidence)
        run = evidence.target_runs[0] if evidence.target_runs else None
        row: dict[str, object] = {
            "run": index,
            "experiment_id": evidence.experiment_id,
            "status": evidence.status.value,
            "reproduction": status.value,
            "finding_class": classify_run(run, evidence_intact=True).value if run else None,
            "verdict": run.oracle.verdict.value if run else None,
            "run_outcome": run.run_outcome if run else None,
            "violation_codes": violation_codes(run) if run else [],
            "new_records": len(run.committed.new_ids) if run else None,
            "claim": run.target_observed.claim.status.value
            if run and run.target_observed.claim
            else None,
            "truncated_model_steps": run.truncated_model_steps if run else None,
            "impairments": [i.value for i in impairments_of(run, evidence_intact=True)]
            if run
            else None,
            "tokens": run.tokens.total_tokens if run and run.tokens else None,
        }
        rows.append(row)
        print(json.dumps(row))
        if evidence.status is ExperimentState.BUDGET_EXHAUSTED:
            break
    out = EVALUATIONS / f"repro-{experiment_id}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    EVALUATIONS.mkdir(parents=True, exist_ok=True)
    write_json(out, rows)
    print(f"record: {out}")
    return _finish_live(live, [])


def _evaluate_pairs(
    settings: Settings,
    live: LiveContext,
    limits: InvestigationLimits,
    directory: Path,
    tier: WorldTier,
    repeats: int,
) -> str:
    worlds = WORLD_TIERS[tier]
    seed_world = PAIR_SEED_WORLDS[tier]
    scope = f"pairs_{directory.name}"
    spend = ScopedSpend(live.ledger, scope, settings.investigator_max_spend_usd)
    model = InvestigatorModel(
        inference=live.client,
        evidence="live_provider",
        model=settings.investigator_model,
        provider=PROVIDER,
        spend=spend,
        max_completion_tokens=limits.max_completion_tokens,
        temperature=limits.temperature,
        provider_attempts=settings.investigator_max_retries + 1,
        reasoning_effort=limits.reasoning_effort,
    )

    def runner_for(executor: str) -> ExperimentRunner:
        return ExperimentRunner(
            sandbox=generated_code_runner(settings),
            target=ReferenceTarget(executor),
            root=EXPERIMENTS,
            sandbox_limits=sandbox_limits(settings),
        )

    results = [
        run_pair(
            replace(case, world=seed_world),
            model=model,
            runner_for=runner_for,
            capability=target_capability(worlds),
            worlds=worlds,
            objective=DEFAULT_OBJECTIVE,
            limits=limits,
            artifacts=directory / "pairs" / case.case_id,
            repeats=repeats,
        )
        for case in PAIR_CASES
    ]
    write_json(directory / "pairs.json", [r.model_dump(mode="json") for r in results])
    after_pass, n_pass, after_violation, n_violation = hardened_rates(results)
    table = render_pairs(results) + (
        f"\nhardened chosen: {after_pass}/{n_pass} after PASS, "
        f"{after_violation}/{n_violation} after VIOLATION\n"
    )
    (directory / "pairs.md").write_text(table, encoding="utf-8")
    return table
