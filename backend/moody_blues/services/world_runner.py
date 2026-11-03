"""Orchestrates Scenario -> World -> Gateway (+faults) -> Persistence -> Oracle.

Ordering matters for truth: the executor's claim is recorded *before* the Oracle runs, and
the Oracle evaluates through a fresh read-only connection. The verdict is appended to the
evidence trail afterwards by trusted code; the Oracle itself never writes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from moody_blues.contracts.oracle import OracleReport
from moody_blues.contracts.run import RunReport, ToolTraceEntry
from moody_blues.contracts.scenario import Scenario
from moody_blues.contracts.world import CustomerRecord, EventKind, ToolResponse, WorldEvent
from moody_blues.world.engine import World
from moody_blues.world.oracle import TruthOracle
from moody_blues.world.reference import EXECUTORS, REFERENCE_CASES, Executor, ReferenceCase
from moody_blues.world.scenarios import load_scenario


class UnknownExecutorError(LookupError):
    pass


def resolve_executor(name: str) -> Executor:
    try:
        return EXECUTORS[name]
    except KeyError:
        raise UnknownExecutorError(
            f"unknown executor {name!r}; known: {', '.join(sorted(EXECUTORS))}"
        ) from None


def execute_in_world(world: World, executor_name: str, *, case_id: str | None = None) -> RunReport:
    """Run one executor against an already-initialized world and evaluate the outcome."""
    executor = resolve_executor(executor_name)
    claim = executor(world.gateway, world.scenario.objective)
    claim_seq = world.record_claim(claim)

    with world.view() as view:
        oracle = TruthOracle().evaluate(view, world.scenario, claim)
    verdict_seq = world.record_verdict(oracle)

    with world.view() as view:
        customers = view.all_customers()
        changes = view.committed_changes()
        events = view.events()

    return RunReport(
        case_id=case_id,
        scenario_ref=world.scenario.ref,
        executor=executor_name,
        world_id=world.world_id,
        tool_trace=_trace(events),
        final_state=customers,
        committed_changes=changes,
        claim=claim,
        claim_event_seq=claim_seq,
        oracle=oracle,
        verdict_event_seq=verdict_seq,
        event_count=len(events),
        fingerprint=fingerprint(executor_name, world.scenario, events, customers, oracle),
    )


def run_scenario(
    scenario: Scenario,
    executor_name: str,
    *,
    case_id: str | None = None,
    root_dir: Path | None = None,
    keep: bool = False,
) -> RunReport:
    world = World(scenario, root_dir=root_dir)
    try:
        return execute_in_world(world, executor_name, case_id=case_id)
    finally:
        world.close(remove=not keep)


def run_reference_case(
    case: ReferenceCase, *, root_dir: Path | None = None, keep: bool = False
) -> RunReport:
    return run_scenario(
        load_scenario(case.scenario_id),
        case.executor,
        case_id=case.case_id,
        root_dir=root_dir,
        keep=keep,
    )


def reference_case(case_id: str) -> ReferenceCase:
    for case in REFERENCE_CASES:
        if case.case_id == case_id:
            return case
    raise LookupError(f"unknown reference case {case_id!r}")


def _trace(events: list[WorldEvent]) -> list[ToolTraceEntry]:
    by_call: dict[int, list[WorldEvent]] = {}
    for e in events:
        if e.call_seq is not None:
            by_call.setdefault(e.call_seq, []).append(e)
    entries: list[ToolTraceEntry] = []
    for call_seq, evs in sorted(by_call.items()):
        requested = next(e for e in evs if e.kind is EventKind.TOOL_CALL_REQUESTED)
        delivered = next(e for e in evs if e.kind is EventKind.TOOL_RESPONSE_DELIVERED)
        fault = next((e for e in evs if e.kind is EventKind.FAULT_INJECTED), None)
        args = requested.payload.get("arguments")
        entries.append(
            ToolTraceEntry(
                call_seq=call_seq,
                tool=str(requested.payload["tool"]),
                arguments=args if isinstance(args, dict) else {},
                delivered=ToolResponse.model_validate(delivered.payload["response"]),
                fault_injected=str(fault.payload["kind"]) if fault else None,
                event_seqs=[e.seq for e in evs],
            )
        )
    return entries


def fingerprint(
    executor: str,
    scenario: Scenario,
    events: list[WorldEvent],
    customers: list[CustomerRecord],
    oracle: OracleReport,
) -> str:
    """Canonical hash of a run's deterministic content.

    Includes the scenario ref, executor, full ordered evidence trail (kinds, call seqs,
    logical times, payloads), the final customer rows and the Oracle report. Excludes
    ``world_id`` (random per world), the only run-specific identifier.
    """
    body = {
        "scenario": scenario.ref,
        "executor": executor,
        "events": [e.model_dump(mode="json", exclude={"world_id"}) for e in events],
        "customers": [c.model_dump(mode="json") for c in customers],
        "oracle": oracle.model_dump(mode="json", exclude={"world_id"}),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
