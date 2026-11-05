"""The finished containment report, read-only. Nothing here runs a sandbox."""

from __future__ import annotations

from fastapi import APIRouter

from moody_blues.api.deps import SettingsDep
from moody_blues.contracts.containment import ContainmentReport
from moody_blues.explorer.containment import read_report
from moody_blues.explorer.paths import containment_report_path

router = APIRouter(prefix="/containment", tags=["containment"])


@router.get("", response_model=ContainmentReport)
def get_containment(settings: SettingsDep) -> ContainmentReport:
    return read_report(containment_report_path(settings))
