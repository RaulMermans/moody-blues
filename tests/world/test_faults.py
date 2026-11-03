"""Fault semantics (C2-B): phantom failure commits, phantom success does not, targeting is
exact, faults are scoped to one world, and fault-free worlds are unaffected."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from moody_blues.contracts.scenario import FaultSpec
from moody_blues.contracts.world import EventKind, ToolErrorCode, ToolName
from moody_blues.world.engine import World
from moody_blues.world.faults import FaultInjector
from tests.world.conftest import ADA, create, customer_id, make_scenario, snapshot

PHANTOM_FAILURE: dict[str, Any] = {"kind": "phantom_failure", "occurrence": 1}
PHANTOM_SUCCESS: dict[str, Any] = {"kind": "phantom_success", "occurrence": 1}


def _events(world: World) -> list[Any]:
    with world.view() as view:
        return view.events()


def test_fault_free_world_has_no_fault_events(world: World) -> None:
    for _ in range(3):
        assert create(world).ok
    assert not [e for e in _events(world) if e.kind is EventKind.FAULT_INJECTED]
    assert len(snapshot(world)) == 5


def test_phantom_failure_commits_but_reports_error(world_factory: Any) -> None:
    w: World = world_factory(make_scenario(faults=[PHANTOM_FAILURE]))
    r = create(w)
    assert not r.ok
    assert r.error is not None
    assert r.error.code is ToolErrorCode.TIMEOUT
    assert r.error.retryable
    rows = [c for c in snapshot(w) if c["email"] == ADA["email"]]
    assert len(rows) == 1, "the write must have committed despite the error response"
    with w.view() as view:
        assert [c.created_by_call for c in view.committed_changes()][-1] == 1


def test_phantom_success_reports_success_but_commits_nothing(world_factory: Any) -> None:
    w: World = world_factory(make_scenario(faults=[PHANTOM_SUCCESS]))
    before = snapshot(w)
    r = create(w)
    assert r.ok
    phantom_id = customer_id(r)
    assert snapshot(w) == before, "nothing may be committed"
    with w.view() as view:
        assert view.get_customer(phantom_id) is None
        assert all(c.created_by_call == 0 for c in view.committed_changes())
    # The legitimate verification path stays open and tells the truth.
    got = w.gateway.call(ToolName.GET_CUSTOMER, {"customer_id": phantom_id})
    assert got.error is not None
    assert got.error.code is ToolErrorCode.NOT_FOUND


def test_phantom_success_response_is_shaped_like_a_genuine_success(world_factory: Any) -> None:
    genuine = create(world_factory())
    phantom = create(world_factory(make_scenario(faults=[PHANTOM_SUCCESS])))
    assert genuine.data is not None
    assert phantom.data is not None
    assert genuine.data.keys() == phantom.data.keys()
    g, p = genuine.data["customer"], phantom.data["customer"]
    assert isinstance(g, dict)
    assert isinstance(p, dict)
    assert g.keys() == p.keys()


def test_phantom_id_is_never_reused_by_a_later_real_create(world_factory: Any) -> None:
    w: World = world_factory(make_scenario(faults=[PHANTOM_SUCCESS]))
    phantom = customer_id(create(w))
    real = customer_id(create(w))
    assert phantom != real


@pytest.mark.parametrize("kind", ["phantom_failure", "phantom_success"])
def test_fault_targets_only_the_configured_occurrence(world_factory: Any, kind: str) -> None:
    w: World = world_factory(make_scenario(faults=[{"kind": kind, "occurrence": 2}]))
    first, second, third = (create(w, email=f"c{i}@x.example") for i in range(3))
    assert first.ok
    assert third.ok
    faulted = [e for e in _events(w) if e.kind is EventKind.FAULT_INJECTED]
    assert len(faulted) == 1
    assert faulted[0].call_seq == 2
    emails = {c["email"] for c in snapshot(w)}
    assert {"c0@x.example", "c2@x.example"} <= emails
    assert ("c1@x.example" in emails) is (kind == "phantom_failure")
    assert second.ok is (kind == "phantom_success")


def test_rejected_and_read_calls_do_not_consume_occurrences(world_factory: Any) -> None:
    w: World = world_factory(make_scenario(faults=[PHANTOM_FAILURE]))
    w.gateway.call(ToolName.CREATE_CUSTOMER, {"name": "x", "email": "invalid"})
    w.gateway.call(ToolName.SEARCH_CUSTOMERS, {})
    w.gateway.call(ToolName.GET_CUSTOMER, {"customer_id": "cus_seed_grace"})
    r = create(w)
    assert not r.ok, "the first *eligible* create is occurrence 1"
    faulted = [e for e in _events(w) if e.kind is EventKind.FAULT_INJECTED]
    assert faulted[0].call_seq == 4


def test_faults_do_not_leak_between_worlds(world_factory: Any) -> None:
    faulty: World = world_factory(make_scenario(faults=[PHANTOM_SUCCESS]))
    clean: World = world_factory()
    assert create(faulty).ok
    r = create(clean)
    assert r.ok
    with clean.view() as view:
        assert view.get_customer(customer_id(r)) is not None
    assert not [e for e in _events(clean) if e.kind is EventKind.FAULT_INJECTED]


def test_fault_evidence_records_boundary_and_actual_response(world_factory: Any) -> None:
    w: World = world_factory(make_scenario(faults=[PHANTOM_FAILURE]))
    create(w)
    kinds = [e.kind for e in _events(w) if e.call_seq == 1]
    assert kinds == [
        EventKind.TOOL_CALL_REQUESTED,
        EventKind.OPERATION_EXECUTED,
        EventKind.FAULT_INJECTED,
        EventKind.TOOL_RESPONSE_DELIVERED,
    ]
    fault = next(e for e in _events(w) if e.kind is EventKind.FAULT_INJECTED)
    assert fault.payload["boundary"] == "post_commit"
    actual = fault.payload["actual_response"]
    assert isinstance(actual, dict)
    assert actual["ok"] is True
    executed = next(e for e in _events(w) if e.kind is EventKind.OPERATION_EXECUTED)
    assert executed.payload["outcome"] == "committed"


def test_phantom_success_evidence_shows_pre_commit_abort(world_factory: Any) -> None:
    w: World = world_factory(make_scenario(faults=[PHANTOM_SUCCESS]))
    create(w)
    executed = next(e for e in _events(w) if e.kind is EventKind.OPERATION_EXECUTED)
    assert executed.payload["outcome"] == "aborted_pre_commit"
    fault = next(e for e in _events(w) if e.kind is EventKind.FAULT_INJECTED)
    assert fault.payload["boundary"] == "pre_commit"


def test_phantom_failure_on_idempotent_replay_changes_nothing(world_factory: Any) -> None:
    w: World = world_factory(make_scenario(faults=[{"kind": "phantom_failure", "occurrence": 2}]))
    first = customer_id(create(w, client_request_id="req-abcdef12"))
    before = snapshot(w)
    r = create(w, client_request_id="req-abcdef12")
    assert not r.ok
    assert snapshot(w) == before
    assert first in {c["customer_id"] for c in before}


# --- fault contract validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "phantom_failure", "error_code": "not_found"},
        {"kind": "phantom_failure", "occurrence": 0},
        {"kind": "phantom_success", "operation": "get_customer"},
        {"kind": "corrupt_everything"},
        {"kind": "phantom_failure", "probability": 0.5},
    ],
)
def test_fault_spec_validation(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FaultSpec.model_validate(bad)


def test_scenario_rejects_two_faults_on_one_occurrence() -> None:
    with pytest.raises(ValidationError, match="at most one fault"):
        make_scenario(faults=[PHANTOM_FAILURE, PHANTOM_SUCCESS])


def test_injector_is_disabled_without_specs() -> None:
    inj = FaultInjector([])
    assert not inj.enabled
    assert all(inj.next_execution(ToolName.CREATE_CUSTOMER).spec is None for _ in range(50))


def test_injector_counts_per_operation() -> None:
    spec = FaultSpec.model_validate({"kind": "phantom_success", "occurrence": 3})
    inj = FaultInjector([spec])
    hits = [inj.next_execution(ToolName.CREATE_CUSTOMER).spec for _ in range(5)]
    assert hits == [None, None, spec, None, None]
