"""Reads a run's fault delivery from its own record. Pure, so it also reads historical evidence.

Only what the gateway recorded counts: ``fault_injected`` means the response changed, and
``fault_effect`` alone means the fault reached a call and could not apply. What an experiment asked
for is the intent. Nothing here looks at a verdict, so validity can never depend on the outcome.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from moody_blues.contracts.run import ToolTraceEntry
from moody_blues.contracts.scenario import FaultEffect, FaultKind, FaultSpec
from moody_blues.contracts.validity import FaultDelivery, RunValidity, ValidityClass

_EFFECT_KINDS: dict[str, FaultKind] = {
    FaultEffect.ABORTED_NEW_WRITE.value: FaultKind.PHANTOM_SUCCESS,
    FaultEffect.NOT_APPLIED_NO_NEW_WRITE.value: FaultKind.PHANTOM_SUCCESS,
    FaultEffect.COMMITTED_WRITE_REPORTED_AS_FAILURE.value: FaultKind.PHANTOM_FAILURE,
    FaultEffect.RESPONSE_REPLACED_WITHOUT_NEW_COMMIT.value: FaultKind.PHANTOM_FAILURE,
    FaultEffect.READ_SERVED_FROM_STALE_SNAPSHOT.value: FaultKind.STALE_READ,
    FaultEffect.NOT_APPLIED_NOTHING_TO_HIDE.value: FaultKind.STALE_READ,
}


def _targeted(trace: Sequence[ToolTraceEntry], kind: FaultKind) -> list[ToolTraceEntry]:
    """Calls this kind of fault reached, in order. Records older than ``fault_effect`` show only
    what was delivered, which is all that can be known of them."""
    return [
        t
        for t in trace
        if t.fault_injected == kind.value
        or (t.fault_effect is not None and _EFFECT_KINDS.get(t.fault_effect) is kind)
    ]


def assess_delivery(
    faults: Sequence[FaultSpec],
    trace: Sequence[ToolTraceEntry],
    source: Literal["scenario", "experiment_selection"],
) -> RunValidity:
    deliveries: list[FaultDelivery] = []
    relevant: set[int] = set()
    for kind in FaultKind:
        reached = _targeted(trace, kind)
        relevant |= {t.call_seq for t in reached}
        specs = sorted((f for f in faults if f.kind is kind), key=lambda f: f.occurrence)
        for spec in specs:
            # Occurrences of one kind are consumed in order, so calls pair off with targets.
            mine, reached = reached[: spec.span], reached[spec.span :]
            applied = [t for t in mine if t.fault_injected is not None]
            deliveries.append(
                FaultDelivery(
                    kind=kind.value,
                    operation=str(spec.operation),
                    occurrence=spec.occurrence,
                    span=spec.span,
                    source=source,
                    trigger_reached=bool(mine),
                    delivered=len(applied),
                    skipped_effects=[
                        t.fault_effect
                        for t in mine
                        if t.fault_injected is None and t.fault_effect is not None
                    ],
                    delivered_at_calls=[t.call_seq for t in applied],
                )
            )
    delivered = sum(d.delivered for d in deliveries)
    if not deliveries:
        classification = ValidityClass.CONTROL
    elif delivered == 0:
        classification = ValidityClass.NOT_EXERCISED
    elif delivered < sum(d.span for d in deliveries):
        classification = ValidityClass.PARTIALLY_EXERCISED
    else:
        classification = ValidityClass.EXERCISED
    eligible = sorted({d.kind for d in deliveries if d.delivered})
    return RunValidity(
        classification=classification,
        faults=deliveries,
        relevant_call_seqs=sorted(relevant),
        eligible_fault_kinds=eligible,
        not_exercised_fault_kinds=sorted({d.kind for d in deliveries} - set(eligible)),
    )
