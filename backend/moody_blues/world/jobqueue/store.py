"""Authoritative job queue persistence: one SQLite file per world, like the CRM's.

The evidence trail, transactions and read-only enforcement are shared (``world/store.py``). What is
here is what makes it a queue: jobs, the transitions that move them, and the attempts that made
them. A trigger keeps ``job_transitions`` and ``committed_changes`` inside the same transaction as
the row, so a transition exists if and only if it committed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from moody_blues.contracts.job_queue import (
    JobRecord,
    JobStatus,
    JobTransition,
    SubmissionAttempt,
)
from moody_blues.contracts.world import WorldChange
from moody_blues.world.store import SCHEMA_CORE as _CORE
from moody_blues.world.store import (
    BeforeCommit,
    CommitDecision,
    CoreReader,
    ReadOnlyView,
    WorldStore,
    WriteOutcome,
    canonical_json,
)

_JOB_TABLES = """
CREATE TABLE jobs (
    job_id          TEXT PRIMARY KEY CHECK (job_id GLOB 'job_?*'),
    job_type        TEXT NOT NULL CHECK (length(job_type) BETWEEN 2 AND 63),
    payload         TEXT NOT NULL CHECK (json_valid(payload) AND json_type(payload) = 'object'),
    request_key     TEXT UNIQUE,
    status          TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    created_at      TEXT NOT NULL,
    created_by_call INTEGER NOT NULL CHECK (created_by_call >= 0),
    updated_by_call INTEGER NOT NULL CHECK (updated_by_call >= 0)
) STRICT;

CREATE TABLE committed_changes (
    change_seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation       TEXT NOT NULL CHECK (operation IN ('insert', 'update', 'delete')),
    job_id          TEXT NOT NULL,
    created_by_call INTEGER NOT NULL
) STRICT;

CREATE TABLE job_transitions (
    transition_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT NOT NULL,
    from_status    TEXT,
    to_status      TEXT NOT NULL,
    at_call        INTEGER NOT NULL
) STRICT;

CREATE TABLE submission_attempts (
    attempt_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    call_seq    INTEGER NOT NULL,
    request_key TEXT,
    outcome     TEXT NOT NULL
) STRICT;

CREATE TRIGGER jobs_after_insert AFTER INSERT ON jobs BEGIN
    INSERT INTO committed_changes (operation, job_id, created_by_call)
    VALUES ('insert', NEW.job_id, NEW.created_by_call);
    INSERT INTO job_transitions (job_id, from_status, to_status, at_call)
    VALUES (NEW.job_id, NULL, NEW.status, NEW.created_by_call);
END;
CREATE TRIGGER jobs_after_update AFTER UPDATE ON jobs BEGIN
    INSERT INTO committed_changes (operation, job_id, created_by_call)
    VALUES ('update', NEW.job_id, NEW.updated_by_call);
    INSERT INTO job_transitions (job_id, from_status, to_status, at_call)
    SELECT NEW.job_id, OLD.status, NEW.status, NEW.updated_by_call
    WHERE OLD.status <> NEW.status;
END;
CREATE TRIGGER jobs_after_delete AFTER DELETE ON jobs BEGIN
    INSERT INTO committed_changes (operation, job_id, created_by_call)
    VALUES ('delete', OLD.job_id, OLD.updated_by_call);
END;

CREATE TRIGGER changes_append_only_u BEFORE UPDATE ON committed_changes BEGIN
    SELECT RAISE(ABORT, 'committed_changes is append-only');
END;
CREATE TRIGGER changes_append_only_d BEFORE DELETE ON committed_changes BEGIN
    SELECT RAISE(ABORT, 'committed_changes is append-only');
END;
CREATE TRIGGER transitions_append_only_u BEFORE UPDATE ON job_transitions BEGIN
    SELECT RAISE(ABORT, 'job_transitions is append-only');
END;
CREATE TRIGGER transitions_append_only_d BEFORE DELETE ON job_transitions BEGIN
    SELECT RAISE(ABORT, 'job_transitions is append-only');
