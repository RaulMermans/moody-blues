"""Agent-facing tool gateway (Layer B): the only way an executor touches the CRM.

Each call produces this evidence, in causal order, before the response is returned:

1. ``tool_call_requested``   — raw arguments as received.
2. ``operation_executed``    — what actually happened (validation result, write outcome).
3. ``fault_injected``        — only when a configured fault targeted this execution.
4. ``tool_response_delivered`` — exactly what the executor sees.

Fault boundaries are explicit, and what a fault does depends on the call's *real* outcome
(recorded as a ``FaultEffect``):

- ``phantom_success`` acts at the **pre-commit** boundary of a *new* write: the staged row is
  rolled back, then a success response is fabricated (``aborted_new_write``). A call that
  never stages a new row (idempotent replay, idempotency conflict, genuine transaction
  failure) has no such boundary: the fault is **not applied**, the genuine response is
  delivered and a ``fault_skipped`` event records why (``not_applied_no_new_write``).
- ``phantom_failure`` acts **after** the write: if the call committed a new row, the
  response is replaced by the configured error (``committed_write_reported_as_failure``);
  if it committed nothing new, only the response is replaced
  (``response_replaced_without_new_commit``) and the evidence says ``new_commit: false``.

A targeted occurrence is consumed either way; it never carries over to a later call.
Faults never touch rows other than the targeted call's own staged write.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, JsonValue, ValidationError

from moody_blues.contracts.scenario import FaultEffect, FaultKind, FaultSpec
from moody_blues.contracts.world import (
    CreateCustomerArgs,
    CustomerRecord,
    EventKind,
    GetCustomerArgs,
    SearchCustomersArgs,
    ToolError,
    ToolErrorCode,
    ToolName,
    ToolResponse,
    ToolSpec,
)
from moody_blues.world.faults import FaultInjector
from moody_blues.world.store import CommitDecision, CrmStore, InsertResult, WriteOutcome

ARG_MODELS: dict[ToolName, type[BaseModel]] = {
    ToolName.CREATE_CUSTOMER: CreateCustomerArgs,
    ToolName.GET_CUSTOMER: GetCustomerArgs,
    ToolName.SEARCH_CUSTOMERS: SearchCustomersArgs,
}

_DESCRIPTIONS: dict[ToolName, str] = {
    ToolName.CREATE_CUSTOMER: (
        "Create a customer. Emails are not unique. Pass a client_request_id to make retries "
        "idempotent: repeating a request with the same id and attributes returns the "
        "original customer instead of creating another."
    ),
    ToolName.GET_CUSTOMER: "Fetch one customer by customer_id.",
    ToolName.SEARCH_CUSTOMERS: (
        "Search customers by exact email and/or a case-insensitive name substring. "
        "With no filters, lists customers in creation order."
    ),
}


TRANSACTION_FAILED = "transaction_failed"


def _fault_effect(kind: FaultKind, *, boundary_reached: bool, committed: bool) -> FaultEffect:
    """Map a targeted fault onto the call's real outcome. Labels follow what happened."""
    match kind:
        case FaultKind.PHANTOM_SUCCESS:
            return (
                FaultEffect.ABORTED_NEW_WRITE
                if boundary_reached
                else FaultEffect.NOT_APPLIED_NO_NEW_WRITE
            )
        case FaultKind.PHANTOM_FAILURE:
            return (
                FaultEffect.COMMITTED_WRITE_REPORTED_AS_FAILURE
                if committed
                else FaultEffect.RESPONSE_REPLACED_WITHOUT_NEW_COMMIT
            )


class ToolPort(Protocol):
    """What an executor (later: the target agent) is given. Nothing else."""

    def call(self, tool: str, arguments: Mapping[str, JsonValue]) -> ToolResponse: ...


def derive_customer_id(seed: int, call_seq: int) -> str:
    """Deterministic, unique per call. A phantom id is never reused by a later real create."""
    digest = hashlib.sha256(f"moody-blues:{seed}:{call_seq}".encode()).hexdigest()
    return f"cus_{digest[:16]}"


def tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(name=name, description=_DESCRIPTIONS[name], parameters=model.model_json_schema())
        for name, model in ARG_MODELS.items()
    ]


def agent_view(record: CustomerRecord) -> dict[str, JsonValue]:
    """The customer as shown to agents: internal provenance (``created_by_call``) omitted."""
    return record.model_dump(mode="json", exclude={"created_by_call"})


def _ok(call_id: str, tool: ToolName, data: dict[str, JsonValue]) -> ToolResponse:
    return ToolResponse(call_id=call_id, tool=tool.value, ok=True, data=data)


