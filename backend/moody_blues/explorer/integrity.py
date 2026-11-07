"""Checks a directory of evidence and says what it found. It writes nothing, anywhere.

Hash checks come from ``verify_investigation``. This adds what hashes cannot show: that the records
of one run agree with each other. Nothing is signed, so this detects damage and casual edits, not a
determined local attacker. A world is removed when its experiment closes, so state is not read
again here: an Oracle verdict is checked against its own findings, never recomputed from a world.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from moody_blues.contracts.adapter import AdapterEventKind
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, TargetRunEvidence
from moody_blues.contracts.investigation import InvestigationReport
from moody_blues.contracts.oracle import Severity, derive_verdict
from moody_blues.experiments.workspace import sha256_text
from moody_blues.explorer.jobs import BUNDLE
from moody_blues.investigator.workspace import REPORT, verify_investigation

CHECKS = (
    "journal and hashes",
    "run report",
    "tool calls",
    "model calls",
    "world identity",
    "oracle findings",
    "published bundle",
)
_JOB = "job.json"
_EVIDENCE = "evidence.json"


@dataclass(slots=True)
class Audit:
    """Problems by check. A check with a count and no problems passed; no count means NOT_RUN."""

    investigations: int = 0
    runs: int = 0
    checked: Counter[str] = field(default_factory=Counter[str])
    problems: dict[str, list[str]] = field(default_factory=dict[str, list[str]])

    def note(self, check: str, found: list[str]) -> None:
        self.checked[check] += 1
        if found:
            self.problems.setdefault(check, []).extend(found)

    @property
    def intact(self) -> bool:
        return self.investigations > 0 and not self.problems


def check_tool_calls(run: TargetRunEvidence) -> list[str]:
    """Each call is numbered once, in order, and the fault count matches the calls it touched."""
    trace = run.target_observed.tool_trace
    problems: list[str] = []
    if [t.call_seq for t in trace] != list(range(1, len(trace) + 1)):
        problems.append(f"{run.run_id}: tool calls are not numbered once, in order")
    for entry in trace:
        if entry.delivered.tool != entry.tool:
            problems.append(f"{run.run_id}: call {entry.call_seq} answered for another tool")
    delivered = sum(1 for t in trace if t.fault_injected is not None)
    if delivered != run.target_observed.faults_delivered:
        problems.append(f"{run.run_id}: {delivered} faulted calls, recorded as a different count")
    if run.world is not None:
        unknown = {t.tool for t in trace} - set(run.world.selected_tools)
        if unknown:
            problems.append(
                f"{run.run_id}: called tools its world did not offer: {sorted(unknown)}"
            )
    if run.external is not None:
        accepted = sum(
            1 for e in run.external.events if e.kind is AdapterEventKind.TOOL_REQUEST_ACCEPTED
        )
        if accepted != len(trace):
            problems.append(f"{run.run_id}: {accepted} accepted calls but {len(trace)} traced")
        unknown = {t.tool for t in trace} - set(run.external.granted_tools)
        if unknown:
            problems.append(f"{run.run_id}: called tools it was not granted: {sorted(unknown)}")
    return problems


def check_model_calls(run: TargetRunEvidence) -> list[str]:
    """A script never claims a model, and an external run's count matches its records."""
    record = run.external
    if record is None:
        return []
    problems: list[str] = []
    if record.model_requests and record.model_calls != len(record.model_requests):
        problems.append(f"{run.run_id}: model call count differs from its records")
    if run.evidence_source == "external_scripted" and record.model_calls:
        problems.append(f"{run.run_id}: labeled a script, with brokered model calls")
    return problems


def check_world(run: TargetRunEvidence) -> list[str]:
    """Every record of a run names one world. A run with no provenance is the legacy CRM."""
    problems: list[str] = []
    if run.oracle.world_id != run.committed.world_id:
        problems.append(f"{run.run_id}: the Oracle and committed state name different worlds")
    if run.world is not None and not run.oracle.scenario_ref.startswith(run.world.scenario_id):
        problems.append(f"{run.run_id}: the Oracle read another scenario")
    world_type = getattr(run.oracle, "world_type", None)
    if world_type is not None and world_type != run.world_type:
        problems.append(f"{run.run_id}: the Oracle names world type {world_type}")
    return problems


