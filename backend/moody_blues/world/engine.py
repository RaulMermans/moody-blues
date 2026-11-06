"""World lifecycle: instantiate from a scenario, expose the gateway, reset, clean up.

Isolation model: every world is its own directory containing its own SQLite file. Nothing
mutable is shared between worlds: no module-level state, no shared connection, no shared
fault counters. Record ids derive from ``(scenario.seed, call_seq)`` and timestamps from a
logical clock, so equal inputs yield equal state regardless of wall-clock time or world id.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from uuid import uuid4

from moody_blues.contracts.oracle import AnyOracleReport
from moody_blues.contracts.scenario import Scenario, ScenarioBase
from moody_blues.contracts.world import AnyClaim, CustomerRecord, EventKind
from moody_blues.world.gateway import GatewayCore, ToolGateway
from moody_blues.world.store import (
    DB_FILENAME,
    CrmStore,
    ReadOnlyView,
    ReadOnlyWorldView,
    WorldStore,
)


class WorldClosedError(RuntimeError):
    pass


class WorldBase[
    ScenarioT: ScenarioBase,
    StoreT: WorldStore,
    ViewT: ReadOnlyView,
    GatewayT: GatewayCore,
]:
    """One isolated, stateful world built from a scenario. Trusted-side handle.

    Directory, lifecycle, logical time and trusted evidence are the same in every world. A world
    says only how its store is seeded and which gateway and read-only view it has.
    """

    def __init__(
        self,
        scenario: ScenarioT,
        *,
        root_dir: Path | None = None,
        world_id: str | None = None,
    ) -> None:
        self.scenario = scenario
        self.world_id = world_id or f"wld_{uuid4().hex[:12]}"
        self._owns_root = root_dir is None
        base = Path(tempfile.mkdtemp(prefix="moody-world-")) if root_dir is None else root_dir
        self.directory = base / self.world_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.db_path = self.directory / DB_FILENAME
        self._store: StoreT | None = None
        self._gateway: GatewayT | None = None
        self.epoch = 0
        self._initialize()

    # --- lifecycle ------------------------------------------------------------------------

    def _meta(self) -> dict[str, str]:
        s = self.scenario
        return {
            "world_id": self.world_id,
            "scenario_id": s.scenario_id,
            "scenario_version": s.version,
            "seed": str(s.seed),
            "epoch": str(self.epoch),
        }

    def _initialize(self) -> None:
        raise NotImplementedError

    def clock(self, call_seq: int) -> datetime:
        c = self.scenario.clock
        return c.start + timedelta(seconds=c.tick_seconds * call_seq)

    def reset(self) -> None:
        """Discard all state and evidence and rebuild the scenario's initial conditions."""
        self._require_open().close()
        self.db_path.unlink()
        for leftover in self.directory.glob(f"{DB_FILENAME}-*"):  # journal files, if any
            leftover.unlink()
        self.epoch += 1
        self._initialize()

    def close(self, *, remove: bool = True) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
            self._gateway = None
        if remove:
            shutil.rmtree(self.directory if not self._owns_root else self.directory.parent)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # --- access ---------------------------------------------------------------------------

    def _require_open(self) -> StoreT:
        if self._store is None:
            raise WorldClosedError(f"world {self.world_id} is closed")
        return self._store

    @property
    def gateway(self) -> GatewayT:
        """The agent-facing port. Hand executors this (as a ``ToolPort``), nothing else."""
        self._require_open()
        if self._gateway is None:  # pragma: no cover - set together with the store
            raise WorldClosedError(f"world {self.world_id} has no gateway")
        return self._gateway

    def view(self) -> ViewT:
        """A fresh read-only connection to authoritative state."""
        raise NotImplementedError

    # --- trusted evidence -----------------------------------------------------------------

    def _after_last_call(self) -> tuple[int, datetime]:
        n = self.gateway.calls_made
        return n, self.clock(n + 1)

    def record_claim(self, claim: AnyClaim | None) -> int:
        _, t = self._after_last_call()
        payload: dict[str, Any] = {
            "claim": claim.model_dump(mode="json") if claim is not None else None
        }
        return self._require_open().append_event(
            EventKind.FINAL_CLAIM, call_seq=None, logical_time=t, payload=payload
        )

    def record_verdict(self, report: AnyOracleReport) -> int:
        _, t = self._after_last_call()
        return self._require_open().append_event(
            EventKind.ORACLE_VERDICT,
            call_seq=None,
            logical_time=t,
            payload={
                "verdict": report.verdict.value,
                "objective_satisfied": report.objective_satisfied,
                "invariants_violated": [str(i) for i in report.invariants_violated],
                "finding_codes": [str(f.code) for f in report.findings],
            },
        )


class World(WorldBase[Scenario, CrmStore, ReadOnlyWorldView, ToolGateway]):
    """One CRM."""

    def _initialize(self) -> None:
        s = self.scenario
        store = CrmStore.initialize(self.db_path, meta=self._meta())
        seeds = [
            CustomerRecord(
                customer_id=c.customer_id,
                name=c.name,
                email=c.email,
                metadata=c.metadata,
                client_request_id=c.client_request_id,
                created_at=s.clock.start,
                created_by_call=0,
            )
            for c in s.initial_state.customers
        ]
        store.seed_customers(seeds)
        store.append_event(
            EventKind.WORLD_INITIALIZED,
            call_seq=None,
            logical_time=s.clock.start,
            payload={
                "scenario_ref": s.ref,
                "seed_customer_ids": [c.customer_id for c in seeds],
                "faults": [f.model_dump(mode="json") for f in s.faults],
            },
        )
        self._store = store
        self._gateway = ToolGateway(store, seed=s.seed, faults=list(s.faults), clock=self.clock)

    def view(self) -> ReadOnlyWorldView:
        self._require_open()
        return ReadOnlyWorldView(self.db_path)
