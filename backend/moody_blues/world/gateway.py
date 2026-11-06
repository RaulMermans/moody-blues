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
- ``stale_read`` acts on the **response of a read**: rows committed during this run are left
  out, as if a lagging replica had served the call (``read_served_from_stale_snapshot``). If
  there was nothing to leave out, the fault is not applied (``not_applied_nothing_to_hide``).
  It never writes, so committed state and the Oracle are unaffected.

A targeted occurrence is consumed either way; it never carries over to a later call.
Faults never touch rows other than the targeted call's own staged write.

``GatewayCore`` owns all of that, so every world gets the same four events and the same fault
boundaries. A world supplies its tools and what a write or a read does, and nothing else: it
cannot deliver a response around the pipeline, and it cannot decide what a fault means.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, JsonValue, ValidationError

from moody_blues.contracts.scenario import READ_OPERATION, FaultEffect, FaultKind, FaultSpec
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
from moody_blues.world.faults import FaultInjector, FaultTarget
from moody_blues.world.store import (
    BeforeCommit,
    CommitDecision,
    CrmStore,
    InsertResult,
    WorldStore,
    WriteOutcome,
)

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
        case FaultKind.STALE_READ:  # pragma: no cover - reads are handled by ``_read``
            raise AssertionError("stale_read does not target writes")


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


def ok_response(call_id: str, tool: str, data: dict[str, JsonValue]) -> ToolResponse:
    return ToolResponse(call_id=call_id, tool=tool, ok=True, data=data)


