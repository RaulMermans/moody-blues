"""Result of executing one scenario with one executor and evaluating it."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from moody_blues.contracts.oracle import AnyOracleReport
from moody_blues.contracts.world import (
    AnyClaim,
    CommittedChange,
    CustomerRecord,
    ToolResponse,
    WorldChange,
    WorldRecord,
)


class ToolTraceEntry(BaseModel):
    """One call as the executor experienced it (Layer B), linked to its evidence events."""

    model_config = ConfigDict(frozen=True)

    call_seq: int
    tool: str
    arguments: dict[str, JsonValue]
    delivered: ToolResponse
    # Fault kind, only when a fault was actually applied to this call's response.
    fault_injected: str | None
    # ``FaultEffect`` for any targeted fault, applied or skipped (see contracts/scenario.py).
    fault_effect: str | None = None
    event_seqs: list[int]


class RunReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str | None
    scenario_ref: str
    executor: str
    world_id: str
    tool_trace: list[ToolTraceEntry]
    final_state: list[CustomerRecord] | list[WorldRecord]
    committed_changes: list[CommittedChange] | list[WorldChange]
    claim: AnyClaim | None
    claim_event_seq: int
    oracle: AnyOracleReport
    verdict_event_seq: int
    event_count: int
    # sha256 over world outcome with run-specific identifiers removed; equal inputs => equal.
    fingerprint: str
