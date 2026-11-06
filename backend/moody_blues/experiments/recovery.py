"""What happens after a coordinator dies, and how evidence is checked afterwards.

A dead coordinator leaves a journal with no ``experiment_finished`` record and releases its
lock. ``recover_interrupted`` finds those, reads what the world actually contains through a
read-only connection, and closes the experiment as UNCERTAIN (when a target run was underway)
or FAILED (when nothing with effects was). It never resumes or repeats anything.
"""

from __future__ import annotations

import fcntl
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue, ValidationError

from moody_blues.contracts.adapter import MODEL_INTENTS_SUFFIX
from moody_blues.contracts.experiment_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    EXTERNAL_EVIDENCE_SCHEMA_VERSION,
    WORLD_EVIDENCE_SCHEMA_VERSION,
    ExperimentAuthorship,
    ExperimentEvidence,
    ExperimentLimits,
    ExperimentState,
    ExperimentTermination,
    OutcomeClass,
    ResourceUsage,
    StepRecord,
    TargetRunEvidence,
    UnresolvedTargetRun,
)
from moody_blues.experiments.workspace import (
    EVIDENCE,
    JOURNAL,
    JournalRecord,
    append_record,
    atomic_write,
    read_journal,
    sha256_text,
)
from moody_blues.world.crm_plugin import WORLD_TYPE as CRM_WORLD_TYPE
from moody_blues.world.registry import plugin_for_scenario
from moody_blues.world.store import DB_FILENAME


def inspect_worlds(worlds_dir: Path, scenario_id: str) -> list[str] | None:
    """Non-seed record ids in the newest surviving world, or None if none can be read."""
    databases = sorted(worlds_dir.glob(f"*/{DB_FILENAME}"), key=lambda p: p.stat().st_mtime)
    if not databases:
        return None
    plugin = plugin_for_scenario(scenario_id)
    try:
        return plugin.new_record_ids(databases[-1], plugin.load_scenario(scenario_id))
    except (sqlite3.Error, OSError):
        return None


def unresolved_run(
    *, run_ref: str, scenario_id: str, found: list[str] | None, note: str, model_calls: int = 0
) -> UnresolvedTargetRun:
    """Each world's new ids go under its own name; ``world_found`` says whether any were read."""
    crm = plugin_for_scenario(scenario_id).descriptor.world_type == CRM_WORLD_TYPE
    return UnresolvedTargetRun(
        run_ref=run_ref,
        scenario_id=scenario_id,
        world_found=found is not None,
        committed_new_customer_ids=found if crm else None,
        committed_new_record_ids=None if crm else found,
        note=note,
        model_calls_unresolved=model_calls,
    )


