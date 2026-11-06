"""Where evidence lives. Paths come from settings and are never derived from a request."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from moody_blues.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def default_artifacts() -> Path:
    """For module-level paths. A release directory is read-only on a host, so the setting wins."""
    configured = os.environ.get("MOODY_ARTIFACTS_DIR")
    return Path(configured) if configured else REPO_ROOT / ".artifacts"


def artifacts_dir(settings: Settings) -> Path:
    return settings.artifacts_dir or REPO_ROOT / ".artifacts"


def rehearsal_artifacts(settings: Settings) -> Path:
    """Where a free, repeatable command writes. Never canonical evidence by accident.

    Only an explicit ``MOODY_ARTIFACTS_DIR`` picks a real directory. Unset, each run gets a fresh
    scratch one (KI-79): a run that costs nothing is exactly the one nobody thinks about, and
    ``.artifacts`` holds evidence and a ledger that exist nowhere else. Paid commands keep
    ``artifacts_dir``, because a ledger has to stay in one place.
    """
    if settings.artifacts_dir is not None:
        return settings.artifacts_dir
    scratch = Path(tempfile.mkdtemp(prefix="moody-rehearsal-"))
    print(f"MOODY_ARTIFACTS_DIR is not set, so this run writes to {scratch}", file=sys.stderr)
    return scratch


def recorded_dir(settings: Settings) -> Path:
    return settings.recorded_evidence_dir or REPO_ROOT / "evidence" / "recorded"


def containment_report_path(settings: Settings) -> Path:
    return settings.containment_report or REPO_ROOT / "evidence" / "containment" / "report.json"
