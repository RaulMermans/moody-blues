"""An append-only, hash-chained record of a suite. A broken chain stops the suite and its report.

A trial that started and never finished is not retried silently: it stays on the record, counted
as attempted and ineligible, because its effects are unknown.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from moody_blues.evaluation.trials import TrialCategory, TrialRecord

_GENESIS = "0" * 64


class JournalError(RuntimeError):
    """The record cannot be trusted. Nothing further may be run or reported from it."""


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: list[dict[str, JsonValue]] = []
        self._last = _GENESIS
        if path.exists():
            self._load()

    def _load(self) -> None:
        previous = _GENESIS
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, start=1):
                entry = json.loads(line)
                body = {k: v for k, v in entry.items() if k != "sha256"}
                if body.get("previous") != previous or _digest(body) != entry.get("sha256"):
                    raise JournalError(f"{self.path}: chain broken at line {number}")
                previous = str(entry["sha256"])
                self._entries.append(entry)
        except (OSError, ValueError, AttributeError) as exc:
            raise JournalError(f"{self.path}: unreadable: {exc}") from exc
        self._last = previous

    def append(self, kind: str, payload: dict[str, JsonValue]) -> None:
        body: dict[str, JsonValue] = {
            "kind": kind,
            "at": datetime.now(UTC).isoformat(),
            "previous": self._last,
            "payload": payload,
        }
        entry = {**body, "sha256": _digest(body)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._entries.append(entry)
        self._last = str(entry["sha256"])

    def payloads(self, kind: str) -> list[dict[str, JsonValue]]:
        return [e["payload"] for e in self._entries if e["kind"] == kind]  # pyright: ignore[reportReturnType]

    def trials(self) -> list[TrialRecord]:
        return [TrialRecord.model_validate(p) for p in self.payloads("trial")]

    def record_trial(self, trial: TrialRecord) -> None:
        self.append("trial", trial.model_dump(mode="json"))

    def unfinished(self) -> list[dict[str, JsonValue]]:
        finished = {str(p["trial_id"]) for p in self.payloads("trial")}
        finished |= {str(p["id"]) for p in self.payloads("abandoned")}
        return [p for p in self.payloads("started") if str(p["id"]) not in finished]

    def close_unfinished(self, *, suite: str) -> list[TrialRecord]:
        """Record whatever a crash left open, once, before the suite continues."""
        closed: list[TrialRecord] = []
        for started in self.unfinished():
            trial_id = str(started["id"])
            trial = TrialRecord(
                trial_id=trial_id,
                suite=suite,
                unit_id=trial_id,
                block=0,
                condition_id=_text(started.get("condition_id")),
                config=_text(started.get("config")),
                experiment_source="unknown",
                category=TrialCategory.PROVIDER_OR_INFRASTRUCTURE,
                experiment_id="unknown",
                evidence_ref="none: the process stopped before evidence was linked",
            )
            self.record_trial(trial)
            closed.append(trial)
        return closed


def _text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def _digest(body: dict[str, JsonValue]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
