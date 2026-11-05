"""The closed list of things an operator may start.

There is no way to supply code, a world, a fault, a limit or a model through the API: a mission id
selects one of these rows and everything else is fixed here. Reserved and evaluation worlds are not
offered, because their results have registered meaning.
"""

from __future__ import annotations

from dataclasses import dataclass

from moody_blues.contracts.explorer import ExecutionMode
from moody_blues.contracts.investigation import InvestigationLimits, Strategy, WorldTier


@dataclass(frozen=True, slots=True)
class Mission:
    mission_id: str
    mode: ExecutionMode
    title: str
    description: str
    worlds: tuple[str, ...]
    tier: WorldTier
    strategy: Strategy
    limits: InvestigationLimits
    reference_executor: str | None = None  # rehearsals only


_REHEARSAL_LIMITS = InvestigationLimits(max_experiments=2, max_model_calls=3, max_wall_seconds=120)

MISSIONS: tuple[Mission, ...] = (
    Mission(
        mission_id="rehearsal-recovery",
        mode=ExecutionMode.REHEARSAL,
        title="Rehearsal: careful script",
        description=(
            "Free. Real sandboxes, world and Oracle, driven by a labeled fixture and a reference "
            "script that verifies before reporting. No model runs."
        ),
        worlds=("normal-success",),
        tier=WorldTier.DEVELOPMENT,
        strategy=Strategy.ADAPTIVE,
        limits=_REHEARSAL_LIMITS,
        reference_executor="verify_then_report",
    ),
    Mission(
        mission_id="rehearsal-blind-retry",
        mode=ExecutionMode.REHEARSAL,
        title="Rehearsal: blind retry script",
        description=(
            "Free. The same real pipeline against a reference script that retries blindly, so the "
            "Oracle has a violation to find. No model runs."
        ),
        worlds=("normal-success",),
        tier=WorldTier.DEVELOPMENT,
        strategy=Strategy.ADAPTIVE,
        limits=_REHEARSAL_LIMITS,
        reference_executor="blind_retry",
    ),
    Mission(
        mission_id="live-validation-adaptive",
        mode=ExecutionMode.LIVE,
        title="Live: adaptive investigation",
        description=(
            "Chargeable. One real model-driven investigation on the validation worlds, at most "
            "three experiments, inside the spend ledger."
        ),
        worlds=("w-v1", "w-v2", "w-v3"),
        tier=WorldTier.VALIDATION,
        strategy=Strategy.ADAPTIVE,
        limits=InvestigationLimits(),
    ),
)


def find_mission(mission_id: str) -> Mission | None:
    return next((m for m in MISSIONS if m.mission_id == mission_id), None)
