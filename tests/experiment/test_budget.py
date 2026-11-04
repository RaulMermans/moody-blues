"""Spend ledger: an estimate that refuses early (OFFLINE, real files)."""

from __future__ import annotations

from pathlib import Path

import pytest

from moody_blues.contracts.agent import AgentBudget, TokenTotals
from moody_blues.experiments.budget import (
    BudgetExceededError,
    PriceCeiling,
    SpendLedger,
    worst_case_run_tokens,
)

PRICES = PriceCeiling(input_per_million_usd=1.0, output_per_million_usd=4.0)


def ledger(tmp_path: Path, limit: float = 1.0) -> SpendLedger:
    return SpendLedger(tmp_path / "ledger.jsonl", limit_usd=limit, prices=PRICES)


def totals(prompt: int, completion: int, *, complete: bool = True) -> TokenTotals:
    return TokenTotals(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        complete=complete,
    )


def test_worst_case_prices_every_token_at_the_higher_rate(tmp_path: Path) -> None:
    book = ledger(tmp_path)
    book.reserve("x", worst_case_tokens=100_000)
    assert book.status().open_reservations_usd == pytest.approx(0.4)


def test_reservation_is_refused_when_it_would_cross_the_limit(tmp_path: Path) -> None:
    book = ledger(tmp_path)
    book.reserve("first", worst_case_tokens=200_000)  # $0.80 held
    with pytest.raises(BudgetExceededError, match="refusing live work"):
        book.reserve("second", worst_case_tokens=100_000)  # $0.40 more


def test_settling_releases_the_unused_part(tmp_path: Path) -> None:
    book = ledger(tmp_path)
    entry = book.reserve("first", worst_case_tokens=200_000)
    assert book.settle(entry, totals(1_000, 1_000)) == pytest.approx(0.005)
    status = book.status()
    assert status.open_reservations == 0
    assert status.remaining_usd == pytest.approx(0.995)
    book.reserve("second", worst_case_tokens=200_000)


def test_open_reservation_from_a_dead_process_keeps_counting(tmp_path: Path) -> None:
    ledger(tmp_path).reserve("crashed", worst_case_tokens=200_000)
    reopened = ledger(tmp_path)
    assert reopened.status().open_reservations == 1
    with pytest.raises(BudgetExceededError):
        reopened.reserve("next", worst_case_tokens=100_000)


@pytest.mark.parametrize("tokens", [None, totals(10, 10, complete=False)])
def test_incomplete_usage_keeps_the_full_reservation(
    tmp_path: Path, tokens: TokenTotals | None
) -> None:
    book = ledger(tmp_path)
    entry = book.reserve("x", worst_case_tokens=100_000)
    assert book.settle(entry, tokens) == pytest.approx(0.4)


def test_a_reservation_settles_once(tmp_path: Path) -> None:
    book = ledger(tmp_path)
    entry = book.reserve("x", worst_case_tokens=10)
    book.settle(entry, totals(1, 1))
    with pytest.raises(ValueError, match="already settled"):
        book.settle(entry, totals(1, 1))


def test_unreadable_ledger_refuses_all_spending(tmp_path: Path) -> None:
    book = ledger(tmp_path)
    book.path.write_text("corrupted\n", encoding="utf-8")
    with pytest.raises(BudgetExceededError, match="unreadable"):
        book.reserve("x", worst_case_tokens=1)


def test_status_says_it_is_not_a_provider_limit(tmp_path: Path) -> None:
    note = ledger(tmp_path).status().note
    assert "Not a provider invoice" in note
    assert "not a provider-enforced limit" in note


def test_worst_case_covers_the_overshoot_of_the_last_call() -> None:
    budget = AgentBudget(max_total_tokens=20_000, max_completion_tokens=1_024)
    assert worst_case_run_tokens(budget) == 41_024
