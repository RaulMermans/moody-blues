"""Authoritative CRM persistence (Layer A): one SQLite file per world.

Two access paths exist and they are deliberately different objects:

- ``CrmStore`` — the single read-write connection, owned by the world and used only by
  trusted code (world initialization and the tool gateway). Writes run in explicit
  ``BEGIN IMMEDIATE`` transactions with a *pre-commit boundary*: a callback that can abort
  the transaction after the write is staged but before it is committed.
- ``ReadOnlyWorldView`` — a separate connection opened with ``mode=ro`` and
  ``PRAGMA query_only``. SQLite itself refuses writes through it. The Truth Oracle uses only
  this path.

Defense in depth lives in the schema: CHECK constraints mirror the Pydantic validation, a
trigger-maintained ``committed_changes`` journal records every row change inside the same
transaction (so it exists iff the change committed), and both journals are append-only.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from moody_blues.contracts.world import (
    CommittedChange,
    CustomerDraft,
    CustomerRecord,
    EventKind,
    WorldEvent,
)

DB_FILENAME = "world.sqlite3"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE world_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE customers (
    customer_id       TEXT PRIMARY KEY CHECK (customer_id GLOB 'cus_?*'),
    name              TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    email             TEXT NOT NULL CHECK (email = lower(email) AND instr(email, '@') > 1),
    metadata          TEXT NOT NULL CHECK (json_valid(metadata)
                                           AND json_type(metadata) = 'object'),
    client_request_id TEXT UNIQUE,
    created_at        TEXT NOT NULL,
    created_by_call   INTEGER NOT NULL CHECK (created_by_call >= 0)
) STRICT;

CREATE INDEX customers_email ON customers (email);

CREATE TABLE committed_changes (
    change_seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation       TEXT NOT NULL CHECK (operation IN ('insert', 'update', 'delete')),
    customer_id     TEXT NOT NULL,
    created_by_call INTEGER NOT NULL
) STRICT;

CREATE TRIGGER customers_after_insert AFTER INSERT ON customers BEGIN
    INSERT INTO committed_changes (operation, customer_id, created_by_call)
    VALUES ('insert', NEW.customer_id, NEW.created_by_call);
END;
CREATE TRIGGER customers_after_update AFTER UPDATE ON customers BEGIN
    INSERT INTO committed_changes (operation, customer_id, created_by_call)
    VALUES ('update', NEW.customer_id, NEW.created_by_call);
END;
CREATE TRIGGER customers_after_delete AFTER DELETE ON customers BEGIN
    INSERT INTO committed_changes (operation, customer_id, created_by_call)
    VALUES ('delete', OLD.customer_id, OLD.created_by_call);
END;

CREATE TABLE events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    call_seq     INTEGER,
    logical_time TEXT NOT NULL,
    payload      TEXT NOT NULL CHECK (json_valid(payload))
) STRICT;

CREATE TRIGGER events_append_only_u BEFORE UPDATE ON events BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;
CREATE TRIGGER events_append_only_d BEFORE DELETE ON events BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;
CREATE TRIGGER changes_append_only_u BEFORE UPDATE ON committed_changes BEGIN
    SELECT RAISE(ABORT, 'committed_changes is append-only');
END;
CREATE TRIGGER changes_append_only_d BEFORE DELETE ON committed_changes BEGIN
    SELECT RAISE(ABORT, 'committed_changes is append-only');
END;
"""

_CUSTOMER_COLUMNS = (
    "customer_id, name, email, metadata, client_request_id, created_at, created_by_call"
)


class CommitDecision(StrEnum):
    COMMIT = "commit"
    ABORT = "abort"


class WriteOutcome(StrEnum):
    COMMITTED = "committed"
    # Staged, then rolled back at the pre-commit boundary (e.g. a phantom_success fault).
    ABORTED_PRE_COMMIT = "aborted_pre_commit"
    # Same client_request_id and identical attributes: the existing record is returned.
    IDEMPOTENT_REPLAY = "idempotent_replay"
    # Same client_request_id with different attributes: rejected, nothing written.
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


