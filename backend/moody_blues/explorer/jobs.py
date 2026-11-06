"""The smallest job lifecycle that survives a restart honestly.

One in-process worker thread runs at most one investigation. State lives on disk::

    <artifacts>/live-jobs/<job_id>/job.json       latest record, written atomically
    <artifacts>/live-jobs/<job_id>/events.jsonl   append-only, fsynced, numbered from 1
    <artifacts>/live-jobs/<job_id>/bundle.json    sanitized evidence, present once durable

Rules that matter more than the code:

- Progress comes from tailing the investigation's own journal, so the Investigator is unchanged
  and nothing is reported that is not already on the record. Only ids and fixed codes are
  published, never model or target text.
- A job is terminal only after its bundle is on disk, or after the reason it cannot be.
- A job is never retried. After a crash, ``reconcile`` runs the existing recovery and classifies
  what it finds: a target run that never reported makes the job ``outcome_uncertain``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from uuid import uuid4

from pydantic import ValidationError

from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.experiment_evidence import ExperimentState
from moody_blues.contracts.explorer import (
    TERMINAL_JOB_STATES,
    JobEvent,
    JobEventType,
    JobRecord,
    JobStatus,
    JobView,
    ProductOutcome,
)
from moody_blues.contracts.investigation import (
    InvestigationReport,
    InvestigationState,
    ResultClass,
)
from moody_blues.experiments.recovery import recover_interrupted
from moody_blues.experiments.workspace import JOURNAL, atomic_write, read_journal
from moody_blues.explorer.missions import Mission
from moody_blues.explorer.projection import build_bundle
from moody_blues.explorer.recorded import render
from moody_blues.explorer.sanitize import EvidenceRefusedError, require_clean
from moody_blues.investigator.workflow import InvestigationWorkflow
from moody_blues.investigator.workspace import (
    REPORT,
    InvestigationBusyError,
    exclusive,
    recover_investigations,
)

log = logging.getLogger("moody_blues.jobs")

JOB = "job.json"
EVENTS = "events.jsonl"
BUNDLE = "bundle.json"
MAX_LISTED_JOBS = 50
_JOB_ID = re.compile(r"^job_[0-9a-f]{12}$")
_POLL_SECONDS = 0.25
SHUTDOWN_WAIT_SECONDS = 20.0

_STATUS_EVENT: dict[JobStatus, JobEventType] = {
    JobStatus.COMPLETED: JobEventType.COMPLETED,
    JobStatus.FAILED: JobEventType.FAILED,
    JobStatus.CANCELLED: JobEventType.CANCELLED,
    JobStatus.BUDGET_EXHAUSTED: JobEventType.BUDGET_EXHAUSTED,
    JobStatus.OUTCOME_UNCERTAIN: JobEventType.OUTCOME_UNCERTAIN,
}


class MissionBlockedError(Exception):
    """A mission could not start. Raised before any chargeable work. Carries a fixed code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


WorkflowFactory = Callable[[Mission, str, Event], InvestigationWorkflow]


