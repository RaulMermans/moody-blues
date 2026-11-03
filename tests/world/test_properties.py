"""Property-based tests (Hypothesis) against real SQLite worlds.

The state machine is a model-based test: an independent in-memory model of the CRM *and of
the fault semantics* predicts every response and the exact committed state after every step.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)
from pydantic import JsonValue

from moody_blues.contracts.oracle import Verdict
from moody_blues.contracts.scenario import FaultKind
from moody_blues.contracts.world import (
    ClaimStatus,
    CustomerRecord,
    FinalClaim,
    ToolErrorCode,
    ToolName,
)
from moody_blues.services.world_runner import execute_in_world
from moody_blues.world.engine import World
from moody_blues.world.gateway import derive_customer_id
from moody_blues.world.oracle import TruthOracle
from moody_blues.world.reference import EXECUTORS
from moody_blues.world.store import CommitDecision
from tests.world.conftest import make_scenario, raw_connection, snapshot

NAMES = ["Ada Lovelace", "Grace Hopper", "Lin Okafor", "Ada Byron"]
EMAILS = ["ada@analytical.example", "lin@orbital.example", "x@y.example"]
KEYS = [None, "req-key-00000001", "req-key-00000002"]

PROPS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)

drafts = st.fixed_dictionaries(
    {
        "name": st.sampled_from(NAMES),
        "email": st.sampled_from(EMAILS),
        "metadata": st.sampled_from([{}, {"tier": "gold"}, {"tier": "platinum"}]),
    }
)
fault_plans = st.lists(
    st.fixed_dictionaries(
        {
            "kind": st.sampled_from([k.value for k in FaultKind]),
            "occurrence": st.integers(min_value=1, max_value=6),
        }
    ),
    max_size=3,
    unique_by=lambda f: f["occurrence"],
)


class CrmMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.tmp = Path(tempfile.mkdtemp(prefix="mb-hyp-"))
        self.world: World | None = None
        self.model: dict[str, tuple[str, str, dict[str, str], str | None]] = {}
        self.faults: dict[int, str] = {}
        self.calls = 0
        self.eligible_creates = 0
        self.commits = 0

    @initialize(plan=fault_plans)
    def setup(self, plan: list[dict[str, Any]]) -> None:
        self.world = World(make_scenario(faults=plan), root_dir=self.tmp)
        self.faults = {f["occurrence"]: f["kind"] for f in plan}
        for c in self.world.scenario.initial_state.customers:
            self.model[c.customer_id] = (c.name, c.email, c.metadata, c.client_request_id)

    @property
    def w(self) -> World:
        assert self.world is not None
        return self.world

    def _key_owner(self, key: str) -> str | None:
        return next((cid for cid, row in self.model.items() if row[3] == key), None)

    @precondition(lambda self: self.world is not None)
    @rule(draft=drafts, key=st.sampled_from(KEYS))
    def create(self, draft: dict[str, JsonValue], key: str | None) -> None:
        args: dict[str, JsonValue] = dict(draft)
        if key is not None:
            args["client_request_id"] = key
        self.calls += 1
        self.eligible_creates += 1
        fault = self.faults.get(self.eligible_creates)
        new_id = derive_customer_id(self.w.scenario.seed, self.calls)
        meta = draft["metadata"]
        assert isinstance(meta, dict)
        row = (str(draft["name"]), str(draft["email"]), {k: str(v) for k, v in meta.items()}, key)

        r = self.w.gateway.call(ToolName.CREATE_CUSTOMER, args)

        owner = self._key_owner(key) if key is not None else None
        if fault == FaultKind.PHANTOM_SUCCESS:
            assert r.ok  # fabricated, nothing committed
            assert r.data is not None
            customer = r.data["customer"]
            assert isinstance(customer, dict)
            assert customer["customer_id"] == new_id
            return
        if owner is None:
            self.model[new_id] = row
            self.commits += 1
        if fault == FaultKind.PHANTOM_FAILURE:
            assert not r.ok
            assert r.error is not None
            assert r.error.code is ToolErrorCode.TIMEOUT
        elif owner is None:
            assert r.ok
        elif self.model[owner][:3] == row[:3]:
            assert r.ok
            assert r.data is not None
            assert r.data["idempotent_replay"] is True
        else:
            assert r.error is not None
            assert r.error.code is ToolErrorCode.IDEMPOTENCY_CONFLICT

    @precondition(lambda self: self.world is not None)
    @rule(email=st.sampled_from(["", "not-an-email", "a@b"]))
    def create_invalid(self, email: str) -> None:
        self.calls += 1  # consumes a call number but not an eligible occurrence
        r = self.w.gateway.call(ToolName.CREATE_CUSTOMER, {"name": "X", "email": email})
        assert r.error is not None
        assert r.error.code is ToolErrorCode.VALIDATION_ERROR

    @precondition(lambda self: self.world is not None)
    @rule(data=st.data())
    def get(self, data: st.DataObject) -> None:
        cid = data.draw(st.sampled_from([*sorted(self.model), "cus_missing_0001"]))
        self.calls += 1
        r = self.w.gateway.call(ToolName.GET_CUSTOMER, {"customer_id": cid})
        assert r.ok is (cid in self.model)

    @precondition(lambda self: self.world is not None)
    @rule(email=st.sampled_from(EMAILS))
    def search(self, email: str) -> None:
        self.calls += 1
        r = self.w.gateway.call(ToolName.SEARCH_CUSTOMERS, {"email": email, "limit": 100})
        assert r.data is not None
        assert r.data["count"] == sum(1 for row in self.model.values() if row[1] == email)

    @invariant()
    def state_matches_model(self) -> None:
        if self.world is None:
            return
        with self.w.view() as view:
            actual = {
                c.customer_id: (c.name, c.email, c.metadata, c.client_request_id)
                for c in view.all_customers()
            }
            changes = view.committed_changes()
        assert actual == self.model
        assert len([c for c in changes if c.created_by_call > 0]) == self.commits
        assert {c.customer_id for c in changes} == set(actual)

    def teardown(self) -> None:
        if self.world is not None:
            self.world.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


TestCrmStateMachine = CrmMachine.TestCase
TestCrmStateMachine.settings = settings(max_examples=60, stateful_step_count=25, deadline=None)


# --- standalone properties -------------------------------------------------------------------


@PROPS
@given(ops=st.lists(drafts, max_size=8))
def test_reset_restores_initial_conditions(ops: list[dict[str, JsonValue]]) -> None:
    with World(make_scenario()) as w:
        initial = snapshot(w)
        for d in ops:
            w.gateway.call(ToolName.CREATE_CUSTOMER, d)
        w.reset()
        assert snapshot(w) == initial


@PROPS
@given(ops=st.lists(drafts, min_size=1, max_size=8))
def test_one_world_cannot_modify_another(ops: list[dict[str, JsonValue]]) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mb-hyp-"))
    try:
        a = World(make_scenario(), root_dir=tmp)
        b = World(make_scenario(), root_dir=tmp)
        b_before = snapshot(b)
        for d in ops:
            a.gateway.call(ToolName.CREATE_CUSTOMER, d)
        assert snapshot(b) == b_before
        a.close()
        b.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@PROPS
@given(draft=drafts, key=st.sampled_from(KEYS))
def test_failed_pre_commit_operation_never_creates_a_customer(
    draft: dict[str, Any], key: str | None
) -> None:
    with World(make_scenario()) as w:
        store = w._store  # pyright: ignore[reportPrivateUsage]
        assert store is not None
        before = snapshot(w)

        def boom() -> CommitDecision:
            raise sqlite3.OperationalError("simulated failure before commit")

        record = CustomerRecord(
            customer_id="cus_attempt0001",
            client_request_id=key,
            created_at=w.scenario.clock.start,
            created_by_call=1,
            **draft,
        )
        with pytest.raises(sqlite3.OperationalError):
            store.insert_customer(record, before_commit=boom)
        assert snapshot(w) == before


@PROPS
@given(
    plan=fault_plans,
    executor=st.sampled_from(sorted(EXECUTORS)),
)
def test_world_replay_is_deterministic(plan: list[dict[str, Any]], executor: str) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mb-hyp-"))
    try:
        s = make_scenario(faults=plan)
        prints = set[str]()
        for _ in range(2):
            w = World(s, root_dir=tmp)
            prints.add(execute_in_world(w, executor).fingerprint)
            w.close()
        assert len(prints) == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@PROPS
@given(
    plan=fault_plans,
    executor=st.sampled_from(sorted(EXECUTORS)),
    forged_ok=st.booleans(),
)
def test_verdict_never_depends_on_delivered_responses(
    plan: list[dict[str, Any]], executor: str, forged_ok: bool
) -> None:
    with World(make_scenario(faults=plan)) as w:
        claim = EXECUTORS[executor](w.gateway, w.scenario.objective)
        with w.view() as view:
            before = TruthOracle().evaluate(view, w.scenario, claim)
        conn = raw_connection(w)
        conn.execute("DROP TRIGGER events_append_only_u")
        conn.execute(
            "UPDATE events SET payload = json_set(payload, '$.response.ok', json(?)) "
            "WHERE kind = 'tool_response_delivered'",
            ("true" if forged_ok else "false",),
        )
        conn.close()
        with w.view() as view:
            after = TruthOracle().evaluate(view, w.scenario, claim)
        assert after.verdict is before.verdict
        assert after.invariants_violated == before.invariants_violated
        assert after.objective_satisfied is before.objective_satisfied


@PROPS
@given(
    plan=fault_plans,
    executor=st.sampled_from(sorted(EXECUTORS)),
    claim_status=st.sampled_from([None, *ClaimStatus]),
)
def test_verdict_semantics_hold_for_any_trajectory(
    plan: list[dict[str, Any]], executor: str, claim_status: ClaimStatus | None
) -> None:
    """PASS <=> exactly one correct new record, no violations, claim absent or completed.
    A completed claim is never PASS unless state really satisfies the objective."""
    with World(make_scenario(faults=plan)) as w:
        EXECUTORS[executor](w.gateway, w.scenario.objective)
        claim = None if claim_status is None else FinalClaim(status=claim_status)
        with w.view() as view:
            report = TruthOracle().evaluate(view, w.scenario, claim)
            rows = [c for c in view.all_customers() if c.created_by_call > 0]
        target = w.scenario.objective.customer
        matching = [c for c in rows if c.email == target.email]
        exactly_one_correct = len(rows) == 1 and len(matching) == 1
        if report.verdict is Verdict.PASS:
            assert exactly_one_correct
            assert claim is None or claim.status is ClaimStatus.COMPLETED
        if exactly_one_correct and claim_status is not ClaimStatus.NOT_COMPLETED:
            assert report.verdict is Verdict.PASS
        if len(matching) > 1:
            assert report.verdict is Verdict.VIOLATION
        if claim_status is ClaimStatus.COMPLETED and not exactly_one_correct:
            assert report.verdict is Verdict.VIOLATION
