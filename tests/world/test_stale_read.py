"""stale_read: a lagging replica. It distorts what a read delivers and nothing else."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from moody_blues.contracts.scenario import FaultEffect, FaultKind, FaultSpec
from moody_blues.contracts.world import EventKind, ToolErrorCode
from moody_blues.world.engine import World
from moody_blues.world.oracle import TruthOracle
from moody_blues.world.reference import EXECUTORS
from tests.world.conftest import ADA, make_scenario, snapshot

STALE: dict[str, Any] = {"kind": "stale_read", "operation": "read", "occurrence": 1}


def stale(**overrides: Any) -> dict[str, Any]:
    return STALE | overrides


def events(world: World, kind: EventKind) -> list[dict[str, Any]]:
    with world.view() as view:
        return [e.payload for e in view.events() if e.kind is kind]


def test_a_stale_search_hides_rows_committed_during_the_run_but_not_seeds() -> None:
    with World(make_scenario(faults=[stale()])) as w:
        created = w.gateway.call("create_customer", ADA)
        assert created.ok
        delivered = w.gateway.call("search_customers", {})
        assert delivered.data is not None
        assert delivered.data["count"] == 2  # the two seeds; the committed row is hidden
        assert len(snapshot(w)) == 3  # authoritative state still has it
        [event] = events(w, EventKind.FAULT_INJECTED)
        assert event["effect"] == FaultEffect.READ_SERVED_FROM_STALE_SNAPSHOT.value
        assert event["rows_hidden"] == 1
        assert event["new_commit"] is False


def test_a_stale_get_reports_not_found_for_a_committed_row_then_the_lag_ends() -> None:
    with World(make_scenario(faults=[stale()])) as w:
        created = w.gateway.call("create_customer", ADA)
        assert created.data is not None
        customer = created.data["customer"]
        assert isinstance(customer, dict)
        args = {"customer_id": customer["customer_id"]}
        first = w.gateway.call("get_customer", args)
        assert first.error is not None
        assert first.error.code is ToolErrorCode.NOT_FOUND
        assert w.gateway.call("get_customer", args).ok


def test_span_covers_consecutive_reads_of_either_tool() -> None:
    with World(make_scenario(faults=[stale(span=2)])) as w:
        created = w.gateway.call("create_customer", ADA)
        assert created.data is not None
        customer = created.data["customer"]
        assert isinstance(customer, dict)
        assert not w.gateway.call("get_customer", {"customer_id": customer["customer_id"]}).ok
        hidden = w.gateway.call("search_customers", {"email": ADA["email"]})
        assert hidden.data is not None
        assert hidden.data["count"] == 0
        visible = w.gateway.call("search_customers", {"email": ADA["email"]})
        assert visible.data is not None
        assert visible.data["count"] == 1


def test_nothing_to_hide_is_recorded_as_not_applied() -> None:
    with World(make_scenario(faults=[stale()])) as w:
        delivered = w.gateway.call("search_customers", {})
        assert delivered.data is not None
        assert delivered.data["count"] == 2
        assert not events(w, EventKind.FAULT_INJECTED)
        [skipped] = events(w, EventKind.FAULT_SKIPPED)
        assert skipped["effect"] == FaultEffect.NOT_APPLIED_NOTHING_TO_HIDE.value


def test_rejected_reads_do_not_consume_an_occurrence() -> None:
    with World(make_scenario(faults=[stale()])) as w:
        w.gateway.call("create_customer", ADA)
        assert not w.gateway.call("get_customer", {}).ok  # invalid arguments
        delivered = w.gateway.call("search_customers", {})
        assert delivered.data is not None
        assert delivered.data["count"] == 2


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ({"kind": "stale_read"}, "targets reads"),
        ({"kind": "phantom_failure", "operation": "read"}, "targets reads"),
        ({"kind": "phantom_failure", "span": 2}, "only stale_read may span"),
    ],
)
def test_invalid_fault_specs_are_refused(fault: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        FaultSpec.model_validate(fault)


def test_overlapping_windows_are_refused() -> None:
    with pytest.raises(ValueError, match="at most one fault"):
        make_scenario(faults=[stale(span=3), stale(occurrence=2)])


@settings(max_examples=30, deadline=None)
@given(
    executor=st.sampled_from(sorted(EXECUTORS)),
    occurrence=st.integers(min_value=1, max_value=3),
    span=st.integers(min_value=1, max_value=6),
)
def test_stale_reads_never_change_state_only_what_the_oracle_is_told_by_the_executor(
    executor: str, occurrence: int, span: int
) -> None:
    """The Oracle judges committed state. A stale read may change what an executor does next,
    so verdicts can differ, but every verdict must equal a re-evaluation of the state alone."""
    plan = [stale(occurrence=occurrence, span=span)]
    with World(make_scenario(faults=plan)) as w:
        claim = EXECUTORS[executor](w.gateway, w.scenario.objective)
        with w.view() as view:
            report = TruthOracle().evaluate(view, w.scenario, claim)
            rows = view.all_customers()
        new = [r for r in rows if r.created_by_call > 0]
        assert len(report.observation.new_customer_ids) == len(new)
        assert {r.customer_id for r in rows} >= set(report.observation.seed_customer_ids)
        assert not any(
            e["kind"] == FaultKind.STALE_READ.value and e["new_commit"]
            for e in events(w, EventKind.FAULT_INJECTED)
        )
