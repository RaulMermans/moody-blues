"""Runs the frozen plan through the existing workflow, coordinator, sandbox, worlds and Oracle.

What to run comes from the plan. A trial that started and never finished stays on the record as
abandoned and is not run again, because its effects are unknown.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from time import monotonic

from pydantic import JsonValue

from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.experiment_evidence import ExperimentAuthorship, ExperimentSpec
from moody_blues.contracts.investigation import (
    InvestigationReport,
    InvestigationRequest,
    Strategy,
    TargetCapability,
    WorldTier,
)
from moody_blues.evaluation.benchmark.spec import (
    Candidate,
    PlannedTrial,
    Spec,
    Stage,
    StrategyName,
    Unit,
    expand_plan,
    menu_for,
    program_for,
    schedule,
    spec_sha,
    world_candidates,
    world_scenarios,
)
from moody_blues.evaluation.journal import Journal
from moody_blues.experiments.target import ReferenceTarget
from moody_blues.external.local import LocalSession
from moody_blues.investigator.catalog import target_capability
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.preflight import generated_code_runner, sandbox_limits
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow
from moody_blues.investigator.workspace import REPORT
from moody_blues.sandbox.base import SandboxRunner
from moody_blues.world.registry import world_plugin

NO_MODEL = "none"


def journal_path(root: Path, spec: Spec) -> Path:
    return root / f"journal-r{spec.revision}.jsonl"


def investigation_id(trial_id: str) -> str:
    return f"inv_{trial_id}"


def _capability(unit: Unit, worlds: tuple[str, ...]) -> TargetCapability:
    """The target as any operator knows it, with the one config the candidates use."""
    return target_capability(worlds).model_copy(update={"configs": [AgentConfigName.BASELINE]})


def build_workflow(
    spec: Spec,
    trial: PlannedTrial,
    *,
    root: Path,
    sandbox: SandboxRunner,
    settings: Settings,
    investigator: InvestigatorModel | None,
) -> InvestigationWorkflow:
    unit = next(u for u in spec.units if u.unit_id == trial.unit_id)
    worlds = world_scenarios(world_candidates(spec, unit.world_type), unit.world_type)
    adaptive = trial.strategy is StrategyName.ADAPTIVE
    if adaptive and (investigator is None or trial.seed is None):
        raise ValueError("an adaptive trial needs a model and a seed")
    return InvestigationWorkflow(
        request=InvestigationRequest(
            objective=world_plugin(unit.world_type).investigation_objective(),
            strategy=Strategy.ADAPTIVE if adaptive else Strategy.FIXED,
            tier=WorldTier.DEVELOPMENT,
            world_ids=worlds,
            investigator_model=spec.model if adaptive else NO_MODEL,
            target_model=f"reference:{unit.executor}",
            limits=spec.limits,
        ),
        runner=ExperimentRunner(
            sandbox=sandbox,
            target=ReferenceTarget(unit.executor),
            root=root / "experiments",
            sandbox_limits=sandbox_limits(settings),
        ),
        root=root / "investigations",
        model=investigator if adaptive else None,
        capability=_capability(unit, worlds),
        fixed_schedule=None if adaptive else schedule(spec, trial.candidates),
        menu=menu_for(spec, unit, trial.seed) if adaptive and trial.seed is not None else None,
        investigation_id=investigation_id(trial.trial_id),
    )


def ollama_rss_kb() -> int | None:
    """Resident memory of the local model server now. A sample, not a peak."""
    listing = subprocess.run(
        ["/bin/ps", "-axo", "rss=,comm="], capture_output=True, text=True, check=True
    )
    sizes = [
        int(line.split(None, 1)[0])
        for line in listing.stdout.splitlines()
        if "ollama" in line.casefold()
    ]
    return sum(sizes) if sizes else None


def _report_sha(root: Path, report: InvestigationReport) -> str:
    path = root / "investigations" / report.investigation_id / REPORT
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_stage(
    spec: Spec,
    stage: Stage,
    *,
    root: Path,
    settings: Settings,
    session: LocalSession | None,
    sandbox: SandboxRunner | None = None,
    limit: int | None = None,
) -> int:
    """Runs what is left of a stage. Returns how many trials ran."""
    journal = Journal(journal_path(root, spec))
    sha = spec_sha(spec)
    if not journal.payloads("registered"):
        journal.append("registered", {"revision": spec.revision, "spec_sha256": sha})
    if journal.payloads("registered")[0]["spec_sha256"] != sha:
        raise RuntimeError("this journal belongs to another specification")
    finished = {str(p["trial_id"]) for p in journal.payloads("bench_trial")}
    finished |= {str(p["id"]) for p in journal.payloads("abandoned")}
    for started in journal.payloads("started"):
        if str(started["id"]) not in finished:
            journal.append("abandoned", {"id": started["id"], "reason": "process_stopped"})
            finished.add(str(started["id"]))
    runner = sandbox or generated_code_runner(settings)
    ran = 0
    for trial in expand_plan(spec):
        if trial.stage is not stage or trial.trial_id in finished:
            continue
        if limit is not None and ran >= limit:
            break
        adaptive = trial.strategy is StrategyName.ADAPTIVE
        model = session.investigator(spec.limits) if adaptive and session is not None else None
        journal.append("started", {"id": trial.trial_id})
        began = monotonic()
        report = build_workflow(
            spec, trial, root=root, sandbox=runner, settings=settings, investigator=model
        ).run()
        journal.append(
            "bench_trial",
            {
                "trial_id": trial.trial_id,
                "investigation_id": report.investigation_id,
                "report_sha256": _report_sha(root, report),
                "state": report.state.value,
                "termination": report.termination,
                "wall_ms": int((monotonic() - began) * 1000),
                "ollama_rss_kb": ollama_rss_kb() if adaptive else None,
            },
        )
        ran += 1
    return ran


def run_candidate(
    spec: Spec,
    unit: Unit,
    candidate: Candidate,
    *,
    root: Path,
    sandbox: SandboxRunner,
    settings: Settings,
    label: str,
    reproduction_of: str | None,
) -> str:
    """One candidate in a fresh world, outside any strategy. Returns the experiment id."""
    worlds = world_scenarios(world_candidates(spec, unit.world_type), unit.world_type)
    runner = ExperimentRunner(
        sandbox=sandbox,
        target=ReferenceTarget(unit.executor),
        root=root / "experiments",
        sandbox_limits=sandbox_limits(settings),
    )
    evidence = runner.run(
        ExperimentSpec(
            label=label,
            code=program_for(candidate),
            authorship=ExperimentAuthorship.DEVELOPER_SCRIPT,
            reproduction_of=reproduction_of,
        ),
        worlds=worlds,
        max_runtime_seconds=120,
        cancel=None,
    )
    return evidence.experiment_id


def trial_payloads(journal: Journal) -> dict[str, dict[str, JsonValue]]:
    return {str(p["trial_id"]): p for p in journal.payloads("bench_trial")}
