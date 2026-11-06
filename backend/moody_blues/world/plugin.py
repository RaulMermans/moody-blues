"""``WorldPlugin``: what shared code may ask of a world, and nothing more.

The coordinator, the Investigator and the evidence layer hold this and never a store. A plugin
supplies a world's tools and invariants. It does not supply limits, budgets, sandbox settings,
verdict semantics or evidence rules: those stay in the shared code that calls it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, JsonValue

from moody_blues.contracts.inference import ToolSpec
from moody_blues.contracts.investigation import TargetCapability
from moody_blues.contracts.oracle import AnyOracleReport
from moody_blues.contracts.scenario import ScenarioBase
from moody_blues.contracts.world import (
    AnyClaim,
    ClaimStatus,
    CommittedChange,
    CustomerRecord,
    ToolErrorCode,
    WorldChange,
    WorldRecord,
)
from moody_blues.contracts.world_plugin import WorldDescriptor
from moody_blues.world.gateway import ToolPort


@dataclass(frozen=True, slots=True)
class WorldTool:
    spec: ToolSpec
    access: Literal["read", "write"]
    scope: str


@dataclass(frozen=True, slots=True)
class WorldState:
    """Read back from authoritative state after a run."""

    records: list[CustomerRecord] | list[WorldRecord]
    changes: list[CommittedChange] | list[WorldChange]


class WorldGateway(ToolPort, Protocol):
    @property
    def calls_made(self) -> int: ...


class WorldRun(Protocol):
    """One isolated instance. ``World`` and ``JobWorld`` are both this."""

    world_id: str
    directory: Path
    db_path: Path
    epoch: int

    @property
    def scenario(self) -> Any: ...
    @property
    def gateway(self) -> WorldGateway: ...
    def view(self) -> AbstractContextManager[Any]: ...
    def reset(self) -> None: ...
    def close(self, *, remove: bool = True) -> None: ...
    def record_claim(self, claim: AnyClaim | None) -> int: ...
    def record_verdict(self, report: AnyOracleReport) -> int: ...


class WorldPlugin(Protocol):
    @property
    def descriptor(self) -> WorldDescriptor: ...
    def handles(self, scenario: ScenarioBase) -> bool: ...

    # Scenarios
    def scenario_ids(self) -> tuple[str, ...]: ...
    def approved_scenarios(self) -> tuple[str, ...]: ...
    def load_scenario(self, scenario_id: str) -> ScenarioBase: ...

    # Lifecycle
    def create_run(
        self, scenario: ScenarioBase, *, root_dir: Path | None = None, world_id: str | None = None
    ) -> WorldRun: ...
    def seed_record_ids(self, scenario: ScenarioBase) -> list[str]: ...
    def new_record_ids(self, db_path: Path, scenario: ScenarioBase) -> list[str]: ...

    # Tools
    def tools(self) -> list[WorldTool]: ...
    def arg_models(self) -> Mapping[str, type[BaseModel]]: ...
    def fault_messages(self) -> Mapping[ToolErrorCode, str]: ...

    # Task context: everything a target is told. Never faults, seeds, paths or expected results.
    def mission(self, scenario: ScenarioBase, *, closing: str) -> str: ...
    def objective_wire(self, scenario: ScenarioBase) -> dict[str, JsonValue]: ...
    def claim(self, status: ClaimStatus, record_ref: str | None, message: str) -> AnyClaim: ...

    # Verification
    def verify(
        self, view: Any, scenario: ScenarioBase, claim: AnyClaim | None
    ) -> AnyOracleReport: ...
    def read_state(self, view: Any) -> WorldState: ...

    # Reference executors, in this repository only
    def executors(self) -> Mapping[str, Any]: ...

    # What the Investigator may be told
    def capability(self, world_ids: Sequence[str]) -> TargetCapability: ...
    def investigator_subject(self) -> str: ...
    def external_task(self) -> str: ...
    def investigation_objective(self) -> str: ...