class JobStore:
    """The on-disk record. Readers and the worker share it; only the worker writes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._write_lock = Lock()

    def directory(self, job_id: str) -> Path:
        if not _JOB_ID.fullmatch(job_id):
            raise ValueError("not a job id")
        return self.root / job_id

    def create(self, record: JobRecord) -> None:
        self.directory(record.job_id).mkdir(parents=True, mode=0o700)
        self.save(record)

    def save(self, record: JobRecord) -> None:
        atomic_write(self.directory(record.job_id) / JOB, record.model_dump_json(indent=1) + "\n")

    def read(self, job_id: str) -> JobRecord | None:
        if not _JOB_ID.fullmatch(job_id):
            return None
        path = self.root / job_id / JOB
        if not path.is_file():
            return None
        try:
            return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise MoodyBluesError(
                ErrorCategory.EVIDENCE_INTEGRITY, "job record is corrupt"
            ) from exc

    def all(self) -> list[JobRecord]:
        if not self.root.is_dir():
            return []
        ids = sorted(p.name for p in self.root.iterdir() if _JOB_ID.fullmatch(p.name))
        records = [r for r in (self._read_quietly(i) for i in ids) if r is not None]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:MAX_LISTED_JOBS]

    def _read_quietly(self, job_id: str) -> JobRecord | None:
        try:
            return self.read(job_id)
        except MoodyBluesError:
            log.warning("job_record_corrupt", extra={"job_id": job_id})
            return None

    def events(self, job_id: str, *, after: int = 0) -> list[JobEvent]:
        path = self.directory(job_id) / EVENTS
        if not path.is_file():
            return []
        out: list[JobEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = JobEvent.model_validate_json(line)
            except ValidationError:
                continue  # a torn last line after a crash: the next append starts clean
            if event.event_id > after:
                out.append(event)
        return out

    def append(
        self,
        job_id: str,
        kind: JobEventType,
        code: str,
        *,
        experiment_id: str | None = None,
        result_class: ResultClass | None = None,
    ) -> None:
        with self._write_lock:
            existing = self.events(job_id)
            event = JobEvent(
                event_id=(existing[-1].event_id if existing else 0) + 1,
                job_id=job_id,
                at=datetime.now(UTC),
                type=kind,
                code=code,
                experiment_id=experiment_id,
                result_class=result_class,
            )
            with (self.directory(job_id) / EVENTS).open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
                f.flush()
                os.fsync(f.fileno())


class JobManager:
    def __init__(
        self,
        store: JobStore,
        *,
        artifacts: Path,
        factory: WorkflowFactory,
        secrets: tuple[str, ...] = (),
    ) -> None:
        self.store = store
        self._investigations = artifacts / "investigations"
        self._experiments = artifacts / "experiments"
        self._factory = factory
        self._secrets = secrets
        self._lock = Lock()
        self._record_lock = Lock()
        self._active: str | None = None
        self._cancel: Event | None = None
        self._thread: Thread | None = None

    @property
    def active_job_id(self) -> str | None:
        with self._lock:
            return self._active

    def start(self, mission: Mission) -> JobRecord:
        """Admission is synchronous; everything slow happens on the worker thread."""
        with self._lock:
            if self._active is not None:
                raise MoodyBluesError(
                    ErrorCategory.CONFLICT, "another investigation is running; it was not queued"
                )
            now = datetime.now(UTC)
            record = JobRecord(
                job_id=f"job_{uuid4().hex[:12]}",
                mission_id=mission.mission_id,
                mode=mission.mode,
                status=JobStatus.CREATED,
                investigation_id=f"inv_{uuid4().hex[:12]}",
                created_at=now,
                updated_at=now,
            )
            self.store.create(record)
            self.store.append(record.job_id, JobEventType.CREATED, "job_created")
            record = self._update(record.job_id, status=JobStatus.QUEUED)
            self.store.append(record.job_id, JobEventType.QUEUED, "job_queued")
            cancel = Event()
            self._active = record.job_id
            self._cancel = cancel
            self._thread = Thread(
                target=self._work,
                args=(record, mission, cancel),
                name=f"investigation-{record.job_id}",
                daemon=True,
            )
            self._thread.start()
        return record

    def cancel(self, job_id: str) -> JobRecord:
        if self.store.read(job_id) is None:
            raise MoodyBluesError(ErrorCategory.NOT_FOUND, "no such job")
        with self._lock:
            if self._active != job_id:
                raise MoodyBluesError(ErrorCategory.CONFLICT, "this job is not running")
            if self._cancel is not None:
                self._cancel.set()
            record = self._update(job_id, cancel_requested=True)
        self.store.append(job_id, JobEventType.CANCEL_REQUESTED, "cancel_requested")
        return record

    def view(self, job_id: str, *, after: int = 0) -> JobView:
        record = self.store.read(job_id)
        if record is None:
            raise MoodyBluesError(ErrorCategory.NOT_FOUND, "no such job")
        return JobView(job=record, events=self.store.events(job_id, after=after))

    def wait(self, timeout: float) -> None:
        """Block until the worker stops, or the timeout passes."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def shutdown(self, timeout: float = SHUTDOWN_WAIT_SECONDS) -> None:
        """Ask a running job to stop. Whatever it leaves is classified by ``reconcile``."""
        with self._lock:
            if self._cancel is not None:
                self._cancel.set()
        self.wait(timeout)

    def _update(self, job_id: str, **changes: object) -> JobRecord:
        """Changes apply to the latest record, so two writers cannot undo each other."""
        with self._record_lock:
            latest = self.store.read(job_id)
            if latest is None:  # pragma: no cover - created before any update
                raise MoodyBluesError(ErrorCategory.NOT_FOUND, "no such job")
            updated = latest.model_copy(update={"updated_at": datetime.now(UTC), **changes})
            self.store.save(updated)
        return updated

    # --- worker -----------------------------------------------------------------------------

    def _work(self, record: JobRecord, mission: Mission, cancel: Event) -> None:
        job_id = record.job_id
        try:
            current = self._update(job_id, status=JobStatus.RUNNING)
            self.store.append(job_id, JobEventType.RUNNING, "job_running")
            self._run(current, mission, cancel)
        finally:
            with self._lock:
                self._active = None
                self._cancel = None

    def _run(self, record: JobRecord, mission: Mission, cancel: Event) -> None:
        try:
            workflow = self._factory(mission, record.investigation_id, cancel)
        except MissionBlockedError as exc:
            self._close(record, JobStatus.FAILED, exc.code)
            return
        stop = Event()
        seen = _Seen()
        tail = Thread(target=self._tail, args=(record, stop, seen), daemon=True)
        tail.start()
        try:
            workflow.run()
        except InvestigationBusyError:
            self._stop_tail(stop, tail, record, seen)
            self._close(record, JobStatus.FAILED, "investigation_busy")
            return
        except Exception:
            # Not hidden: logged with its traceback, and the job says the outcome is unknown. A
            # crash inside a run may have left effects, so this must not read as a plain failure.
            log.exception("job_crashed", extra={"job_id": record.job_id})
            self._stop_tail(stop, tail, record, seen)
            self._close(record, JobStatus.OUTCOME_UNCERTAIN, "worker_crashed")
            return
        self._stop_tail(stop, tail, record, seen)
        self._finish(record)

    def _stop_tail(self, stop: Event, tail: Thread, record: JobRecord, seen: _Seen) -> None:
        stop.set()
        tail.join(5)
        self._drain(record, seen)

    def _tail(self, record: JobRecord, stop: Event, seen: _Seen) -> None:
        while not stop.wait(_POLL_SECONDS):
            self._drain(record, seen)

    def _drain(self, record: JobRecord, seen: _Seen) -> None:
        path = self._investigations / record.investigation_id / JOURNAL
        if not path.is_file():
            return
        with seen.lock:
            records, _ = read_journal(path)
            for entry in records:
                if entry.seq <= seen.last_seq:
                    continue
                seen.last_seq = entry.seq
                if entry.kind != "experiment_linked":
                    continue
                experiment_id = str(entry.payload.get("experiment_id"))
                result = _result_class(self._investigations, record, entry.payload)
                self.store.append(
                    record.job_id,
                    JobEventType.EXPERIMENT_COMPLETED,
                    "experiment_completed",
                    experiment_id=experiment_id,
                    result_class=result,
                )
                if result is ResultClass.ORACLE_CONFIRMED_VIOLATION:
                    self.store.append(
                        record.job_id,
                        JobEventType.FINDING_VERIFIED,
                        "oracle_confirmed_violation",
                        experiment_id=experiment_id,
                        result_class=result,
                    )

    def _finish(self, record: JobRecord) -> None:
        directory = self._investigations / record.investigation_id
        report_path = directory / REPORT
        if not report_path.is_file():
            self._close(record, JobStatus.OUTCOME_UNCERTAIN, "no_report_written")
            return
        try:
            report = InvestigationReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            bundle = build_bundle(directory, self._experiments, mode=record.mode)
            text = render(bundle)
            require_clean(text, secrets=self._secrets)
        except (OSError, ValidationError, EvidenceRefusedError) as exc:
            log.warning("job_evidence_refused", extra={"job_id": record.job_id, "error": str(exc)})
            self._close(record, JobStatus.FAILED, "evidence_not_intact")
            return
        digest = atomic_write(self.store.directory(record.job_id) / BUNDLE, text)
        status, code = terminal_status(report, bundle.summary.outcome)
        self._close(record, status, code, evidence_sha256=digest)

    def _close(
        self,
        record: JobRecord,
        status: JobStatus,
        code: str,
        *,
        evidence_sha256: str | None = None,
    ) -> None:
        self._update(
            record.job_id,
            status=status,
            code=code,
            finished_at=datetime.now(UTC),
            evidence_available=evidence_sha256 is not None,
            bundle_sha256=evidence_sha256,
        )
        self.store.append(record.job_id, _STATUS_EVENT[status], code)

    # --- after a restart ---------------------------------------------------------------------

    def reconcile(self, reap_orphans: Callable[[], object] | None = None) -> list[str]:
        """Close jobs a dead process left open. Never resumes or retries. Returns job ids closed."""
        open_jobs = [j for j in self.store.all() if j.status not in TERMINAL_JOB_STATES]
        if not open_jobs:
            # A sandbox can outlive the job that was closed for it, so expired ones go regardless.
            if reap_orphans is not None:
                reap_orphans()
            return []
        try:
            with exclusive(self._investigations):
                return self._reconcile_locked(open_jobs, reap_orphans)
        except InvestigationBusyError:
            # A live investigation elsewhere holds the lock. Its records cannot be judged yet.
            log.warning("reconcile_deferred", extra={"jobs": len(open_jobs)})
            return []

    def _reconcile_locked(
        self, jobs: list[JobRecord], reap_orphans: Callable[[], object] | None
    ) -> list[str]:
        if reap_orphans is not None:
            reap_orphans()
        recovered = recover_interrupted(self._experiments)
        recover_investigations(self._investigations)
        unresolved = {
            e.parent_investigation_id for e in recovered if e.status is ExperimentState.UNCERTAIN
        }
        closed: list[str] = []
        for job in jobs:
            directory = self._investigations / job.investigation_id
            if (directory / REPORT).is_file():
                self._finish(job)  # the report landed; only the job record lagged behind
            elif job.investigation_id in unresolved:
                self._close(job, JobStatus.OUTCOME_UNCERTAIN, "interrupted_target_run_unresolved")
            elif (directory / JOURNAL).is_file():
                self._close(job, JobStatus.FAILED, "interrupted_no_target_run_open")
            else:
                self._close(job, JobStatus.FAILED, "interrupted_before_start")
            closed.append(job.job_id)
        return closed


class _Seen:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_seq = 0


def _result_class(
    investigations: Path, record: JobRecord, payload: Mapping[str, object]
) -> ResultClass | None:
    """The linked record names the observation; its class is in the state file written with it."""
    raw = payload.get("result_class")
    if isinstance(raw, str):
        return ResultClass(raw)
    state = investigations / record.investigation_id / "state.json"
    try:
        body = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for observation in body.get("observations", []):
        if observation.get("observation_id") == payload.get("observation_id"):
            return ResultClass(observation["result_class"])
    return None


def terminal_status(report: InvestigationReport, outcome: ProductOutcome) -> tuple[JobStatus, str]:
    if outcome is ProductOutcome.OUTCOME_UNCERTAIN:
        return JobStatus.OUTCOME_UNCERTAIN, "target_run_unresolved"
    match report.state:
        case InvestigationState.CANCELLED:
            return JobStatus.CANCELLED, "cancelled"
        case InvestigationState.BUDGET_EXHAUSTED:
            return JobStatus.BUDGET_EXHAUSTED, "spend_limit"
        case InvestigationState.FAILED:
            return JobStatus.FAILED, report.termination or "failed"
        case _:
            return JobStatus.COMPLETED, report.termination or report.state.value