def error_response(
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


Emit = Callable[[EventKind, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class CallContext:
    """One gateway call, as a world's operation sees it."""

    call_seq: int
    call_id: str
    now: datetime
    emit: Emit


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What a world's write really did. ``actual`` is the response it deserves, undistorted."""

    outcome: str  # a ``WriteOutcome`` value
    facts: dict[str, Any]  # world-named ids, recorded on ``operation_executed``
    actual: ToolResponse


class GatewayCore:
    """The call pipeline and the fault boundaries, identical in every world."""

    def __init__(
        self,
        store: WorldStore,
        *,
        arg_models: Mapping[str, type[BaseModel]],
        faults: list[FaultSpec],
        clock: Callable[[int], datetime],
    ) -> None:
        self._evidence = store
        self._arg_models = arg_models
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
            self._evidence.append_event(kind, call_seq=call_seq, logical_time=now, payload=payload)

        emit(
            EventKind.TOOL_CALL_REQUESTED,
            {"call_id": call_id, "tool": tool, "arguments": dict(arguments)},
        )
        self._before_call(call_seq, now)
        response = self._dispatch(tool, arguments, CallContext(call_seq, call_id, now, emit))
        emit(
            EventKind.TOOL_RESPONSE_DELIVERED,
            {"call_id": call_id, "response": response.model_dump(mode="json")},
        )
        return response

    def _before_call(self, call_seq: int, now: datetime) -> None:
        """Time passes in a world only as calls arrive. Most worlds have nothing to do here."""

    def _dispatch(
        self, tool: str, arguments: Mapping[str, JsonValue], ctx: CallContext
    ) -> ToolResponse:
        model = self._arg_models.get(tool)
        if model is None:
            ctx.emit(EventKind.OPERATION_EXECUTED, {"tool": tool, "outcome": "unknown_tool"})
            known = ", ".join(self._arg_models)
            return error_response(
                ctx.call_id, tool, ToolErrorCode.UNKNOWN_TOOL, f"unknown tool; use {known}"
            )
        try:
            args = model.model_validate(dict(arguments))
        except ValidationError as exc:
            message = _validation_message(exc)
            ctx.emit(
                EventKind.OPERATION_EXECUTED,
                {"tool": tool, "outcome": "rejected_invalid_arguments", "detail": message},
            )
            return error_response(ctx.call_id, tool, ToolErrorCode.VALIDATION_ERROR, message)
        return self._execute(tool, args, ctx)

    def _execute(self, tool: str, args: BaseModel, ctx: CallContext) -> ToolResponse:
        raise NotImplementedError

    def _faulted_read(
        self,
        ctx: CallContext,
        *,
        target: FaultTarget,
        actual: ToolResponse,
        hidden: int,
        stale: Callable[[], ToolResponse],
    ) -> ToolResponse:
        """Deliver ``actual``, or what a lagging replica would have said if a fault targets it."""
        if target.spec is None:
            return actual
        effect = (
            FaultEffect.READ_SERVED_FROM_STALE_SNAPSHOT
            if hidden
            else FaultEffect.NOT_APPLIED_NOTHING_TO_HIDE
        )
        evidence: dict[str, Any] = {
            "kind": FaultKind.STALE_READ.value,
            "operation": READ_OPERATION,
            "occurrence": target.occurrence,
            "effect": effect.value,
            "call_outcome": "read",
            "new_commit": False,
            "rows_hidden": hidden,
            "actual_response": actual.model_dump(mode="json"),
        }
        if not hidden:
            ctx.emit(EventKind.FAULT_SKIPPED, evidence | {"boundary": None})
            return actual
        ctx.emit(EventKind.FAULT_INJECTED, evidence | {"boundary": "response"})
        return stale()

    def _faulted_write(
        self,
        ctx: CallContext,
        *,
        operation: str,
        attempted: dict[str, Any],
        perform: Callable[[BeforeCommit], WriteResult],
        failed: ToolResponse,
        distort: Callable[[FaultSpec], ToolResponse],
    ) -> ToolResponse:
        """Run one write through the pre-commit boundary, then decide what the caller is told."""
        target = self._faults.next_execution(operation)
        fault = target.spec
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
            result = perform(pre_commit_boundary)
        except sqlite3.Error as exc:
            # A genuine (unfaulted) transaction failure. The store already rolled back.
            outcome = TRANSACTION_FAILED
            ctx.emit(
                EventKind.OPERATION_EXECUTED,
                {
                    "tool": operation,
                    "occurrence": target.occurrence,
                    "outcome": outcome,
                    "new_commit": False,
                    "detail": f"{type(exc).__name__}: {exc}"[:300],
                }
                | attempted,
            )
            actual = failed
        else:
            outcome = result.outcome
            ctx.emit(
                EventKind.OPERATION_EXECUTED,
                {
                    "tool": operation,
                    "occurrence": target.occurrence,
                    "outcome": outcome,
                    "new_commit": outcome == WriteOutcome.COMMITTED.value,
                }
                | attempted
                | result.facts,
            )
            actual = result.actual

        if fault is None:
            return actual
        new_commit = outcome == WriteOutcome.COMMITTED.value
        effect = _fault_effect(fault.kind, boundary_reached=boundary_reached, committed=new_commit)
        evidence: dict[str, Any] = {
            "kind": fault.kind.value,
            "operation": operation,
            "occurrence": target.occurrence,
            "effect": effect.value,
            "call_outcome": outcome,
            "new_commit": new_commit,
            "actual_response": actual.model_dump(mode="json"),
        }
        if effect is FaultEffect.NOT_APPLIED_NO_NEW_WRITE:
            ctx.emit(EventKind.FAULT_SKIPPED, evidence | {"boundary": None})
            return actual
        boundary = {
            FaultEffect.ABORTED_NEW_WRITE: "pre_commit",
            FaultEffect.COMMITTED_WRITE_REPORTED_AS_FAILURE: "post_commit",
            FaultEffect.RESPONSE_REPLACED_WITHOUT_NEW_COMMIT: "response",
        }[effect]
        delivered = distort(fault)
        ctx.emit(EventKind.FAULT_INJECTED, evidence | {"boundary": boundary})
        return delivered


class ToolGateway(GatewayCore):
    """The CRM's three tools."""

    def __init__(
        self,
        store: CrmStore,
        *,
        seed: int,
        faults: list[FaultSpec],
        clock: Callable[[int], datetime],
    ) -> None:
        super().__init__(
            store,
            arg_models={name.value: model for name, model in ARG_MODELS.items()},
            faults=faults,
            clock=clock,
        )
        self._store = store
        self._seed = seed

    def _execute(self, tool: str, args: BaseModel, ctx: CallContext) -> ToolResponse:
        match args:
            case CreateCustomerArgs():
                return self._create(args, ctx)
            case GetCustomerArgs() | SearchCustomersArgs():
                return self._read(args, ctx)
            case _:  # pragma: no cover - ARG_MODELS is exhaustive
                raise AssertionError(f"unhandled tool {tool}")

    def _read(self, args: GetCustomerArgs | SearchCustomersArgs, ctx: CallContext) -> ToolResponse:
        target = self._faults.next_execution(READ_OPERATION)
        match args:
            case GetCustomerArgs():
                name = ToolName.GET_CUSTOMER
                found = self._store.get_customer(args.customer_id)
                rows = [] if found is None else [found]
                ctx.emit(
                    EventKind.OPERATION_EXECUTED,
                    {"tool": name.value, "outcome": "read", "found": found is not None},
                )
            case SearchCustomersArgs():
                name = ToolName.SEARCH_CUSTOMERS
                rows = self._store.search_customers(
                    email=args.email, name_contains=args.name_contains, limit=args.limit
                )
                ctx.emit(
                    EventKind.OPERATION_EXECUTED,
                    {"tool": name.value, "outcome": "read", "result_count": len(rows)},
                )

        def respond(visible: list[CustomerRecord]) -> ToolResponse:
            if name is ToolName.SEARCH_CUSTOMERS:
                data: dict[str, JsonValue] = {
                    "customers": [agent_view(r) for r in visible],
                    "count": len(visible),
                }
                return ok_response(ctx.call_id, name.value, data)
            if not visible:
                return error_response(
                    ctx.call_id, name.value, ToolErrorCode.NOT_FOUND, "customer not found"
                )
            return ok_response(ctx.call_id, name.value, {"customer": agent_view(visible[0])})

        snapshot = [r for r in rows if r.created_by_call == 0]  # seed rows predate the run
        return self._faulted_read(
            ctx,
            target=target,
            actual=respond(rows),
            hidden=len(rows) - len(snapshot),
            stale=lambda: respond(snapshot),
        )

    def _create(self, args: CreateCustomerArgs, ctx: CallContext) -> ToolResponse:
        tool = ToolName.CREATE_CUSTOMER
        record = CustomerRecord(
            customer_id=derive_customer_id(self._seed, ctx.call_seq),
            name=args.name,
            email=args.email,
            metadata=args.metadata,
            client_request_id=args.client_request_id,
            created_at=ctx.now,
            created_by_call=ctx.call_seq,
        )

        def perform(before_commit: BeforeCommit) -> WriteResult:
            result = self._store.insert_customer(record, before_commit=before_commit)
            return WriteResult(
                outcome=result.outcome.value,
                facts={"result_customer_id": result.record.customer_id if result.record else None},
                actual=self._actual_create_response(ctx.call_id, result),
            )

        return self._faulted_write(
            ctx,
            operation=tool.value,
            attempted={"attempted_customer_id": record.customer_id},
            perform=perform,
            failed=error_response(
                ctx.call_id,
                tool.value,
                ToolErrorCode.INTERNAL_ERROR,
                "the customer could not be saved; nothing was written",
                retryable=True,
            ),
            distort=lambda fault: self._distort(ctx.call_id, fault, record),
        )

    @staticmethod
    def _actual_create_response(call_id: str, result: InsertResult) -> ToolResponse:
        tool = ToolName.CREATE_CUSTOMER
        match result.outcome:
            case WriteOutcome.COMMITTED | WriteOutcome.IDEMPOTENT_REPLAY:
                if result.record is None:  # pragma: no cover - store invariant
                    raise RuntimeError("store returned a success outcome without a record")
                return ok_response(
                    call_id,
                    tool.value,
                    {
                        "customer": agent_view(result.record),
                        "idempotent_replay": result.outcome is WriteOutcome.IDEMPOTENT_REPLAY,
                    },
                )
            case WriteOutcome.IDEMPOTENCY_CONFLICT:
                return error_response(
                    call_id,
                    tool.value,
                    ToolErrorCode.IDEMPOTENCY_CONFLICT,
                    "client_request_id was already used with different attributes",
                )
            case WriteOutcome.ABORTED_PRE_COMMIT:
                # Only a fault aborts; its distortion replaces this. Kept honest regardless.
                return error_response(
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
                return error_response(
                    call_id, tool.value, fault.error_code, fault.error_message, retryable=True
                )
            case FaultKind.PHANTOM_SUCCESS:
                # Indistinguishable in shape from a genuine success; the id was never committed.
                return ok_response(
                    call_id,
                    tool.value,
                    {"customer": agent_view(attempted), "idempotent_replay": False},
                )
            case FaultKind.STALE_READ:  # pragma: no cover - reads are handled by ``_read``
                raise AssertionError("stale_read does not target writes")
