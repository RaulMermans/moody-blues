"""Read-only access to approved evidence.

Ids are never joined into a path. A request id is compared against the manifest and against job
records, and only a file named by one of those is opened, so a crafted id has nothing to reach.
Public callers get the committed recorded bundles. Bundles from operator jobs need operator access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.explorer import (
    ExecutionMode,
    IntegrityState,
    InvestigationBundle,
    InvestigationList,
    ListedInvestigation,
    ManifestEntry,
    RecordedManifest,
)
from moody_blues.experiments.workspace import sha256_text
from moody_blues.explorer.jobs import BUNDLE, JobStore
from moody_blues.explorer.recorded import MANIFEST
from moody_blues.explorer.sanitize import MAX_BUNDLE_BYTES

_INVESTIGATION_ID = re.compile(r"^inv_[0-9a-f]{12}$")
_MAX_PARSED = 64


class EvidenceCorruptError(MoodyBluesError):
    def __init__(self, problem: str) -> None:
        super().__init__(
            ErrorCategory.EVIDENCE_INTEGRITY, f"this record failed verification: {problem}"
        )
        self.problem = problem


def _not_found() -> MoodyBluesError:
    return MoodyBluesError(ErrorCategory.NOT_FOUND, "no such investigation")


@dataclass(frozen=True, slots=True)
class _Check:
    bundle: InvestigationBundle | None
    problem: str | None


class EvidenceStore:
    def __init__(self, recorded_dir: Path, jobs: JobStore) -> None:
        self._recorded = recorded_dir
        self._jobs = jobs
        self._parsed: dict[str, InvestigationBundle] = {}

    def _manifest(self) -> RecordedManifest | None:
        path = self._recorded / MANIFEST
        if not path.is_file():
            return None
        try:
            return RecordedManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError) as exc:
            raise EvidenceCorruptError("manifest_invalid") from exc

    def _parse(
        self,
        path: Path,
        expected_sha256: str | None,
        investigation_id: str,
        mode: set[ExecutionMode],
    ) -> _Check:
        try:
            if not path.is_file():
                return _Check(None, "missing")
            if path.stat().st_size > MAX_BUNDLE_BYTES:
                return _Check(None, "too_large")
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return _Check(None, "unreadable")
        digest = sha256_text(text)
        if expected_sha256 is not None and digest != expected_sha256:
            return _Check(None, "hash_mismatch")
        cached = self._parsed.get(digest)
        if cached is None:
            try:
                cached = InvestigationBundle.model_validate_json(text)
            except ValidationError:
                return _Check(None, "schema_invalid")
            if len(self._parsed) >= _MAX_PARSED:
                self._parsed.clear()
            self._parsed[digest] = cached
        if cached.summary.investigation_id != investigation_id:
            return _Check(None, "id_mismatch")
        if cached.summary.mode not in mode:
            return _Check(None, "mode_mismatch")
        return _Check(cached, None)

    def _check_recorded(self, entry: ManifestEntry) -> _Check:
        return self._parse(
            self._recorded / entry.file,
            entry.bundle_sha256,
            entry.investigation_id,
            {ExecutionMode.RECORDED},
        )

    def _job_items(self) -> list[ListedInvestigation]:
        items: list[ListedInvestigation] = []
        for job in self._jobs.all():
            if not job.evidence_available:
                continue
            check = self._parse(
                self._jobs.directory(job.job_id) / BUNDLE,
                job.bundle_sha256,
                job.investigation_id,
                {ExecutionMode.LIVE, ExecutionMode.REHEARSAL, ExecutionMode.LOCAL},
            )
            items.append(_listed(job.investigation_id, check))
        return items

    def list(self, *, operator: bool) -> InvestigationList:
        manifest = self._manifest()
        items: list[ListedInvestigation] = []
        if operator:
            items.extend(self._job_items())
        if manifest is not None:
            items.extend(
                _listed(e.investigation_id, self._check_recorded(e)) for e in manifest.cases
            )
        return InvestigationList(items=items, study=manifest.study if manifest else None)

    def get(self, investigation_id: str, *, operator: bool) -> InvestigationBundle:
        if not _INVESTIGATION_ID.fullmatch(investigation_id):
            raise _not_found()
        manifest = self._manifest()
        entry = next(
            (
                e
                for e in (manifest.cases if manifest else [])
                if e.investigation_id == investigation_id
            ),
            None,
        )
        if entry is not None:
            return _require(self._check_recorded(entry))
        if operator:
            job = next(
                (j for j in self._jobs.all() if j.investigation_id == investigation_id), None
            )
            if job is not None and job.evidence_available:
                return _require(
                    self._parse(
                        self._jobs.directory(job.job_id) / BUNDLE,
                        job.bundle_sha256,
                        investigation_id,
                        {ExecutionMode.LIVE, ExecutionMode.REHEARSAL, ExecutionMode.LOCAL},
                    )
                )
        raise _not_found()


def _require(check: _Check) -> InvestigationBundle:
    if check.bundle is None:
        raise EvidenceCorruptError(check.problem or "unknown")
    return check.bundle


def _listed(investigation_id: str, check: _Check) -> ListedInvestigation:
    if check.bundle is None:
        return ListedInvestigation(
            investigation_id=investigation_id,
            integrity=IntegrityState.CORRUPT,
            summary=None,
            problem=check.problem,
        )
    return ListedInvestigation(
        investigation_id=investigation_id,
        integrity=IntegrityState.VERIFIED,
        summary=check.bundle.summary,
    )