@dataclass(frozen=True, slots=True)
class InsertResult:
    outcome: WriteOutcome
    # COMMITTED: the new row. IDEMPOTENT_REPLAY/CONFLICT: the existing row. ABORTED: None.
    record: CustomerRecord | None


BeforeCommit = Callable[[], CommitDecision]


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _row_to_customer(row: sqlite3.Row) -> CustomerRecord:
    return CustomerRecord(
        customer_id=row["customer_id"],
        name=row["name"],
        email=row["email"],
        metadata=cast(dict[str, str], json.loads(row["metadata"])),
        client_request_id=row["client_request_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        created_by_call=row["created_by_call"],
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class _Reader:
    """SQL shared by the writer and the read-only view. Every method is a pure read."""

    _conn: sqlite3.Connection

    def get_customer(self, customer_id: str) -> CustomerRecord | None:
        row = self._conn.execute(
            f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE customer_id = ?",  # noqa: S608
            (customer_id,),
        ).fetchone()
        return _row_to_customer(row) if row else None

    def find_by_client_request_id(self, key: str) -> CustomerRecord | None:
        row = self._conn.execute(
            f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE client_request_id = ?",  # noqa: S608
            (key,),
        ).fetchone()
        return _row_to_customer(row) if row else None

    def search_customers(
        self, *, email: str | None = None, name_contains: str | None = None, limit: int = 100
    ) -> list[CustomerRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if email is not None:
            clauses.append("email = ?")
            params.append(email.strip().lower())
        if name_contains is not None:
            clauses.append("name LIKE ? ESCAPE '\\' COLLATE NOCASE")
            params.append(f"%{_escape_like(name_contains)}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT {_CUSTOMER_COLUMNS} FROM customers {where} "  # noqa: S608 - fixed fragments
            "ORDER BY created_by_call, customer_id LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_row_to_customer(r) for r in rows]

    def all_customers(self) -> list[CustomerRecord]:
        rows = self._conn.execute(
            f"SELECT {_CUSTOMER_COLUMNS} FROM customers "  # noqa: S608
            "ORDER BY created_by_call, customer_id"
        ).fetchall()
        return [_row_to_customer(r) for r in rows]

    def count_customers(self) -> int:
        return int(self._conn.execute("SELECT count(*) FROM customers").fetchone()[0])

    def meta(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM world_meta").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def events(self) -> list[WorldEvent]:
        world_id = self.meta()["world_id"]
        rows = self._conn.execute(
            "SELECT seq, kind, call_seq, logical_time, payload FROM events ORDER BY seq"
        ).fetchall()
        return [
            WorldEvent(
                seq=r["seq"],
                world_id=world_id,
                kind=EventKind(r["kind"]),
                call_seq=r["call_seq"],
                logical_time=datetime.fromisoformat(r["logical_time"]),
                payload=cast(dict[str, JsonValue], json.loads(r["payload"])),
            )
            for r in rows
        ]

    def committed_changes(self) -> list[CommittedChange]:
        rows = self._conn.execute(
            "SELECT change_seq, operation, customer_id, created_by_call "
            "FROM committed_changes ORDER BY change_seq"
        ).fetchall()
        return [CommittedChange(**dict(r)) for r in rows]


def _connect(target: str, *, uri: bool = False) -> sqlite3.Connection:
    # isolation_level=None: no implicit transactions; every write transaction is explicit.
    conn = sqlite3.connect(target, uri=uri, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


class CrmStore(_Reader):
    """The single read-write handle on a world's authoritative state. Trusted code only."""

    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self._conn = conn
        self.path = path

    @classmethod
    def initialize(cls, path: Path, *, meta: dict[str, str]) -> CrmStore:
        if path.exists():
            raise FileExistsError(f"world database already exists: {path}")
        conn = _connect(str(path))
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA synchronous = FULL")
        store = cls(conn, path)
        with store.transaction():
            for statement in _split_sql(_SCHEMA):
                conn.execute(statement)
            conn.executemany(
                "INSERT INTO world_meta (key, value) VALUES (?, ?)",
                sorted((meta | {"schema_version": str(SCHEMA_VERSION)}).items()),
            )
        return store

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """BEGIN IMMEDIATE ... COMMIT, rolling back on *any* exception and re-raising it."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def seed_customers(self, records: list[CustomerRecord]) -> None:
        with self.transaction() as conn:
            for record in records:
                _insert_row(conn, record)

    def insert_customer(
        self, record: CustomerRecord, *, before_commit: BeforeCommit | None = None
    ) -> InsertResult:
        """Insert one customer atomically, honouring idempotency keys.

        ``before_commit`` runs after the row is staged and before COMMIT. Returning
        ``ABORT`` rolls the transaction back; raising rolls back and propagates.
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if record.client_request_id is not None:
                existing = self.find_by_client_request_id(record.client_request_id)
                if existing is not None:
                    self._conn.execute("ROLLBACK")
                    same = _same_attributes(existing, record)
                    outcome = (
                        WriteOutcome.IDEMPOTENT_REPLAY
                        if same
                        else WriteOutcome.IDEMPOTENCY_CONFLICT
                    )
                    return InsertResult(outcome, existing)
            _insert_row(self._conn, record)
            decision = before_commit() if before_commit is not None else CommitDecision.COMMIT
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        if decision is CommitDecision.ABORT:
            self._conn.execute("ROLLBACK")
            return InsertResult(WriteOutcome.ABORTED_PRE_COMMIT, None)
        self._conn.execute("COMMIT")
        return InsertResult(WriteOutcome.COMMITTED, record)

    def append_event(
        self,
        kind: EventKind,
        *,
        call_seq: int | None,
        logical_time: datetime,
        payload: dict[str, Any],
    ) -> int:
        """Append one evidence event in its own committed transaction; returns its ``seq``."""
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO events (kind, call_seq, logical_time, payload) VALUES (?, ?, ?, ?)",
                (kind.value, call_seq, logical_time.isoformat(), _dumps(payload)),
            )
        seq = cur.lastrowid
        if seq is None:  # pragma: no cover - sqlite always sets it for a rowid table
            raise RuntimeError("sqlite did not report an event seq")
        return seq

    def close(self) -> None:
        self._conn.close()


class ReadOnlyWorldView(_Reader):
    """Read-only handle enforced by SQLite (``mode=ro`` + ``query_only``), not by convention."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"world database not found: {path}")
        self._conn = _connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        self._conn.execute("PRAGMA query_only = ON")
        self.path = path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ReadOnlyWorldView:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _insert_row(conn: sqlite3.Connection, record: CustomerRecord) -> None:
    conn.execute(
        f"INSERT INTO customers ({_CUSTOMER_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",  # noqa: S608
        (
            record.customer_id,
            record.name,
            record.email,
            _dumps(record.metadata),
            record.client_request_id,
            record.created_at.isoformat(),
            record.created_by_call,
        ),
    )


def _same_attributes(existing: CustomerRecord, requested: CustomerRecord) -> bool:
    return (existing.name, existing.email, existing.metadata) == (
        requested.name,
        requested.email,
        requested.metadata,
    )


def draft_matches(record: CustomerRecord, draft: CustomerDraft) -> bool:
    """Objective attribute match: same name and email; draft metadata is a subset."""
    return (
        record.name == draft.name
        and record.email == draft.email
        and all(record.metadata.get(k) == v for k, v in draft.metadata.items())
    )


def _split_sql(script: str) -> list[str]:
    """Split the fixed schema script into statements, keeping trigger bodies intact."""
    statements: list[str] = []
    buf: list[str] = []
    for line in script.strip().splitlines():
        buf.append(line)
        text = "\n".join(buf).strip()
        if text.endswith(";") and sqlite3.complete_statement(text):
            statements.append(text)
            buf = []
    if "".join(buf).strip():
        raise ValueError("unterminated schema statement")
    return statements
