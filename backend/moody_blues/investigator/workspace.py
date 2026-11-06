"""Trusted on-disk record of one investigation, and the one-at-a-time lock.

Layout of ``<root>/<investigation_id>/`` (mode 0700, never mounted into a sandbox)::

    journal.jsonl   hash-chained, fsynced, written ahead of every model call and experiment
    state.json      latest bounded state, rewritten at each transition
    report.json     final record; its hash is stored in the journal
    sources/        every generated program, by proposal id, including rejected ones
    calls/          exact prompt and response of every model call

Experiments keep their own directories under the shared experiment root, so that existing
recovery and verification apply to them unchanged. They are linked by id and evidence hash.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.experiment_evidence import ExperimentEvidence
from moody_blues.contracts.investigation import (
    TERMINAL_INVESTIGATION_STATES,
    InvestigationReport,
)
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.workspace import (
    EVIDENCE,
    GENESIS,
    JOURNAL,
    append_record,
    atomic_write,
    read_journal,
    sha256_text,
)

REPORT = "report.json"
STATE = "state.json"


class InvestigationBusyError(MoodyBluesError):
    def __init__(self) -> None:
        super().__init__(ErrorCategory.BUDGET_EXCEEDED, "another investigation is running")


@contextmanager
def exclusive(root: Path) -> Generator[None]:
    """One investigation at a time on this machine. A second one is refused, not queued."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InvestigationBusyError from exc
        yield


class InvestigationWorkspace:
    def __init__(self, root: Path, investigation_id: str) -> None:
        self.directory = root / investigation_id
        self.directory.mkdir(parents=True, mode=0o700)
        self.sources_dir = self.directory / "sources"
        self.calls_dir = self.directory / "calls"
        self.sources_dir.mkdir(mode=0o700)
        self.calls_dir.mkdir(mode=0o700)
        self._seq = 0
        self._prev = GENESIS

    def journal(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        self._seq += 1
        self._prev = append_record(
            self.directory / JOURNAL,
            seq=self._seq,
            at=datetime.now(UTC),
            kind=kind,
            payload=payload or {},
            prev=self._prev,
        )

    def save_source(self, proposal_id: str, code: str) -> str:
        """Preserves the program exactly as generated. Returns its path in this directory."""
        name = f"{proposal_id}.py"
        atomic_write(self.sources_dir / name, code)
        return f"sources/{name}"

    def save_state(self, report: InvestigationReport) -> None:
        atomic_write(self.directory / STATE, report.model_dump_json(indent=1) + "\n")

    def save_report(self, report: InvestigationReport) -> None:
        digest = atomic_write(self.directory / REPORT, report.model_dump_json(indent=2) + "\n")
        self.journal(
            "investigation_finished", {"state": report.state.value, "report_sha256": digest}
        )


def _verify_model_calls(directory: Path, report: InvestigationReport) -> list[str]:
    """What the model was asked and what it answered, against the hashes in the report."""
    problems: list[str] = []
    for call in report.model_calls:
        path = directory / call.artifact_path
        if not path.exists():
            problems.append(f"{call.artifact_path} is missing")
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
            request, response = artifact["request"], artifact.get("response")
        except (ValueError, KeyError, TypeError):
            problems.append(f"{call.artifact_path} cannot be read")
            continue
        answered = sha256_text(response) if response is not None else None
        if sha256_text(request) != call.prompt_sha256 or answered != call.response_sha256:
            problems.append(f"{call.artifact_path} does not match its recorded hash")
    return problems


def verify_investigation(directory: Path, experiment_root: Path) -> list[str]:
    """Check the journal, the report, every source and every linked experiment.

    Empty means intact. Like the experiment journal this detects accidental or casual edits, not
    a determined local attacker: nothing is signed.
    """
    records, problems = read_journal(directory / JOURNAL)
    finished = [r for r in records if r.kind == "investigation_finished"]
    path = directory / REPORT
    if not finished or not path.exists():
        return [*problems, "investigation has no finished report"]
    text = path.read_text(encoding="utf-8")
    if sha256_text(text) != finished[-1].payload.get("report_sha256"):
        problems.append("report.json does not match the hash in the journal")
    try:
        report = InvestigationReport.model_validate_json(text)
    except ValidationError:
        return [*problems, "report.json does not match the schema"]
    for proposal in report.proposals:
        if proposal.source_path is None:
            continue
        source = directory / proposal.source_path
        if not source.exists():
            problems.append(f"{proposal.source_path} is missing")
        elif sha256_text(source.read_text(encoding="utf-8")) != proposal.source_sha256:
            problems.append(f"{proposal.source_path} does not match its recorded hash")
    problems.extend(_verify_model_calls(directory, report))
    known = {p.proposal_id: p for p in report.proposals}
    for ref in report.experiments:
        experiment = experiment_root / ref.experiment_id
        problems.extend(f"{ref.experiment_id}: {p}" for p in verify_experiment(experiment))
        evidence_path = experiment / EVIDENCE
        if not evidence_path.exists():
            continue
        evidence_text = evidence_path.read_text(encoding="utf-8")
        if sha256_text(evidence_text) != ref.evidence_sha256:
            problems.append(f"{ref.experiment_id}: evidence differs from the linked hash")
        evidence = ExperimentEvidence.model_validate_json(evidence_text)
        if evidence.parent_investigation_id != report.investigation_id:
            problems.append(f"{ref.experiment_id}: belongs to another investigation")
        proposal = known.get(ref.proposal_id)
        if proposal is None:
            problems.append(f"{ref.experiment_id}: linked to an unknown proposal")
        elif proposal.source_sha256 not in {None, evidence.code_sha256}:
            problems.append(f"{ref.experiment_id}: ran different code from its proposal")
    return problems


def recover_investigations(root: Path) -> list[str]:
    """Close investigations whose process died. Never resumes, retries or invents a result.

    Open spend reservations are left in the ledger, where they keep counting in full.
    """
    closed: list[str] = []
    if not root.exists():
        return closed
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        state_path = directory / STATE
        if (directory / REPORT).exists() or not state_path.exists():
            continue
        report = InvestigationReport.model_validate_json(state_path.read_text(encoding="utf-8"))
        if report.state in TERMINAL_INVESTIGATION_STATES:
            continue
        records, _ = read_journal(directory / JOURNAL)
        last = records[-1] if records else None
        prev = last.sha256 if last is not None else GENESIS
        append_record(
            directory / JOURNAL,
            seq=(last.seq if last is not None else 0) + 1,
            at=datetime.now(UTC),
            kind="investigation_interrupted",
            payload={"state_at_crash": report.state.value},
            prev=prev,
        )
        closed.append(directory.name)
    return closed