END;
"""

_SCHEMA = _CORE + _JOB_TABLES

_JOB_COLUMNS = "job_id, job_type, payload, request_key, status, created_at, created_by_call"


@dataclass(frozen=True, slots=True)
class JobInsertResult:
    outcome: WriteOutcome
    # COMMITTED: the new row. IDEMPOTENT_REPLAY/CONFLICT: the existing row. ABORTED: None.
    record: JobRecord | None


def _row_to_job(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=row["job_id"],
        job_type=row["job_type"],
        payload=cast(dict[str, str], json.loads(row["payload"])),
        request_key=row["request_key"],
        status=JobStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        created_by_call=row["created_by_call"],
    )


class _JobReader(CoreReader):
    def get_job(self, job_id: str) -> JobRecord | None:
        row = self._conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE job_id = ?",  # noqa: S608
            (job_id,),
        ).fetchone()
        return _row_to_job(row) if row else None

    def find_by_request_key(self, key: str) -> JobRecord | None:
        row = self._conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE request_key = ?",  # noqa: S608
            (key,),
        ).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(
        self, *, job_type: str | None = None, request_key: str | None = None, limit: int = 100
    ) -> list[JobRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if job_type is not None:
            clauses.append("job_type = ?")
            params.append(job_type)
        if request_key is not None:
            clauses.append("request_key = ?")
            params.append(request_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs {where} "  # noqa: S608 - fixed fragments
            "ORDER BY created_by_call, job_id LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    def all_jobs(self) -> list[JobRecord]:
        rows = self._conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs ORDER BY created_by_call, job_id"  # noqa: S608
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    def transitions(self) -> list[JobTransition]:
        rows = self._conn.execute(
            "SELECT transition_seq, job_id, from_status, to_status, at_call "
            "FROM job_transitions ORDER BY transition_seq"
        ).fetchall()
        return [JobTransition(**dict(r)) for r in rows]

    def status_at_commit(self, job_id: str) -> JobStatus | None:
        """The first status recorded for a job: what a replica lagging since then would show."""
        row = self._conn.execute(
            "SELECT to_status FROM job_transitions WHERE job_id = ? "
            "ORDER BY transition_seq LIMIT 1",
            (job_id,),
        ).fetchone()
        return JobStatus(row["to_status"]) if row else None

    def attempts(self) -> list[SubmissionAttempt]:
        rows = self._conn.execute(
            "SELECT attempt_seq, call_seq, request_key, outcome "
            "FROM submission_attempts ORDER BY attempt_seq"
        ).fetchall()
        return [SubmissionAttempt(**dict(r)) for r in rows]

    def committed_changes(self) -> list[WorldChange]:
        rows = self._conn.execute(
            "SELECT change_seq, operation, job_id, created_by_call "
            "FROM committed_changes ORDER BY change_seq"
        ).fetchall()
        return [
            WorldChange(
                change_seq=r["change_seq"],
                operation=r["operation"],
                record_id=r["job_id"],
                created_by_call=r["created_by_call"],
            )
            for r in rows
        ]


def _insert(conn: sqlite3.Connection, record: JobRecord) -> None:
    conn.execute(
        "INSERT INTO jobs (job_id, job_type, payload, request_key, status, created_at, "
        "created_by_call, updated_by_call) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.job_id,
            record.job_type,
            canonical_json(record.payload),
            record.request_key,
            record.status.value,
            record.created_at.isoformat(),
            record.created_by_call,
            record.created_by_call,
        ),
    )


class JobStore(WorldStore, _JobReader):
    """The queue's authoritative state. Used by world setup, the gateway and the worker only."""

    SCHEMA = _SCHEMA

    def seed_jobs(self, records: list[JobRecord]) -> None:
        with self.transaction() as conn:
            for record in records:
                _insert(conn, record)

    def insert_job(self, record: JobRecord, *, before_commit: BeforeCommit) -> JobInsertResult:
        """Insert one job atomically, honouring request keys, as ``CrmStore.insert_customer``."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if record.request_key is not None:
                existing = self.find_by_request_key(record.request_key)
                if existing is not None:
                    self._conn.execute("ROLLBACK")
                    same = (existing.job_type, existing.payload) == (
                        record.job_type,
                        record.payload,
                    )
                    outcome = (
                        WriteOutcome.IDEMPOTENT_REPLAY
                        if same
                        else WriteOutcome.IDEMPOTENCY_CONFLICT
                    )
                    return JobInsertResult(outcome, existing)
            _insert(self._conn, record)
            decision = before_commit()
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        if decision is CommitDecision.ABORT:
            self._conn.execute("ROLLBACK")
            return JobInsertResult(WriteOutcome.ABORTED_PRE_COMMIT, None)
        self._conn.execute("COMMIT")
        return JobInsertResult(WriteOutcome.COMMITTED, record)

    def record_attempt(self, *, call_seq: int, request_key: str | None, outcome: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO submission_attempts (call_seq, request_key, outcome) VALUES (?, ?, ?)",
                (call_seq, request_key, outcome),
            )

    def advance(self, job_id: str, status: JobStatus, *, call_seq: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_by_call = ? WHERE job_id = ?",
                (status.value, call_seq, job_id),
            )


class ReadOnlyJobView(ReadOnlyView, _JobReader):
    """The queue through a read-only connection. The job verifier uses only this."""