def check_oracle(run: TargetRunEvidence) -> list[str]:
    """The verdict means what ``derive_verdict`` says, given the findings written beside it."""
    oracle = run.oracle
    problems: list[str] = []
    evaluated = {str(i) for i in oracle.invariants_evaluated}
    violated = {str(i) for i in oracle.invariants_violated}
    if not violated <= evaluated:
        problems.append(f"{run.run_id}: an invariant was violated without being evaluated")
    severe = {
        str(f.invariant)
        for f in oracle.findings
        if f.severity is Severity.VIOLATION and f.invariant is not None
    }
    if severe != violated:
        problems.append(f"{run.run_id}: findings and violated invariants disagree")
    expected = derive_verdict(
        violated=bool(violated),
        objective_satisfied=oracle.objective_satisfied,
        claim=oracle.claim,
    )
    if oracle.verdict is not expected:
        problems.append(f"{run.run_id}: {oracle.verdict.value} does not follow from its findings")
    return problems


def _report_run_id(report: dict[str, Any]) -> str | None:
    """A reference script's report has no run id: ``ReferenceTarget`` derives one from it."""
    if "run_id" in report:
        return report["run_id"]
    fingerprint, world_id = report.get("fingerprint"), report.get("world_id")
    if not isinstance(fingerprint, str) or not isinstance(world_id, str):
        return None
    return f"ref_{fingerprint[:12]}_{world_id[-6:]}"


def check_run_report(run: TargetRunEvidence, directory: Path) -> list[str]:
    """The report on disk and the evidence that hashed it tell the same story."""
    path = directory / run.report_path
    if not path.exists():
        return []  # reported missing by the hash check
    try:
        report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return [f"{run.report_path} cannot be read"]
    problems: list[str] = []
    if _report_run_id(report) != run.run_id:
        problems.append(f"{run.report_path}: belongs to another run")
    if report.get("oracle") != run.oracle.model_dump(mode="json"):
        problems.append(f"{run.report_path}: its Oracle report differs from the evidence")
    if report.get("world_id") != run.committed.world_id:
        problems.append(f"{run.report_path}: names another world")
    return problems


def _check_experiment(audit: Audit, directory: Path) -> None:
    path = directory / _EVIDENCE
    if not path.exists():
        return  # reported by the hash check
    try:
        evidence = ExperimentEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError:
        return  # reported by the hash check
    for run in evidence.target_runs:
        audit.runs += 1
        audit.note("run report", check_run_report(run, directory))
        audit.note("tool calls", check_tool_calls(run))
        audit.note("model calls", check_model_calls(run))
        audit.note("world identity", check_world(run))
        audit.note("oracle findings", check_oracle(run))


def _check_bundles(audit: Audit, root: Path, known: set[str]) -> None:
    jobs = root / "live-jobs"
    if not jobs.is_dir():
        return
    for job_path in sorted(jobs.glob(f"*/{_JOB}")):
        try:
            job: dict[str, Any] = json.loads(job_path.read_text(encoding="utf-8"))
        except ValueError:
            audit.note("published bundle", [f"{job_path.parent.name}: job record cannot be read"])
            continue
        bundle = job_path.parent / BUNDLE
        if not job.get("evidence_available") or not bundle.exists():
            continue
        found: list[str] = []
        if sha256_text(bundle.read_text(encoding="utf-8")) != job.get("bundle_sha256"):
            found.append(f"{job_path.parent.name}: bundle does not match its recorded hash")
        if job.get("investigation_id") not in known:
            found.append(f"{job_path.parent.name}: names an investigation not in this directory")
        audit.note("published bundle", found)


def audit_artifacts(root: Path) -> Audit:
    """Everything under ``root``. Reads only: no directory is made and no lock is taken."""
    audit = Audit()
    investigations = root / "investigations"
    experiments = root / "experiments"
    known: set[str] = set()
    if not investigations.is_dir():
        return audit
    for directory in sorted(p for p in investigations.iterdir() if p.is_dir()):
        audit.investigations += 1
        known.add(directory.name)
        audit.note(
            "journal and hashes",
            [f"{directory.name}: {p}" for p in verify_investigation(directory, experiments)],
        )
        path = directory / REPORT
        if not path.exists():
            continue
        try:
            report = InvestigationReport.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError:
            continue  # reported above
        for ref in report.experiments:
            _check_experiment(audit, experiments / ref.experiment_id)
    _check_bundles(audit, root, known)
    return audit


def print_audit(audit: Audit, root: Path) -> None:
    print(f"EVIDENCE: {root}")
    print(f"  {audit.investigations} investigation(s), {audit.runs} run(s)")
    for check in CHECKS:
        count = audit.checked[check]
        found = audit.problems.get(check, [])
        state = "NOT_RUN" if count == 0 else "FAIL" if found else "PASS"
        print(f"  [{state:7}] {check} ({count} checked)")
        for problem in found[:20]:
            print(f"            {problem}")
        if len(found) > 20:
            print(f"            ... and {len(found) - 20} more")
    print("Nothing was written. Nothing here is signed: this finds damage, not a forger.")
