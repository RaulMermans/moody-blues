"""Deterministic, experiment-scoped fault targeting.

A ``FaultInjector`` belongs to exactly one world. It counts eligible executions per operation
and returns the ``FaultSpec`` configured for that occurrence, if any. No randomness: given the
same call sequence, the same calls are hit. With no specs configured it never fires.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from moody_blues.contracts.scenario import FaultSpec
from moody_blues.contracts.world import ToolName


@dataclass(frozen=True, slots=True)
class FaultTarget:
    occurrence: int
    spec: FaultSpec | None


class FaultInjector:
    def __init__(self, specs: Sequence[FaultSpec]) -> None:
        self._specs = {(s.operation, s.occurrence): s for s in specs}
        if len(self._specs) != len(specs):
            raise ValueError("duplicate fault target (operation, occurrence)")
        self._counts: Counter[ToolName] = Counter()

    @property
    def enabled(self) -> bool:
        return bool(self._specs)

    def next_execution(self, operation: ToolName) -> FaultTarget:
        """Register one eligible execution of ``operation`` and return its fault, if any."""
        self._counts[operation] += 1
        occurrence = self._counts[operation]
        return FaultTarget(occurrence, self._specs.get((operation, occurrence)))
