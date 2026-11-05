"""Reclassifies evidence that already exists. Reads records, changes nothing, costs nothing."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from moody_blues.contracts.experiment_evidence import ExperimentEvidence
from moody_blues.contracts.investigation import InvestigationReport
from moody_blues.evaluation.trials import TrialRecord, summarize, trial_from_run
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.workspace import EVIDENCE
from moody_blues.investigator.workspace import REPORT


class AuditRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    created_at: str
    trial: TrialRecord
    reproduction_of: str | None
    investigation_id: str | None


class Audit(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiments_read: int
    live_runs: int
    categories: dict[str, int]
    verified_world_state_violations: int
    violations_in_eligible_runs: int
    violations_in_impaired_runs: int
    live_investigations: int
    investigations_by_state: dict[str, int]
    proposals: int
    proposals_executed: int
    model_claims: int
    model_claims_supported: int
    reported_models: list[str]
    long_stale_rows: list[AuditRow]
    violation_rows: list[AuditRow]


def _rows(experiments: Path) -> tuple[int, list[AuditRow]]:
    rows: list[AuditRow] = []
    paths = sorted(experiments.glob(f"*/{EVIDENCE}"))
    for path in paths:
        evidence = ExperimentEvidence.model_validate_json(path.read_text(encoding="utf-8"))
        intact = not verify_experiment(path.parent)
        for run in evidence.target_runs:
            if run.evidence_source != "live_provider":
                continue
            trial = trial_from_run(
                evidence,
                run,
                root=experiments,
                suite="sprint-05-audit",
                trial_id=run.run_id,
                unit_id=evidence.parent_investigation_id or evidence.experiment_id,
                block=0,
                evidence_intact=intact,
            )
            rows.append(
                AuditRow(
                    experiment_id=evidence.experiment_id,
                    created_at=evidence.created_at.isoformat(),
                    trial=trial,
                    reproduction_of=evidence.reproduction_of,
                    investigation_id=evidence.parent_investigation_id,
                )
            )
    return len(paths), sorted(rows, key=lambda r: r.created_at)


def run_audit(experiments: Path, investigations: Path, *, long_stale: str) -> Audit:
    read, rows = _rows(experiments)
    trials = [r.trial for r in rows]
    reports = [
        InvestigationReport.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(investigations.glob(f"*/{REPORT}"))
    ]
    # A fixed investigation calls no model, but its target can still be live.
    live = [r for r in reports if not r.request.target_model.startswith(("reference", "fixture"))]
    claims = [c for r in live for c in r.claim_checks]
    generated = [p for r in live for p in r.proposals if p.authorship.value == "model_generated"]
    return Audit(
        experiments_read=read,
        live_runs=len(rows),
        categories=dict(Counter(t.category.value for t in trials)),
        verified_world_state_violations=sum(1 for t in trials if t.violated),
        violations_in_eligible_runs=sum(1 for t in trials if t.violated and t.eligible),
        violations_in_impaired_runs=sum(1 for t in trials if t.violated and not t.eligible),
        live_investigations=len(live),
        investigations_by_state=dict(Counter(r.state.value for r in live)),
        proposals=len(generated),
        proposals_executed=sum(1 for p in generated if p.status.value == "executed"),
        model_claims=len(claims),
        model_claims_supported=sum(1 for c in claims if c.supported),
        reported_models=sorted({m for t in trials for m in t.reported_models}),
        long_stale_rows=[r for r in rows if long_stale in r.trial.faults_configured],
        violation_rows=[r for r in rows if r.trial.violated],
    )


def render_audit(audit: Audit) -> str:
    def table(rows: list[AuditRow]) -> list[str]:
        lines = [
            "| Experiment | World | Config | Faults | Verdict | Duplicate | Termination "
            "| Claim | Category | Impairments | Source of run |",
            "|" + "---|" * 11,
        ]
        for r in rows:
            t = r.trial
            origin = f"rerun of {r.reproduction_of}" if r.reproduction_of else "investigation"
            lines.append(
                f"| {r.experiment_id} | {t.world_id} | {t.config} "
                f"| {', '.join(t.faults_configured) or 'none'} | {t.oracle_verdict} "
                f"| {t.duplicate} | {t.termination} | {t.claim_status} | {t.category.value} "
                f"| {', '.join(i.value for i in t.impairments) or '-'} | {origin} |"
            )
        return lines

    cell = summarize("long stale read", [r.trial for r in audit.long_stale_rows])
    return "\n".join(
        [
            f"- Experiments read: {audit.experiments_read}. Live target runs: {audit.live_runs}.",
            f"- Trial categories: {audit.categories}",
            f"- Verified world-state violations: {audit.verified_world_state_violations} "
            f"({audit.violations_in_eligible_runs} eligible, "
            f"{audit.violations_in_impaired_runs} impaired)",
            f"- Live investigations: {audit.live_investigations} {audit.investigations_by_state}",
            f"- Proposals: {audit.proposals}, executed {audit.proposals_executed}",
            f"- Investigator claims: {audit.model_claims}, Oracle-supported "
            f"{audit.model_claims_supported}",
            f"- Models reported by the provider: {audit.reported_models}",
            "",
            f"## Long stale read: {cell.attempted} runs, {cell.eligible} eligible, "
            f"{cell.duplicates_all} duplicates ({cell.duplicates_eligible} eligible)",
            "",
            *table(audit.long_stale_rows),
            "",
            "## All live Oracle violations",
            "",
            *table(audit.violation_rows),
            "",
        ]
    )
