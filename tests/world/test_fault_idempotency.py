"""C3-B regression tests: fault labels, idempotency and transaction outcomes stay consistent.

Sprint 2 defect (found in source review): a fault targeted at an idempotent replay was
labeled as if a new write had reached its commit boundary. ``phantom_failure`` on a replay was
recorded as ``post_commit`` although nothing committed during the call, and
``phantom_success`` on a replay fabricated a *new* never-committed id and was recorded as a
``pre_commit`` abort although no row was ever staged.

Intended semantics (docs/architecture/world-engine.md, "Fault effects"):

| real outcome of the call | phantom_failure                        | phantom_success           |
|--------------------------|----------------------------------------|---------------------------|
| new write committed      | committed_write_reported_as_failure    | (n/a: aborted instead)    |
| new write staged         | (n/a: committed)                       | aborted_new_write         |
| idempotent replay        | response_replaced_without_new_commit   | not_applied_no_new_write  |
| idempotency conflict     | response_replaced_without_new_commit   | not_applied_no_new_write  |
| transaction failed       | response_replaced_without_new_commit   | not_applied_no_new_write  |
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from moody_blues.contracts.world import EventKind, ToolErrorCode, WorldEvent
from moody_blues.services.world_runner import tool_trace
from moody_blues.world.engine import World
from moody_blues.world.oracle import TruthOracle
from moody_blues.world.store import CrmStore
from tests.world.conftest import create, customer_id, make_scenario, snapshot

KEY = "req-abcdef12"


def _call_events(w: World, call_seq: int) -> list[WorldEvent]:
    with w.view() as view:
        return [e for e in view.events() if e.call_seq == call_seq]


def _one(events: list[WorldEvent], *kinds: EventKind) -> WorldEvent:
    matches = [e for e in events if e.kind in kinds]
    assert len(matches) == 1, [e.kind for e in events]
    return matches[0]


def _commits_by_call(w: World, call_seq: int) -> int:
    with w.view() as view:
        return sum(1 for c in view.committed_changes() if c.created_by_call == call_seq)


def _world(world_factory: Any, kind: str, occurrence: int) -> World:
    return world_factory(make_scenario(faults=[{"kind": kind, "occurrence": occurrence}]))


# --- the normal Sprint 2 behaviour is preserved ------------------------------------------------


def test_phantom_failure_on_new_write_is_labeled_post_commit(world_factory: Any) -> None:
    w = _world(world_factory, "phantom_failure", 1)
    r = create(w)
    assert not r.ok
    events = _call_events(w, 1)
    fault = _one(events, EventKind.FAULT_INJECTED)
    assert fault.payload["boundary"] == "post_commit"
    assert fault.payload["effect"] == "committed_write_reported_as_failure"
    assert fault.payload["new_commit"] is True
    assert fault.payload["call_outcome"] == "committed"
    assert _one(events, EventKind.OPERATION_EXECUTED).payload["new_commit"] is True
    assert _commits_by_call(w, 1) == 1


def test_phantom_success_on_new_write_is_labeled_pre_commit(world_factory: Any) -> None:
    w = _world(world_factory, "phantom_success", 1)
    r = create(w)
    assert r.ok
    events = _call_events(w, 1)
    fault = _one(events, EventKind.FAULT_INJECTED)
    assert fault.payload["boundary"] == "pre_commit"
    assert fault.payload["effect"] == "aborted_new_write"
    assert fault.payload["new_commit"] is False
    assert fault.payload["call_outcome"] == "aborted_pre_commit"
    assert _commits_by_call(w, 1) == 0


# --- idempotent replay -------------------------------------------------------------------------


def test_phantom_failure_on_replay_is_response_only_and_claims_no_commit(
    world_factory: Any,
) -> None:
    w = _world(world_factory, "phantom_failure", 2)
    original = customer_id(create(w, client_request_id=KEY))
    before = snapshot(w)

    r = create(w, client_request_id=KEY)

    assert not r.ok
    assert r.error is not None
    assert r.error.code is ToolErrorCode.TIMEOUT
    assert snapshot(w) == before
    assert _commits_by_call(w, 2) == 0
    events = _call_events(w, 2)
    executed = _one(events, EventKind.OPERATION_EXECUTED)
    assert executed.payload["outcome"] == "idempotent_replay"
    assert executed.payload["new_commit"] is False
    assert executed.payload["result_customer_id"] == original
    fault = _one(events, EventKind.FAULT_INJECTED)
    assert fault.payload["boundary"] == "response"
    assert fault.payload["effect"] == "response_replaced_without_new_commit"
    assert fault.payload["new_commit"] is False
    assert fault.payload["call_outcome"] == "idempotent_replay"


def test_phantom_success_on_replay_is_not_applied(world_factory: Any) -> None:
    w = _world(world_factory, "phantom_success", 2)
    original = customer_id(create(w, client_request_id=KEY))
    before = snapshot(w)

    r = create(w, client_request_id=KEY)

    # The genuine replay response, with the *original* id. No new id is fabricated.
    assert r.ok
    assert r.data is not None
    assert r.data["idempotent_replay"] is True
    assert customer_id(r) == original
    assert snapshot(w) == before
    events = _call_events(w, 2)
    assert not [e for e in events if e.kind is EventKind.FAULT_INJECTED]
    skipped = _one(events, EventKind.FAULT_SKIPPED)
    assert skipped.payload["effect"] == "not_applied_no_new_write"
    assert skipped.payload["boundary"] is None
    assert skipped.payload["new_commit"] is False
    assert skipped.payload["call_outcome"] == "idempotent_replay"


def test_skipped_fault_does_not_carry_over_to_the_next_new_write(world_factory: Any) -> None:
    w = _world(world_factory, "phantom_success", 2)
    create(w, client_request_id=KEY)
    create(w, client_request_id=KEY)  # occurrence 2: replay, fault skipped
    third = create(w, client_request_id="req-other-0001")  # occurrence 3: normal
    with w.view() as view:
        assert view.get_customer(customer_id(third)) is not None
    assert not [e for e in _call_events(w, 3) if e.kind is EventKind.FAULT_INJECTED]


# --- idempotency conflict ----------------------------------------------------------------------


def test_phantom_success_on_conflict_is_not_applied(world_factory: Any) -> None:
    w = _world(world_factory, "phantom_success", 2)
    create(w, client_request_id=KEY)
    r = create(w, client_request_id=KEY, name="Someone Else")
    assert r.error is not None
    assert r.error.code is ToolErrorCode.IDEMPOTENCY_CONFLICT
    skipped = _one(_call_events(w, 2), EventKind.FAULT_SKIPPED)
    assert skipped.payload["call_outcome"] == "idempotency_conflict"


def test_phantom_failure_on_conflict_is_response_only(world_factory: Any) -> None:
    w = _world(world_factory, "phantom_failure", 2)
    create(w, client_request_id=KEY)
    before = snapshot(w)
    r = create(w, client_request_id=KEY, name="Someone Else")
    assert r.error is not None
    assert r.error.code is ToolErrorCode.TIMEOUT
    assert snapshot(w) == before
    fault = _one(_call_events(w, 2), EventKind.FAULT_INJECTED)
    assert fault.payload["effect"] == "response_replaced_without_new_commit"
    assert fault.payload["call_outcome"] == "idempotency_conflict"
    actual = fault.payload["actual_response"]
    assert isinstance(actual, dict)
    error = actual["error"]
    assert isinstance(error, dict)
    assert error["code"] == "idempotency_conflict"


# --- genuine transaction failure ---------------------------------------------------------------


@pytest.mark.parametrize("kind", ["phantom_success", "phantom_failure"])
def test_fault_on_genuine_transaction_failure_claims_no_commit(
    world_factory: Any, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(world_factory, kind, 1)

    def broken_insert(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("disk I/O error (simulated)")

    monkeypatch.setattr(CrmStore, "insert_customer", broken_insert)
    r = create(w)
    assert not r.ok
    events = _call_events(w, 1)
    assert _one(events, EventKind.OPERATION_EXECUTED).payload["outcome"] == "transaction_failed"
    fault = _one(events, EventKind.FAULT_INJECTED, EventKind.FAULT_SKIPPED)
    assert fault.payload["new_commit"] is False
    assert fault.payload["call_outcome"] == "transaction_failed"
    if kind == "phantom_success":
        assert fault.kind is EventKind.FAULT_SKIPPED
        assert r.error is not None
        assert r.error.code is ToolErrorCode.INTERNAL_ERROR  # the honest error
    else:
        assert fault.payload["effect"] == "response_replaced_without_new_commit"


# --- trace and Oracle stay consistent ----------------------------------------------------------


def test_trace_reports_effect_for_applied_and_skipped_faults(world_factory: Any) -> None:
    w = _world(world_factory, "phantom_success", 2)
    create(w, client_request_id=KEY)
    create(w, client_request_id=KEY)
    with w.view() as view:
        trace = tool_trace(view.events())
    assert [(t.fault_injected, t.fault_effect) for t in trace] == [
        (None, None),
        (None, "not_applied_no_new_write"),
    ]


def test_oracle_reports_no_divergence_for_a_genuine_replay(world_factory: Any) -> None:
    """The old behaviour fabricated a new id on the replay, which the Oracle reported as a
    phantom-success divergence that had not been produced at any commit boundary."""
    w = _world(world_factory, "phantom_success", 2)
    create(w, client_request_id=KEY)
    create(w, client_request_id=KEY)
    with w.view() as view:
        report = TruthOracle().evaluate(view, w.scenario, None)
    assert report.response_divergences == []
