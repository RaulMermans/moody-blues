"""One fail-closed budget for model calls and target runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from moody_blues.contracts.agent import AgentBudget, TokenTotals
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import InferenceRequest, InferenceResult
from moody_blues.contracts.investigation import InvestigationState
from moody_blues.experiments.budget import (
    BudgetExceededError,
    PriceCeiling,
    ScopedSpend,
    SpendLedger,
)
from moody_blues.experiments.target import AgentTarget
from moody_blues.inference.vultr import InferenceError
from moody_blues.investigator.fixtures import (
    ScriptedInvestigatorModel,
    conclude,
    propose,
    tool_result,
)
from moody_blues.investigator.model import InvestigatorModel
from tests.investigator.conftest import CODE, Harness, experiment

PRICES = PriceCeiling(input_per_million_usd=1.40, output_per_million_usd=4.40)


def ledger(path: Path, limit: float = 5.0) -> SpendLedger:
    return SpendLedger(path / "ledger.jsonl", limit_usd=limit, prices=PRICES)


def spend(path: Path, cap: float = 1.0, limit: float = 5.0) -> ScopedSpend:
    return ScopedSpend(ledger(path, limit), "inv_test", cap)


def agent_target(scope: ScopedSpend) -> AgentTarget:
    """A live-labeled target over a canned model: it reserves like the real one."""
    inference = ScriptedInvestigatorModel(
        [tool_result("submit_final_claim", {"status": "not_completed", "message": "x"})] * 4
    )
    return AgentTarget(
        inference=inference,
        evidence="live_provider",
        provider="fixture",
        model="fixture",
        budget=AgentBudget(max_steps=2, max_total_tokens=1_000),
        ledger=scope,
    )


def test_model_calls_and_target_runs_share_one_scope(tmp_path: Path) -> None:
    scope = spend(tmp_path)
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=experiment(),
        target=agent_target(scope),
        spend=scope,
    )
    report = h.run()
    labels = [str(r["label"]) for r in scope._ledger.export()]  # pyright: ignore[reportPrivateUsage]
    assert any(":investigator:" in x for x in labels)
    assert any(":experiment:" in x for x in labels)
    assert report.usage.scope_settled_usd is not None
    assert report.usage.scope_settled_usd > 0
    assert report.usage.scope_open_usd == 0


def test_a_model_call_reserves_before_sending_and_refuses_past_the_cap(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[], steps=[], spend=spend(tmp_path, cap=0.0001))
    report = h.run()
    assert report.state is InvestigationState.BUDGET_EXHAUSTED
    assert report.termination == "spend_limit"
    assert not h.inference.requests  # nothing was sent


def test_the_project_limit_applies_even_under_a_generous_cap(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[], steps=[], spend=spend(tmp_path, cap=1.0, limit=0.0001))
    assert h.run().state is InvestigationState.BUDGET_EXHAUSTED
    assert not h.inference.requests


def test_a_target_run_past_the_cap_ends_the_investigation(tmp_path: Path) -> None:
    scope = spend(tmp_path, cap=0.06)
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=experiment()[:1],
        target=AgentTarget(
            inference=ScriptedInvestigatorModel([]),
            evidence="live_provider",
            provider="fixture",
            model="fixture",
            budget=AgentBudget(),  # worst case far above the cap
            ledger=scope,
        ),
        spend=scope,
    )
    report = h.run()
    assert report.state is InvestigationState.BUDGET_EXHAUSTED
    assert report.termination == "experiment_budget"


def test_a_failed_call_keeps_its_full_reservation(tmp_path: Path) -> None:
    def fail(_: InferenceRequest) -> InferenceResult:
        raise InferenceError(ErrorCategory.PROVIDER_TIMEOUT, "timeout")

    scope = spend(tmp_path)
    h = Harness(tmp_path, replies=[fail], steps=[], spend=scope)
    report = h.run()
    worst = report.model_calls[0].estimated_cost_usd
    assert worst is not None  # booked at the worst case, not at zero
    assert worst > 0.01


def test_a_response_without_usage_keeps_its_full_reservation(tmp_path: Path) -> None:
    reply = conclude().model_copy(update={"usage": None})
    scope = spend(tmp_path)
    h = Harness(tmp_path, replies=[reply], steps=[], spend=scope)
    report = h.run()
    assert (report.model_calls[0].estimated_cost_usd or 0) > 0.01
    assert report.usage.usage_complete is False


def test_a_corrupt_ledger_refuses_all_new_work(tmp_path: Path) -> None:
    scope = spend(tmp_path)
    (tmp_path / "ledger.jsonl").write_text("{corrupt\n", encoding="utf-8")
    h = Harness(tmp_path, replies=[conclude()], steps=[], spend=scope)
    report = h.run()
    assert report.state is InvestigationState.BUDGET_EXHAUSTED
    assert not h.inference.requests


def test_restarting_cannot_reset_a_scope(tmp_path: Path) -> None:
    first = spend(tmp_path, cap=0.01)
    entry = first.reserve("a", worst_case_tokens=2_000)
    first.settle(
        entry, TokenTotals(prompt_tokens=1_000, completion_tokens=1_000, total_tokens=2_000)
    )
    second = spend(tmp_path, cap=0.01)  # a new process, same ledger file, same scope
    assert second.status().settled_usd > 0
    with pytest.raises(BudgetExceededError):
        second.reserve("b", worst_case_tokens=2_000)


def test_an_open_reservation_counts_against_the_scope(tmp_path: Path) -> None:
    scope = spend(tmp_path, cap=0.01)
    scope.reserve("crashed", worst_case_tokens=2_000)
    with pytest.raises(BudgetExceededError):
        scope.reserve("next", worst_case_tokens=1_000)


def test_ledger_records_from_before_scopes_still_load(tmp_path: Path) -> None:
    (tmp_path / "ledger.jsonl").write_text(
        '{"kind":"reserve","entry_id":"spend_1","at":"2026-11-03T00:00:00Z","label":"old",'
        '"amount_usd":0.5}\n',
        encoding="utf-8",
    )
    assert ledger(tmp_path).status().open_reservations == 1


def test_a_live_model_cannot_be_built_without_a_ledger() -> None:
    with pytest.raises(ValueError, match="ledger"):
        InvestigatorModel(
            inference=ScriptedInvestigatorModel([]),
            evidence="live_provider",
            model="m",
            provider="vultr",
            spend=None,
            max_completion_tokens=256,
            temperature=0,
        )


def test_retries_multiply_the_reservation(tmp_path: Path) -> None:
    def model(attempts: int) -> InvestigatorModel:
        return InvestigatorModel(
            inference=ScriptedInvestigatorModel([]),
            evidence="offline_fixture",
            model="m",
            provider=None,
            spend=None,
            max_completion_tokens=256,
            temperature=0,
            provider_attempts=attempts,
        )

    assert model(3).worst_case_tokens([], []) == 3 * model(1).worst_case_tokens([], [])
