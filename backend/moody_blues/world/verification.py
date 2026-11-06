"""The one way any world is verified. Coordinates the Oracle; holds no world's rules.

Each world's verifier reads its own authoritative state through a read-only view. What this adds is
what no world may change: a verifier that cannot read is an error, never a verdict, and a report
whose verdict disagrees with its own findings is refused, so a plugin cannot redefine what PASS,
VIOLATION or INCONCLUSIVE mean.
"""

from __future__ import annotations

import sqlite3

from pydantic import ValidationError

from moody_blues.contracts.oracle import AnyOracleReport, Severity, derive_verdict
from moody_blues.contracts.world import AnyClaim
from moody_blues.world.plugin import WorldRun
from moody_blues.world.registry import plugin_for


class OracleVerificationError(RuntimeError):
    """The Oracle could not reach a verdict. Never reported as a verdict."""


def verify_world(world: WorldRun, claim: AnyClaim | None) -> AnyOracleReport:
    plugin = plugin_for(world.scenario)
    try:
        with world.view() as view:
            report = plugin.verify(view, world.scenario, claim)
    except (sqlite3.Error, ValidationError, KeyError, TypeError) as exc:
        raise OracleVerificationError(f"{type(exc).__name__} while verifying") from exc
    check_report(report, world_id=world.world_id, scenario_ref=world.scenario.ref, claim=claim)
    return report


def check_report(
    report: AnyOracleReport, *, world_id: str, scenario_ref: str, claim: AnyClaim | None
) -> None:
    if report.world_id != world_id or report.scenario_ref != scenario_ref:
        raise OracleVerificationError("the report describes a different world")
    if report.claim != claim:
        raise OracleVerificationError("the report does not carry the claim it was given")
    expected = derive_verdict(
        violated=any(f.severity is Severity.VIOLATION for f in report.findings),
        objective_satisfied=report.objective_satisfied,
        claim=claim,
    )
    if report.verdict is not expected:
        raise OracleVerificationError("the verdict disagrees with the report's own findings")
