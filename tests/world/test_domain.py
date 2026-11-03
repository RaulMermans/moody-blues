"""CRM domain + persistence (C2-A): validation, CRUD-like tools, transactions, isolation."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from moody_blues.contracts.scenario import Scenario
from moody_blues.contracts.world import (
    CustomerDraft,
    CustomerRecord,
    EventKind,
    ToolErrorCode,
    ToolName,
)
from moody_blues.world.engine import World, WorldClosedError
from moody_blues.world.gateway import derive_customer_id, tool_specs
from moody_blues.world.store import CommitDecision, CrmStore, ReadOnlyWorldView, WriteOutcome
from tests.world.conftest import ADA, create, customer_id, make_scenario, raw_connection, snapshot

# --- validation ------------------------------------------------------------------------------


def test_draft_normalizes_name_and_email() -> None:
    d = CustomerDraft(name="  Ada   Lovelace ", email="  ADA@Analytical.Example ")
    assert d.name == "Ada Lovelace"
    assert d.email == "ada@analytical.example"


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "   ", "email": "a@b.co"},
        {"name": "x" * 121, "email": "a@b.co"},
        {"name": "bad\x00name", "email": "a@b.co"},
        {"name": "Ada", "email": "not-an-email"},
        {"name": "Ada", "email": "a@b"},
        {"name": "Ada", "email": "a@b.co", "metadata": {"Bad Key": "v"}},
        {"name": "Ada", "email": "a@b.co", "metadata": {f"k{i}": "v" for i in range(17)}},
        {"name": "Ada", "email": "a@b.co", "unexpected": 1},
    ],
)
def test_draft_rejects_invalid(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CustomerDraft.model_validate(bad)


def test_invalid_tool_arguments_are_rejected_without_writing(world: World) -> None:
    before = snapshot(world)
    r = world.gateway.call(ToolName.CREATE_CUSTOMER, {"name": "Ada", "email": "nope"})
    assert not r.ok
    assert r.error is not None
    assert r.error.code is ToolErrorCode.VALIDATION_ERROR
    assert not r.error.retryable
    assert snapshot(world) == before


def test_unknown_tool_is_an_honest_error(world: World) -> None:
    r = world.gateway.call("delete_everything", {})
    assert r.error is not None
    assert r.error.code is ToolErrorCode.UNKNOWN_TOOL


# --- create / get / search -------------------------------------------------------------------


def test_create_commits_a_customer_with_deterministic_id_and_time(world: World) -> None:
    r = create(world)
    cid = customer_id(r)
    assert cid == derive_customer_id(world.scenario.seed, 1)
    assert r.data is not None
    assert r.data["idempotent_replay"] is False
    with world.view() as view:
        rec = view.get_customer(cid)
    assert rec is not None
    assert (rec.name, rec.email, rec.metadata) == (
        "Ada Lovelace",
        ADA["email"],
        {"tier": "platinum"},
    )
    assert rec.created_at == datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    assert rec.created_by_call == 1


def test_agent_view_hides_internal_provenance(world: World) -> None:
    r = create(world)
    assert r.data is not None
    customer = r.data["customer"]
    assert isinstance(customer, dict)
    assert "created_by_call" not in customer


def test_get_customer_found_and_not_found(world: World) -> None:
    cid = customer_id(create(world))
    got = world.gateway.call(ToolName.GET_CUSTOMER, {"customer_id": cid})
    assert customer_id(got) == cid
    missing = world.gateway.call(ToolName.GET_CUSTOMER, {"customer_id": "cus_unknown"})
    assert missing.error is not None
    assert missing.error.code is ToolErrorCode.NOT_FOUND


def test_search_by_email_name_and_listing(world: World) -> None:
    create(world)
    by_email = world.gateway.call(ToolName.SEARCH_CUSTOMERS, {"email": "ADA@analytical.example"})
    assert by_email.data is not None
    assert by_email.data["count"] == 1
    by_name = world.gateway.call(ToolName.SEARCH_CUSTOMERS, {"name_contains": "lovel"})
    assert by_name.data is not None
    assert by_name.data["count"] == 1
    listing = world.gateway.call(ToolName.SEARCH_CUSTOMERS, {})
    assert listing.data is not None
    assert listing.data["count"] == 3  # 2 seeds + 1 created
    limited = world.gateway.call(ToolName.SEARCH_CUSTOMERS, {"limit": 1})
    assert limited.data is not None
    assert limited.data["count"] == 1


def test_search_treats_like_wildcards_literally(world: World) -> None:
    r = world.gateway.call(ToolName.SEARCH_CUSTOMERS, {"name_contains": "%"})
    assert r.data is not None
    assert r.data["count"] == 0


def test_emails_are_not_unique_so_duplicates_are_possible(world: World) -> None:
    a, b = customer_id(create(world)), customer_id(create(world))
    assert a != b
    assert len(snapshot(world)) == 4


def test_idempotent_replay_returns_original_and_writes_nothing(world: World) -> None:
    first = customer_id(create(world, client_request_id="req-abcdef12"))
    before = snapshot(world)
    again = create(world, client_request_id="req-abcdef12")
    assert customer_id(again) == first
    assert again.data is not None
    assert again.data["idempotent_replay"] is True
    assert snapshot(world) == before


def test_idempotency_key_reused_with_different_attributes_conflicts(world: World) -> None:
    create(world, client_request_id="req-abcdef12")
    before = snapshot(world)
    r = create(world, client_request_id="req-abcdef12", name="Someone Else")
    assert r.error is not None
    assert r.error.code is ToolErrorCode.IDEMPOTENCY_CONFLICT
    assert snapshot(world) == before


def test_tool_specs_cover_every_tool() -> None:
    specs = {s.name for s in tool_specs()}
    assert specs == set(ToolName)


# --- persistence, transactions, journal ---------------------------------------------------


def test_state_persists_on_disk_and_is_readable_by_a_fresh_connection(world: World) -> None:
    cid = customer_id(create(world))
    with ReadOnlyWorldView(world.db_path) as fresh:
        assert fresh.get_customer(cid) is not None


def _record(call_seq: int, **kw: Any) -> CustomerRecord:
    base: dict[str, Any] = {
        "customer_id": f"cus_test{call_seq:04d}",
        "name": "Ada Lovelace",
        "email": "ada@analytical.example",
        "metadata": {},
        "client_request_id": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "created_by_call": call_seq,
    }
    return CustomerRecord.model_validate(base | kw)


def _store(tmp_path: Path) -> CrmStore:
    return CrmStore.initialize(tmp_path / "w.sqlite3", meta={"world_id": "wld_test"})


def test_exception_before_commit_rolls_back(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def boom() -> CommitDecision:
        raise sqlite3.OperationalError("disk I/O error (simulated)")

    with pytest.raises(sqlite3.OperationalError):
        store.insert_customer(_record(1), before_commit=boom)
    assert store.all_customers() == []
    assert store.committed_changes() == []
    # The connection is usable again: no transaction was left open.
    assert store.insert_customer(_record(2)).outcome is WriteOutcome.COMMITTED
    store.close()


def test_abort_at_pre_commit_boundary_leaves_no_trace(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.insert_customer(_record(1), before_commit=lambda: CommitDecision.ABORT)
    assert result.outcome is WriteOutcome.ABORTED_PRE_COMMIT
    assert store.all_customers() == []
    assert store.committed_changes() == []
    store.close()


def test_committed_changes_journal_tracks_commits_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.insert_customer(_record(1))
    store.insert_customer(_record(2), before_commit=lambda: CommitDecision.ABORT)
    store.insert_customer(_record(3))
    changes = store.committed_changes()
    assert [(c.operation, c.created_by_call) for c in changes] == [("insert", 1), ("insert", 3)]
    store.close()


def test_schema_check_constraints_reject_bad_rows_atomically(world: World) -> None:
    conn = raw_connection(world)
    before = snapshot(world)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO customers VALUES ('cus_bad1', 'X', 'UPPER@CASE.EXAMPLE', '{}', NULL, "
            "'2026-01-01T00:00:00+00:00', 1)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO customers VALUES ('cus_bad2', 'X', 'a@b.co', '[1]', NULL, "
            "'2026-01-01T00:00:00+00:00', 1)"
        )
    conn.close()
    assert snapshot(world) == before


def test_evidence_trail_is_append_only(world: World) -> None:
    create(world)
    conn = raw_connection(world)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE events SET payload = '{}'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM committed_changes")
    conn.close()


def test_read_only_view_cannot_write(world: World) -> None:
    with world.view() as view:
        conn = view._conn  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(sqlite3.OperationalError, match=r"readonly|read-only|query_only"):
            conn.execute("DELETE FROM customers")
        # Even with query_only lifted, the connection was opened mode=ro: still refused.
        conn.execute("PRAGMA query_only = OFF")
        with pytest.raises(sqlite3.OperationalError, match=r"readonly"):
            conn.execute("DELETE FROM customers")
    assert len(snapshot(world)) == 2


def test_gateway_refuses_to_operate_when_evidence_cannot_be_recorded(world: World) -> None:
    """A locked database means no evidence can be written: the call must fail loudly
    rather than act unobserved."""
    store = world._store  # pyright: ignore[reportPrivateUsage]
    assert store is not None
    store._conn.execute("PRAGMA busy_timeout = 50")  # pyright: ignore[reportPrivateUsage]
    blocker = raw_connection(world)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            create(world)
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert len(snapshot(world)) == 2


def test_genuine_transaction_failure_returns_honest_retryable_error(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = world._store  # pyright: ignore[reportPrivateUsage]
    assert store is not None
    original = store.insert_customer

    def failing(record: CustomerRecord, *, before_commit: Any = None) -> Any:
        def boom() -> CommitDecision:
            raise sqlite3.OperationalError("disk I/O error (simulated)")

        return original(record, before_commit=boom)

    monkeypatch.setattr(store, "insert_customer", failing)
    r = create(world)
    assert r.error is not None
    assert r.error.code is ToolErrorCode.INTERNAL_ERROR
    assert r.error.retryable
    assert len(snapshot(world)) == 2
    with world.view() as view:
        executed = [e for e in view.events() if e.kind is EventKind.OPERATION_EXECUTED]
    assert executed[-1].payload["outcome"] == "transaction_failed"


# --- lifecycle, reset, isolation --------------------------------------------------------------


def test_fresh_world_matches_scenario_initial_state(world: World) -> None:
    rows = snapshot(world)
    assert [r["customer_id"] for r in rows] == ["cus_seed_alan", "cus_seed_grace"]
    with world.view() as view:
        events = view.events()
    assert [e.kind for e in events] == [EventKind.WORLD_INITIALIZED]


def test_reset_restores_initial_state_and_evidence(world: World) -> None:
    initial = snapshot(world)
    create(world)
    create(world, email="other@x.example")
    world.reset()
    assert snapshot(world) == initial
    with world.view() as view:
        assert [e.kind for e in view.events()] == [EventKind.WORLD_INITIALIZED]
        assert view.committed_changes()[-1].created_by_call == 0
    assert world.epoch == 1
    # Fresh gateway: call numbering (and therefore ids) restart.
    assert customer_id(create(world)) == derive_customer_id(world.scenario.seed, 1)


def test_worlds_are_isolated(world_factory: Any) -> None:
    a: World = world_factory()
    b: World = world_factory()
    assert a.db_path != b.db_path
    b_before = snapshot(b)
    create(a)
    create(a, email="z@z.example")
    assert snapshot(b) == b_before
    assert len(snapshot(a)) == 4


def test_closed_world_refuses_use(tmp_path: Path) -> None:
    w = World(make_scenario(), root_dir=tmp_path)
    w.close()
    assert not w.directory.exists()
    with pytest.raises(WorldClosedError):
        _ = w.gateway


def test_world_without_root_cleans_up_its_temp_dir() -> None:
    with World(make_scenario()) as w:
        root = w.directory.parent
        assert w.db_path.exists()
    assert not root.exists()


def test_scenario_rejects_duplicate_seed_ids() -> None:
    seed = {"customer_id": "cus_dup1", "name": "A", "email": "a@b.co"}
    with pytest.raises(ValidationError, match="unique"):
        make_scenario(initial_state={"customers": [seed, seed]})


def test_scenario_round_trips_through_json() -> None:
    s = make_scenario(faults=[{"kind": "phantom_failure"}])
    assert Scenario.model_validate_json(s.model_dump_json()) == s