def _err(
    call_id: str, tool: str, code: ToolErrorCode, message: str, *, retryable: bool = False
) -> ToolResponse:
    return ToolResponse(
        call_id=call_id,
        tool=tool,
        ok=False,
        error=ToolError(code=code, message=message, retryable=retryable),
    )


def _validation_message(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()]
    return "; ".join(parts)[:500]


class ToolGateway:
    def __init__(
        self,
        store: CrmStore,
        *,
        seed: int,
        faults: list[FaultSpec],
        clock: Callable[[int], datetime],
    ) -> None:
        self._store = store
        self._seed = seed
        self._faults = FaultInjector(faults)
        self._clock = clock
        self._call_seq = 0

    @property
    def calls_made(self) -> int:
        return self._call_seq

    def call(self, tool: str, arguments: Mapping[str, JsonValue]) -> ToolResponse:
        self._call_seq += 1
        call_seq = self._call_seq
        call_id = f"call_{call_seq:04d}"
        now = self._clock(call_seq)

        def emit(kind: EventKind, payload: dict[str, Any]) -> None:
            self._store.append_event(kind, call_seq=call_seq, logical_time=now, payload=payload)

        emit(
            EventKind.TOOL_CALL_REQUESTED,
            {"call_id": call_id, "tool": tool, "arguments": dict(arguments)},
        )
        response = self._dispatch(tool, arguments, call_seq, call_id, now, emit)
        emit(
            EventKind.TOOL_RESPONSE_DELIVERED,
            {"call_id": call_id, "response": response.model_dump(mode="json")},
        )
        return response

    def _dispatch(
        self,
        tool: str,
        arguments: Mapping[str, JsonValue],
        call_seq: int,
        call_id: str,
        now: datetime,
        emit: Callable[[EventKind, dict[str, Any]], None],
    ) -> ToolResponse:
        try:
            name = ToolName(tool)
        except ValueError:
            emit(EventKind.OPERATION_EXECUTED, {"tool": tool, "outcome": "unknown_tool"})
            known = ", ".join(t.value for t in ToolName)
            return _err(call_id, tool, ToolErrorCode.UNKNOWN_TOOL, f"unknown tool; use {known}")

        try:
            args = ARG_MODELS[name].model_validate(dict(arguments))
        except ValidationError as exc:
            message = _validation_message(exc)
            emit(
                EventKind.OPERATION_EXECUTED,
                {"tool": name.value, "outcome": "rejected_invalid_arguments", "detail": message},
            )
            return _err(call_id, name.value, ToolErrorCode.VALIDATION_ERROR, message)

        match args:
            case CreateCustomerArgs():
                return self._create(args, call_seq, call_id, now, emit)
            case GetCustomerArgs():
                found = self._store.get_customer(args.customer_id)
                emit(
                    EventKind.OPERATION_EXECUTED,
                    {"tool": name.value, "outcome": "read", "found": found is not None},
                )
                if found is None:
                    return _err(call_id, name.value, ToolErrorCode.NOT_FOUND, "customer not found")
                return _ok(call_id, name, {"customer": agent_view(found)})
            case SearchCustomersArgs():
                rows = self._store.search_customers(
                    email=args.email, name_contains=args.name_contains, limit=args.limit
                )
                emit(
                    EventKind.OPERATION_EXECUTED,
                    {"tool": name.value, "outcome": "read", "result_count": len(rows)},
                )
                return _ok(
                    call_id,
                    name,
                    {"customers": [agent_view(r) for r in rows], "count": len(rows)},
                )
            case _:  # pragma: no cover - ARG_MODELS is exhaustive
                raise AssertionError(f"unhandled tool {name}")

    def _create(
        self,
        args: CreateCustomerArgs,
        call_seq: int,
        call_id: str,
        now: datetime,
        emit: Callable[[EventKind, dict[str, Any]], None],
    ) -> ToolResponse:
        tool = ToolName.CREATE_CUSTOMER
        target = self._faults.next_execution(tool)
        fault = target.spec
        record = CustomerRecord(
            customer_id=derive_customer_id(self._seed, call_seq),
            name=args.name,
            email=args.email,
            metadata=args.metadata,
            client_request_id=args.client_request_id,
            created_at=now,
            created_by_call=call_seq,
        )
        boundary_reached = False

        def pre_commit_boundary() -> CommitDecision:
            # Runs only when a *new* row has been staged: never for idempotent replays,
            # idempotency conflicts or writes that failed before staging completed.
            nonlocal boundary_reached
            boundary_reached = True
            if fault is not None and fault.kind is FaultKind.PHANTOM_SUCCESS:
                return CommitDecision.ABORT
            return CommitDecision.COMMIT

        outcome: str
        try:
            result = self._store.insert_customer(record, before_commit=pre_commit_boundary)
        except sqlite3.Error as exc:
            # A genuine (unfaulted) transaction failure. The store already rolled back.
            outcome = TRANSACTION_FAILED
            emit(
                EventKind.OPERATION_EXECUTED,
                {
                    "tool": tool.value,
                    "occurrence": target.occurrence,
                    "outcome": outcome,
                    "new_commit": False,
                    "detail": f"{type(exc).__name__}: {exc}"[:300],
                    "attempted_customer_id": record.customer_id,
                },
            )
            actual = _err(
                call_id,
                tool.value,
                ToolErrorCode.INTERNAL_ERROR,
                "the customer could not be saved; nothing was written",
                retryable=True,
            )
        else:
            outcome = result.outcome.value
            emit(
                EventKind.OPERATION_EXECUTED,
                {
                    "tool": tool.value,
                    "occurrence": target.occurrence,
                    "outcome": outcome,
                    "new_commit": result.outcome is WriteOutcome.COMMITTED,
                    "attempted_customer_id": record.customer_id,
                    "result_customer_id": result.record.customer_id if result.record else None,
                },
            )
            actual = self._actual_create_response(call_id, result)

        if fault is None:
            return actual
        new_commit = outcome == WriteOutcome.COMMITTED.value
        effect = _fault_effect(fault.kind, boundary_reached=boundary_reached, committed=new_commit)
        evidence: dict[str, Any] = {
            "kind": fault.kind.value,
            "operation": fault.operation.value,
            "occurrence": target.occurrence,
            "effect": effect.value,
            "call_outcome": outcome,
            "new_commit": new_commit,
            "actual_response": actual.model_dump(mode="json"),
        }
        if effect is FaultEffect.NOT_APPLIED_NO_NEW_WRITE:
            emit(EventKind.FAULT_SKIPPED, evidence | {"boundary": None})
            return actual
        boundary = {
            FaultEffect.ABORTED_NEW_WRITE: "pre_commit",
            FaultEffect.COMMITTED_WRITE_REPORTED_AS_FAILURE: "post_commit",
            FaultEffect.RESPONSE_REPLACED_WITHOUT_NEW_COMMIT: "response",
        }[effect]
        delivered = self._distort(call_id, fault, record)
        emit(EventKind.FAULT_INJECTED, evidence | {"boundary": boundary})
        return delivered

    @staticmethod
    def _actual_create_response(call_id: str, result: InsertResult) -> ToolResponse:
        tool = ToolName.CREATE_CUSTOMER
        match result.outcome:
            case WriteOutcome.COMMITTED | WriteOutcome.IDEMPOTENT_REPLAY:
                if result.record is None:  # pragma: no cover - store invariant
                    raise RuntimeError("store returned a success outcome without a record")
                return _ok(
                    call_id,
                    tool,
                    {
                        "customer": agent_view(result.record),
                        "idempotent_replay": result.outcome is WriteOutcome.IDEMPOTENT_REPLAY,
                    },
                )
            case WriteOutcome.IDEMPOTENCY_CONFLICT:
                return _err(
                    call_id,
                    tool.value,
                    ToolErrorCode.IDEMPOTENCY_CONFLICT,
                    "client_request_id was already used with different attributes",
                )
            case WriteOutcome.ABORTED_PRE_COMMIT:
                # Only a fault aborts; its distortion replaces this. Kept honest regardless.
                return _err(
                    call_id,
                    tool.value,
                    ToolErrorCode.INTERNAL_ERROR,
                    "the customer was not saved",
                    retryable=True,
                )

    @staticmethod
    def _distort(call_id: str, fault: FaultSpec, attempted: CustomerRecord) -> ToolResponse:
        """The delivered response depends only on the fault, never on the actual outcome."""
        tool = ToolName.CREATE_CUSTOMER
        match fault.kind:
            case FaultKind.PHANTOM_FAILURE:
                return _err(
                    call_id, tool.value, fault.error_code, fault.error_message, retryable=True
                )
            case FaultKind.PHANTOM_SUCCESS:
                # Indistinguishable in shape from a genuine success; the id was never committed.
                return _ok(
                    call_id, tool, {"customer": agent_view(attempted), "idempotent_replay": False}
                )
