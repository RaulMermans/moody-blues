"""Application-side spend ledger for live provider calls.

**This is an estimate, not a billing control.** The provider enforces nothing here. Prices are
ceilings we assume, usage is what the provider reports, and a killed process can spend without
settling. The ledger's job is to refuse to *start* work that could cross the limit.

Rules, all of which err towards refusing:

- Work reserves its worst case before it starts. ``reserve`` refuses if settled spend, plus
  every open reservation, plus this worst case would exceed the limit.
- An open reservation counts in full. A crashed run therefore keeps its worst case on the
  books rather than vanishing.
- Settling with incomplete usage keeps the full reservation.
- A ledger that cannot be read refuses all further spending.

There is one ledger for every live caller. A *scope* adds a second, narrower limit on the same
records: an investigation's model calls and target runs share one scope, so they share one cap
and neither can be reset by restarting a command.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentBudget, TokenTotals
from moody_blues.contracts.common import ErrorCategory, MoodyBluesError


class BudgetExceededError(MoodyBluesError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCategory.BUDGET_EXCEEDED, message)


class PriceCeiling(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_per_million_usd: float = Field(gt=0)
    output_per_million_usd: float = Field(gt=0)

    @classmethod
    def from_settings(cls, settings: Settings) -> PriceCeiling:
        return cls(
            input_per_million_usd=settings.live_price_ceiling_input_per_million_usd,
            output_per_million_usd=settings.live_price_ceiling_output_per_million_usd,
        )

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.input_per_million_usd
            + completion_tokens * self.output_per_million_usd
        ) / 1_000_000

    def worst_case(self, tokens: int) -> float:
        """Every token at the higher of the two prices."""
        highest = max(self.input_per_million_usd, self.output_per_million_usd)
        return tokens * highest / 1_000_000


def worst_case_run_tokens(budget: AgentBudget) -> int:
    """Upper bound for one agent run.

    ``max_total_tokens`` is checked between inference calls, so the last call can overshoot it
    by its own size: a prompt no larger than the conversation so far, plus one completion.
    """
    return 2 * budget.max_total_tokens + budget.max_completion_tokens


class SpendRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["reserve", "settle"]
    entry_id: str
    at: datetime
    label: str
    amount_usd: float = Field(ge=0)  # reserve: worst case; settle: estimated cost
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    usage_complete: bool | None = None
    scope: str | None = None  # absent in records written before scopes existed


class SpendStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit_usd: float
    settled_usd: float
    open_reservations_usd: float
    open_reservations: int
    remaining_usd: float
    prompt_tokens: int
    completion_tokens: int
    settled_entries: int
    note: str = (
        "Application-side estimate at assumed ceiling prices. Not a provider invoice and not a "
        "provider-enforced limit."
    )


class SpendPort(Protocol):
    """What live work needs from a ledger. ``SpendLedger`` and ``ScopedSpend`` satisfy it."""

    def reserve(self, label: str, *, worst_case_tokens: int) -> str: ...

    def settle(self, entry_id: str, tokens: TokenTotals | None) -> float: ...


class SpendLedger:
    def __init__(self, path: Path, *, limit_usd: float, prices: PriceCeiling) -> None:
        self.path = path
        self.limit_usd = limit_usd
        self.prices = prices

    @classmethod
    def from_settings(cls, settings: Settings, path: Path) -> SpendLedger:
        return cls(
            path,
            limit_usd=settings.live_spend_limit_usd,
            prices=PriceCeiling.from_settings(settings),
        )

    @contextmanager
    def _locked(self) -> Generator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _records(self) -> list[SpendRecord]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            return [SpendRecord.model_validate_json(line) for line in lines if line.strip()]
        except (OSError, ValidationError) as exc:
            raise BudgetExceededError(
                f"spend ledger {self.path} is unreadable; refusing to spend: {exc}"
            ) from exc

    def _append(self, record: SpendRecord) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _status(self, records: list[SpendRecord]) -> SpendStatus:
        settled = [r for r in records if r.kind == "settle"]
        settled_ids = {r.entry_id for r in settled}
        reserved = [r for r in records if r.kind == "reserve" and r.entry_id not in settled_ids]
        settled_usd = sum(r.amount_usd for r in settled)
        open_usd = sum(r.amount_usd for r in reserved)
        return SpendStatus(
            limit_usd=self.limit_usd,
            settled_usd=round(settled_usd, 6),
            open_reservations_usd=round(open_usd, 6),
            open_reservations=len(reserved),
            remaining_usd=round(self.limit_usd - settled_usd - open_usd, 6),
            prompt_tokens=sum(r.prompt_tokens or 0 for r in settled),
            completion_tokens=sum(r.completion_tokens or 0 for r in settled),
            settled_entries=len(settled),
        )

    def status(self) -> SpendStatus:
        with self._locked():
            return self._status(self._records())

    def reserve(
        self,
        label: str,
        *,
        worst_case_tokens: int,
        scope: str | None = None,
        scope_limit_usd: float | None = None,
    ) -> str:
        """Hold the worst case, or raise ``BudgetExceededError``. Returns the entry id."""
        amount = self.prices.worst_case(worst_case_tokens)
        with self._locked():
            records = self._records()
            status = self._status(records)
            if scope is not None and scope_limit_usd is not None:
                inside = self._status([r for r in records if r.scope == scope])
                committed = inside.settled_usd + inside.open_reservations_usd
                if amount + committed > scope_limit_usd:
                    raise BudgetExceededError(
                        f"refusing live work {label!r}: worst case ${amount:.4f} on top of "
                        f"${committed:.4f} exceeds this investigation's "
                        f"${scope_limit_usd:.2f} cap"
                    )
            if amount > status.remaining_usd:
                raise BudgetExceededError(
                    f"refusing live work {label!r}: worst case ${amount:.4f} exceeds the "
                    f"${status.remaining_usd:.4f} left of the ${self.limit_usd:.2f} limit "
                    f"(settled ${status.settled_usd:.4f}, "
                    f"open ${status.open_reservations_usd:.4f})"
                )
            entry_id = f"spend_{uuid4().hex[:12]}"
            self._append(
                SpendRecord(
                    kind="reserve",
                    entry_id=entry_id,
                    at=datetime.now(UTC),
                    label=label,
                    amount_usd=amount,
                    scope=scope,
                )
            )
        return entry_id

    def settle(self, entry_id: str, tokens: TokenTotals | None) -> float:
        """Replace a reservation with measured usage. Returns the amount now on the books."""
        with self._locked():
            records = self._records()
            reserved = next(
                (r for r in records if r.kind == "reserve" and r.entry_id == entry_id), None
            )
            if reserved is None:
                raise ValueError(f"no reservation {entry_id}")
            if any(r.kind == "settle" and r.entry_id == entry_id for r in records):
                raise ValueError(f"reservation {entry_id} is already settled")
            complete = tokens is not None and tokens.complete
            amount = (
                self.prices.cost(tokens.prompt_tokens, tokens.completion_tokens)
                if tokens is not None and complete
                else reserved.amount_usd
            )
            self._append(
                SpendRecord(
                    kind="settle",
                    entry_id=entry_id,
                    at=datetime.now(UTC),
                    label=reserved.label,
                    amount_usd=amount,
                    prompt_tokens=tokens.prompt_tokens if tokens is not None else None,
                    completion_tokens=tokens.completion_tokens if tokens is not None else None,
                    usage_complete=complete,
                    scope=reserved.scope,
                )
            )
        return amount

    def record_measured(self, label: str, tokens: TokenTotals) -> str:
        """Book usage measured before this ledger existed, e.g. from a saved run report."""
        entry_id = self.reserve(label, worst_case_tokens=tokens.total_tokens)
        self.settle(entry_id, tokens)
        return entry_id

    def scope_status(self, scope: str) -> SpendStatus:
        with self._locked():
            return self._status([r for r in self._records() if r.scope == scope])

    def export(self) -> list[dict[str, object]]:
        with self._locked():
            return [json.loads(r.model_dump_json()) for r in self._records()]


class ScopedSpend:
    """One investigation's view of the shared ledger: same records, an extra cap."""

    def __init__(self, ledger: SpendLedger, scope: str, limit_usd: float) -> None:
        self._ledger = ledger
        self.scope = scope
        self.limit_usd = limit_usd

    def reserve(self, label: str, *, worst_case_tokens: int) -> str:
        return self._ledger.reserve(
            f"{self.scope}:{label}",
            worst_case_tokens=worst_case_tokens,
            scope=self.scope,
            scope_limit_usd=self.limit_usd,
        )

    def settle(self, entry_id: str, tokens: TokenTotals | None) -> float:
        return self._ledger.settle(entry_id, tokens)

    def status(self) -> SpendStatus:
        return self._ledger.scope_status(self.scope)
