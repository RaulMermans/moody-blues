"""Command implementations for the registered evaluation. ``cli.py`` only wires arguments.

``eval-run`` is the only billable command here. It refuses unless the registration is committed
and its fingerprints still match the code. Suites run one at a time, sequentially, on the same
ledger as everything else; the manifest's limit sits above what was already settled, so the sprint
gets its stated budget and nothing is reset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.common import MoodyBluesError
from moody_blues.contracts.experiment_evidence import (
    ExperimentEvidence,
    ExperimentSpec,
)
from moody_blues.contracts.investigation import (
    InvestigationLimits,
    InvestigationReport,
    InvestigationRequest,
    Strategy,
    WorldTier,
)
from moody_blues.evaluation.adaptation import run_answers
from moody_blues.evaluation.audit import render_audit, run_audit
from moody_blues.evaluation.journal import Journal, JournalError
from moody_blues.evaluation.manifest import (
    FROZEN_DIR,
    Faults,
    Manifest,
    ManifestError,
    PlannedInvestigation,
    TrialPlan,
    canonical_sha,
    check_fingerprints,
    committed_head,
    freeze,
    load_frozen,
)
from moody_blues.evaluation.report import build_results, write_results
from moody_blues.evaluation.suites import SuiteStoppedError, run_causal, run_strategies
from moody_blues.experiments.budget import (
    PriceCeiling,
    ScopedSpend,
    SpendLedger,
    worst_case_run_tokens,
)
from moody_blues.experiments.programs import probe_program
from moody_blues.experiments.target import AgentTarget, ReferenceTarget
from moody_blues.experiments.workspace import EVIDENCE
from moody_blues.inference.vultr import PROVIDER
from moody_blues.investigator.catalog import target_capability
from moody_blues.investigator.commands import (
    ARTIFACTS,
    DEFAULT_OBJECTIVE,
    EXPERIMENTS,
    INVESTIGATIONS,
    LiveContext,
    not_confirmed,
    open_live,
    target_client,
)
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.preflight import generated_code_runner, sandbox_limits
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow

JOURNALS = ARTIFACTS / "sprint-06"
RESULTS = FROZEN_DIR / "results"
SUITES = ("causal", "strategies", "adaptation")


def _journal(suite: str) -> Journal:
    return Journal(JOURNALS / suite / "journal.jsonl")


def _model(
    settings: Settings, live: LiveContext, spend: ScopedSpend, limits: InvestigationLimits
) -> InvestigatorModel:
    return InvestigatorModel(
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


def _agent_target(settings: Settings, manifest: Manifest, spend: ScopedSpend) -> AgentTarget:
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    return AgentTarget(
        inference=target_client(settings, key),
        evidence="live_provider",
        provider=PROVIDER,
        model=settings.investigator_target_model,
        budget=manifest.target_budget,
        ledger=spend,
    )


@dataclass(slots=True)
class _CausalExecutor:
    settings: Settings
    manifest: Manifest
    spend: ScopedSpend
    prices: PriceCeiling
    root: Path = EXPERIMENTS

    def run(
        self, *, trial_id: str, world: str, config: AgentConfigName, faults: Faults
    ) -> ExperimentEvidence:
        runner = ExperimentRunner(
            sandbox=generated_code_runner(self.settings),
            target=_agent_target(self.settings, self.manifest, self.spend),
            root=self.root,
            sandbox_limits=sandbox_limits(self.settings),
        )
        evidence = runner.run(
            ExperimentSpec(
                label=trial_id,
                code=probe_program(
                    scenario_id=world,
                    config=config.value,
                    looking_for="duplicate_side_effect",
                    faults=faults,
                ),
                parent_investigation_id=f"s6-causal-{trial_id}"[:64],
            ),
            worlds=(world,),
            max_runtime_seconds=300.0,
            cancel=None,
        )
        print(
            json.dumps(
                {
                    "trial": trial_id,
                    "experiment": evidence.experiment_id,
                    "status": evidence.status.value,
                }
            ),
            flush=True,
        )
        return evidence

    def remaining_usd(self) -> float:
        status = self.spend.status()
        return self.spend.limit_usd - status.settled_usd - status.open_reservations_usd

    @property
    def reservation_usd(self) -> float:
        return self.prices.worst_case(worst_case_run_tokens(self.manifest.target_budget))


@dataclass(slots=True)
class _InvestigationExecutor:
    settings: Settings
    manifest: Manifest
    live: LiveContext
    spend: ScopedSpend
    root: Path = EXPERIMENTS

    def run(self, unit: PlannedInvestigation) -> InvestigationReport:
        suite = self.manifest.strategies
        limits = suite.limits
        schedule = None
        if unit.strategy is Strategy.FIXED:
            schedule = [
                (
                    label,
                    probe_program(
                        scenario_id=world,
                        config="baseline",
                        looking_for="duplicate_side_effect",
                        faults=condition.faults,
                    ),
                )
                for label, world, condition in unit.fixed_schedule
            ]
        workflow = InvestigationWorkflow(
            request=InvestigationRequest(
                objective=DEFAULT_OBJECTIVE,
                strategy=unit.strategy,
                tier=WorldTier.EVALUATION,
                world_ids=suite.worlds,
                investigator_model=self.settings.investigator_model,
                target_model=self.settings.investigator_target_model,
                limits=limits,
            ),
            runner=ExperimentRunner(
                sandbox=generated_code_runner(self.settings),
                target=_agent_target(self.settings, self.manifest, self.spend),
                root=self.root,
                sandbox_limits=sandbox_limits(self.settings),
            ),
            root=INVESTIGATIONS,
            model=None
            if unit.strategy is Strategy.FIXED
            else _model(self.settings, self.live, self.spend, limits),
            spend=self.spend,
            fixed_schedule=schedule,
            repair_unrun_programs=unit.strategy is Strategy.ONE_SHOT,
        )
        report = workflow.run()
        print(
            json.dumps(
                {
                    "unit": unit.unit_id,
                    "investigation": report.investigation_id,
                    "state": report.state.value,
                    "termination": report.termination,
                    "statement": report.statement,
                }
            ),
            flush=True,
        )
        return report

    def evidence(self, experiment_id: str) -> ExperimentEvidence:
        return ExperimentEvidence.model_validate_json(
            (self.root / experiment_id / EVIDENCE).read_text(encoding="utf-8")
        )


def _run_adaptation(
    settings: Settings, manifest: Manifest, plan: TrialPlan, live: LiveContext
) -> None:
    suite = manifest.adaptation
    spend = ScopedSpend(live.ledger, "s6-adaptation", manifest.budget.adaptation_cap_usd)

    def runner_for(executor: str) -> ExperimentRunner:
        return ExperimentRunner(
            sandbox=generated_code_runner(settings),
            target=ReferenceTarget(executor),
            root=EXPERIMENTS,
            sandbox_limits=sandbox_limits(settings),
        )

    records = run_answers(
        suite,
        plan.adaptation,
        model=_model(settings, live, spend, suite.limits),
        runner_for=runner_for,
        capability=target_capability(suite.worlds),
        objective=DEFAULT_OBJECTIVE,
        journal=_journal("adaptation"),
        artifacts=JOURNALS / "adaptation" / "calls",
    )
    print(json.dumps({"answers": len(records)}), flush=True)


def _registered(settings: Settings) -> tuple[Manifest, TrialPlan, str]:
    manifest, plan = load_frozen()
    drift = check_fingerprints(manifest, settings)
    if drift:
        raise ManifestError(f"the code no longer matches the registration: {drift}")
    return manifest, plan, committed_head()


def eval_freeze(settings: Settings) -> int:
    ledger = SpendLedger(
        ARTIFACTS / "live-spend" / "ledger.jsonl",
        limit_usd=settings.live_spend_limit_usd,
        prices=PriceCeiling.from_settings(settings),
    )
    status = ledger.status()
    if status.open_reservations:
        print(json.dumps({"status": "BLOCKED", "reason": "open reservations in the ledger"}))
        return 2
    manifest, plan = freeze(settings, settled_usd=status.settled_usd)
    print(
        json.dumps(
            {
                "manifest_sha256": canonical_sha(manifest),
                "causal_stage_one": len(plan.causal_stage_one),
                "units": len(plan.strategies),
                "answers": len(plan.adaptation),
            }
        )
    )
    return 0


def eval_verify(settings: Settings) -> int:
    try:
        manifest, plan, head = _registered(settings)
    except ManifestError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)[:400]}))
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "manifest_sha256": plan.manifest_sha256,
                "head": head,
                "ledger_limit_usd": manifest.budget.ledger_limit_usd,
            }
        )
    )
    return 0


def eval_run(settings: Settings, *, suite: str, confirmed: bool) -> int:
    if not confirmed:
        return not_confirmed("eval-run")
    try:
        manifest, plan, head = _registered(settings)
    except ManifestError as exc:
        print(json.dumps({"status": "NOT_RUN", "reason": str(exc)[:400]}))
        return 2
    live = open_live(settings, limit_usd=manifest.budget.ledger_limit_usd)
    if live is None:
        return 2
    journal = _journal(suite)
    if not journal.payloads("run"):
        journal.append("run", {"registered_at": head, "manifest_sha256": plan.manifest_sha256})
    try:
        if suite == "causal":
            run_causal(
                manifest,
                plan,
                executor=_CausalExecutor(
                    settings,
                    manifest,
                    ScopedSpend(live.ledger, "s6-causal", manifest.budget.causal_cap_usd),
                    live.ledger.prices,
                ),
                journal=journal,
            )
        elif suite == "strategies":
            run_strategies(
                manifest,
                plan,
                executor=_InvestigationExecutor(
                    settings,
                    manifest,
                    live,
                    ScopedSpend(live.ledger, "s6-strategies", manifest.budget.strategies_cap_usd),
                ),
                journal=journal,
            )
        else:
            _run_adaptation(settings, manifest, plan, live)
    except (SuiteStoppedError, MoodyBluesError, JournalError) as exc:
        print(json.dumps({"status": "BLOCKED_BY_BUDGET", "reason": str(exc)[:400]}))
        return 3
    status = live.ledger.status()
    print(
        json.dumps(
            {
                "ledger_settled_usd": status.settled_usd,
                "remaining_usd": status.remaining_usd,
                "note": "estimate at assumed ceiling prices; confirm in the Vultr console",
            }
        )
    )
    return 0


def eval_report(settings: Settings) -> int:
    manifest, plan = load_frozen()
    journals = {s: _journal(s) for s in SUITES}
    runs = journals["causal"].payloads("run")
    ledger = SpendLedger(
        ARTIFACTS / "live-spend" / "ledger.jsonl",
        limit_usd=manifest.budget.ledger_limit_usd,
        prices=PriceCeiling.from_settings(settings),
    )
    results, trials = build_results(
        manifest,
        plan,
        causal=journals["causal"],
        strategies=journals["strategies"],
        adaptation=journals["adaptation"],
        registered_at=str(runs[0]["registered_at"]) if runs else None,
        adaptation_cost_usd=ledger.scope_status("s6-adaptation").settled_usd,
    )
    write_results(RESULTS, results, trials, manifest)
    print(json.dumps({"conclusion": results.conclusion, "reasons": results.conclusion_reasons}))
    print(f"record: {RESULTS}")
    return 0


def evidence_audit() -> int:
    audit = run_audit(EXPERIMENTS, INVESTIGATIONS, long_stale="stale_read#1x6")
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    (FROZEN_DIR / "evidence-audit.json").write_text(audit.model_dump_json(indent=2) + "\n", "utf-8")
    text = render_audit(audit)
    (FROZEN_DIR / "evidence-audit.md").write_text(
        "# Sprint 5 evidence, reclassified\n\n_Generated by `moody-blues evidence-audit`._\n\n"
        + text,
        "utf-8",
    )
    print(text)
    return 0
