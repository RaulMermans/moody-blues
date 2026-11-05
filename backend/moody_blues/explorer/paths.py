"""Where evidence lives. Paths come from settings and are never derived from a request."""

from __future__ import annotations

import os
from pathlib import Path

from moody_blues.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def default_artifacts() -> Path:
    """For module-level paths. A release directory is read-only on a host, so the setting wins."""
    configured = os.environ.get("MOODY_ARTIFACTS_DIR")
    return Path(configured) if configured else REPO_ROOT / ".artifacts"


def artifacts_dir(settings: Settings) -> Path:
    return settings.artifacts_dir or REPO_ROOT / ".artifacts"


def recorded_dir(settings: Settings) -> Path:
    return settings.recorded_evidence_dir or REPO_ROOT / "evidence" / "recorded"


def containment_report_path(settings: Settings) -> Path:
    return settings.containment_report or REPO_ROOT / "evidence" / "containment" / "report.json"