def unresolved_model_calls(worlds_dir: Path) -> int:
    """Model calls written down before they were made, with no outcome after them."""
    requested: set[str] = set()
    settled: set[str] = set()
    for path in worlds_dir.glob(f"*{MODEL_INTENTS_SUFFIX}"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:  # the crash may have cut the last line; it was still a request
                continue
            target = requested if entry.get("status") == "requested" else settled
            target.add(str(entry.get("request_id")))
    return len(requested - settled)


def schema_for(
    runs: list[TargetRunEvidence], unresolved: list[UnresolvedTargetRun]
) -> Literal[1, 2, 3]:
    """The lowest version that can hold these runs, so CRM records stay as they were."""
    other_world = any(r.world_type != CRM_WORLD_TYPE for r in runs) or any(
        u.committed_new_record_ids is not None for u in unresolved
    )
    if other_world:
        return WORLD_EVIDENCE_SCHEMA_VERSION
    if any(r.external is not None for r in runs):
        return EXTERNAL_EVIDENCE_SCHEMA_VERSION
    return EVIDENCE_SCHEMA_VERSION


def _owned_by_live_process(directory: Path) -> bool:
    lock_path = directory / ".lock"
    if not lock_path.exists():
        return False
    with lock_path.open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def _unresolved(records: list[JournalRecord], worlds_dir: Path) -> list[UnresolvedTargetRun]:
    closed: set[str] = set()
    for record in records:
        if record.kind == "target_run_finished" or record.kind == "target_run_not_started":
            closed.add(str(record.payload["run_ref"]))
    out: list[UnresolvedTargetRun] = []
    for record in records:
        if record.kind != "target_run_intent":
            continue
        run_ref = str(record.payload["run_ref"])
        if run_ref in closed:
            continue
        authorized = cast(dict[str, JsonValue], record.payload["authorized"])
        scenario_id = str(authorized["scenario_id"])
        found = inspect_worlds(worlds_dir, scenario_id)
        out.append(
            unresolved_run(
                run_ref=run_ref,
                scenario_id=scenario_id,
                found=found,
                note="the coordinator died during this run; its effects and any claim are "
                "unverified and no Oracle verdict exists; not retried",
                model_calls=unresolved_model_calls(worlds_dir),
            )
        )
    return out


def _close(directory: Path, records: list[JournalRecord]) -> ExperimentEvidence:
    created = records[0].payload
    steps = [StepRecord.model_validate(r.payload) for r in records if r.kind == "step_completed"]
    runs = [
        TargetRunEvidence.model_validate(r.payload)
        for r in records
        if r.kind == "target_run_finished"
    ]
    unresolved = _unresolved(records, directory / "worlds")
    status = ExperimentState.UNCERTAIN if unresolved else ExperimentState.FAILED
    tokens = [r.tokens for r in runs if r.tokens is not None]
    costs = [r.estimated_cost_usd for r in runs if r.estimated_cost_usd is not None]
    executions = [e for s in steps for e in s.sandbox]
    now = datetime.now(UTC)
    evidence = ExperimentEvidence(
        schema_version=schema_for(runs, unresolved),
        experiment_id=str(created["experiment_id"]),
        parent_investigation_id=cast(str | None, created.get("parent_investigation_id")),
        label=str(created["label"]),
        authorship=ExperimentAuthorship.DEVELOPER_SCRIPT,
        code_sha256=str(created["code_sha256"]),
        protocol=str(created["protocol"]),
        limits=ExperimentLimits.model_validate(created["limits"]),
        status=status,
        termination=ExperimentTermination.COORDINATOR_INTERRUPTED,
        classifications=[OutcomeClass.COORDINATOR_FAILURE],
        detail=f"recovered after the coordinator stopped; last state record seq {records[-1].seq}",
        created_at=datetime.fromisoformat(str(created["created_at"])),
        finished_at=now,
        steps=steps,
        target_runs=runs,
        unresolved_target_runs=unresolved,
        sandbox_supplied=None,
        usage=ResourceUsage(
            sandbox_executions=len(executions),
            sandbox_ms=sum(e.duration_ms for e in executions),
            target_runs=len(runs),
            total_tokens=sum(t.total_tokens for t in tokens),
            tokens_complete=not unresolved and all(t.complete for t in tokens),
            estimated_cost_usd=round(sum(costs), 6) if costs else None,
            wall_ms=0,
        ),
    )
    digest = atomic_write(directory / EVIDENCE, evidence.model_dump_json(indent=2) + "\n")
    _append_recovery(directory, records[-1], status, digest, now)
    return evidence


def _append_recovery(
    directory: Path,
    last: JournalRecord,
    status: ExperimentState,
    digest: str,
    now: datetime,
) -> None:
    append_record(
        directory / JOURNAL,
        seq=last.seq + 1,
        at=now,
        kind="experiment_finished",
        payload={
            "status": status.value,
            "termination": ExperimentTermination.COORDINATOR_INTERRUPTED.value,
            "evidence_sha256": digest,
            "recovered": True,
        },
        prev=last.sha256,
    )


def recover_interrupted(root: Path) -> list[ExperimentEvidence]:
    """Close every experiment whose coordinator is gone. Safe to run repeatedly."""
    recovered: list[ExperimentEvidence] = []
    if not root.is_dir():
        return recovered
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        journal = directory / JOURNAL
        if not journal.exists() or _owned_by_live_process(directory):
            continue
        records, _ = read_journal(journal)
        if not records or any(r.kind == "experiment_finished" for r in records):
            continue
        recovered.append(_close(directory, records))
    return recovered


def verify_experiment(directory: Path) -> list[str]:
    """Check the journal chain, the evidence hash and every run report. Empty means intact."""
    records, problems = read_journal(directory / JOURNAL)
    finished = [r for r in records if r.kind == "experiment_finished"]
    if not finished:
        return [*problems, "experiment has no finish record"]
    evidence_path = directory / EVIDENCE
    if not evidence_path.exists():
        return [*problems, "evidence.json is missing"]
    text = evidence_path.read_text(encoding="utf-8")
    if sha256_text(text) != finished[-1].payload.get("evidence_sha256"):
        problems.append("evidence.json does not match the hash in the journal")
    try:
        evidence = ExperimentEvidence.model_validate_json(text)
    except ValidationError:
        return [*problems, "evidence.json does not match the schema"]
    if evidence.source_path is not None:
        source = directory / evidence.source_path
        if not source.exists():
            problems.append(f"{evidence.source_path} is missing")
        elif sha256_text(source.read_text(encoding="utf-8")) != evidence.code_sha256:
            problems.append(f"{evidence.source_path} does not match the recorded code hash")
    for run in evidence.target_runs:
        report = directory / run.report_path
        if not report.exists():
            problems.append(f"{run.report_path} is missing")
        elif sha256_text(report.read_text(encoding="utf-8")) != run.report_sha256:
            problems.append(f"{run.report_path} does not match its recorded hash")
    return problems
