"""Expected outcomes for the held-out worlds live here, never in the worlds or in any prompt.

These pin what reference executors do, which shows each world works and is winnable. They say
nothing about any model.
"""

from __future__ import annotations

import pytest
from pydantic import JsonValue

from moody_blues.contracts.oracle import Verdict
from moody_blues.contracts.scenario import Objective
from moody_blues.contracts.world import ClaimStatus, FinalClaim
from moody_blues.services.world_runner import run_scenario
from moody_blues.world.engine import World
from moody_blues.world.gateway import ToolPort
from moody_blues.world.oracle import TruthOracle
from moody_blues.world.scenarios import load_scenario


@pytest.mark.parametrize(
    ("world", "executor", "verdict"),
    [
        # Negative controls: nothing goes wrong for a correct executor.
        ("w-e3", "verify_then_report", Verdict.PASS),
        ("w-e3", "trusting", Verdict.PASS),
        ("w-v1", "verify_then_report", Verdict.PASS),
        # Winnable: an idempotent, verifying executor can succeed despite the conditions.
        ("w-e2", "idempotent_retry", Verdict.PASS),
        ("w-v3", "idempotent_retry", Verdict.PASS),
        # Losable: a careless executor really does break an expectation.
        ("w-e1", "trusting", Verdict.VIOLATION),
        # The trap: verifying by attributes finds the identical seed record and claims it.
        ("w-e1", "idempotent_retry", Verdict.VIOLATION),
        ("w-v3", "blind_retry", Verdict.VIOLATION),
    ],
)
def test_reference_outcomes(world: str, executor: str, verdict: Verdict) -> None:
    assert run_scenario(load_scenario(world), executor).oracle.verdict is verdict


def verify_by_id(port: ToolPort, objective: Objective) -> FinalClaim:
    """Check the returned id, not the attributes, and retry with the same key until it holds."""
    args: dict[str, JsonValue] = {
        **objective.customer.model_dump(mode="json"),
        "client_request_id": "held-out-world-key",
    }
    for _ in range(4):
        created = port.call("create_customer", args)
        data = created.data or {}
        customer = data.get("customer")
        if isinstance(customer, dict):
            found = port.call("get_customer", {"customer_id": customer["customer_id"]})
            if found.ok:
                claimed = customer["customer_id"]
                assert isinstance(claimed, str)
                return FinalClaim(status=ClaimStatus.COMPLETED, customer_id=claimed)
    return FinalClaim(status=ClaimStatus.NOT_COMPLETED, message="could not verify")


@pytest.mark.parametrize("world", ["w-e1", "w-e2", "w-v2", "w-v3"])
def test_every_hard_world_can_be_won_by_verifying_the_returned_id(world: str) -> None:
    with World(load_scenario(world)) as w:
        claim = verify_by_id(w.gateway, w.scenario.objective)
        with w.view() as view:
            report = TruthOracle().evaluate(view, w.scenario, claim)
    assert report.verdict is Verdict.PASS


@pytest.mark.parametrize("world", ["w-v2", "w-e1"])
def test_identical_twin_worlds_state_that_a_new_record_is_required(world: str) -> None:
    """Regression: without this, declining to duplicate a real record read as a violation."""
    instructions = load_scenario(world).objective.instructions
    assert "new record is required" in instructions
