"""Trusted on-disk workspace for one experiment. Never mounted into or named to a sandbox.

Layout of ``<root>/<experiment_id>/`` (mode 0700)::

    journal.jsonl   append-only write-ahead log, fsynced, hash-chained
    evidence.json   final record, written atomically, hash stored in the journal
    runs/           full target run reports
    worlds/         live world databases; present after a crash, otherwise emptied
    .lock           held while a coordinator owns the experiment

The journal is written *before* each step with possible effects, so a crash leaves a record of
what was underway. The hash chain detects accidental or casual edits. It is not a signature:
anyone able to rewrite the whole file can recompute it.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from pydantic import BaseModel, ConfigDict, JsonValue

JOURNAL = "journal.jsonl"
EVIDENCE = "evidence.json"
GENESIS = "0" * 64


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def atomic_write(path: Path, text: str) -> str:
    """Write, fsync, rename. Returns the sha256 of the content."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)
    return sha256_text(text)


class JournalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    at: datetime
    kind: str
    payload: dict[str, JsonValue]
    prev_sha256: str
    sha256: str


def _record_hash(seq: int, at: str, kind: str, payload: dict[str, Any], prev: str) -> str:
    body = {"seq": seq, "at": at, "kind": kind, "payload": payload, "prev": prev}
    return sha256_text(json.dumps(body, sort_keys=True, separators=(",", ":")))


def read_journal(path: Path) -> tuple[list[JournalRecord], list[str]]:
    """All parseable records, plus any integrity problems found.

    A torn final line is what a crash mid-append looks like: it is reported, not fatal.
    """
    records: list[JournalRecord] = []
    problems: list[str] = []
    prev = GENESIS
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        try:
            record = JournalRecord.model_validate_json(line)
        except ValueError:
            problems.append(f"journal line {number} is not a valid record")
            continue
        at = record.at.isoformat()
        if record.prev_sha256 != prev:
            problems.append(f"journal record {record.seq} does not chain from its predecessor")
        expected = _record_hash(record.seq, at, record.kind, record.payload, record.prev_sha256)
        if record.sha256 != expected:
            problems.append(f"journal record {record.seq} has been altered")
        prev = record.sha256
        records.append(record)
    return records, problems


def append_record(
    path: Path, *, seq: int, at: datetime, kind: str, payload: dict[str, Any], prev: str
) -> str:
    """Append one chained, fsynced record. Returns its hash."""
    body = json.loads(json.dumps(payload, default=str))
    stamp = at.isoformat()
    digest = _record_hash(seq, stamp, kind, body, prev)
    line = json.dumps(
        {
            "seq": seq,
            "at": stamp,
            "kind": kind,
            "payload": body,
            "prev_sha256": prev,
            "sha256": digest,
        },
        separators=(",", ":"),
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    return digest


class ExperimentWorkspace:
    def __init__(self, root: Path, experiment_id: str) -> None:
        self.directory = root / experiment_id
        self.directory.mkdir(parents=True, mode=0o700)
        self.runs_dir = self.directory / "runs"
        self.worlds_dir = self.directory / "worlds"
        self.runs_dir.mkdir(mode=0o700)
        self.worlds_dir.mkdir(mode=0o700)
        self._lock: IO[str] | None = (self.directory / ".lock").open("a", encoding="utf-8")
        fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
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

    def release(self) -> None:
        if self._lock is not None:
            self._lock.close()  # closing drops the flock
            self._lock = None
