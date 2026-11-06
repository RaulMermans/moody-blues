"""Drives one external agent through one run. The host side of ``mb-agent/1``.

The agent proposes; this decides. Every tool request is checked here before it can reach the
gateway, every answer is exactly what the gateway delivered, and the driver keeps the only clock
and the only counters. It holds a ``ToolPort``, so even it cannot touch the world by other means.

Failure rules:

- A line that is not a valid message ends the run. It is never repaired or re-asked.
- A well-formed call that may not run is answered with a rejection, as a model-driven target's
  would be. Rejected calls are counted, and a flood of them ends the run.
- Nothing here repeats a call. A duplicate ``call_id`` is refused, never run again.
- A run that stops for any reason still goes to the Oracle: whatever the agent did before it
  stopped is real, and the Oracle reads it from committed state.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event
from typing import NoReturn

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from moody_blues.agents.target import InferencePort
from moody_blues.agents.tooling import CRM_TOOLS, error_result, validate_call
from moody_blues.contracts.adapter import (
    AdapterEvent,
    AdapterEventKind,
    AdapterLimits,
    AdapterRejection,
    AdapterRejectionCode,
    AgentManifest,
    CallRejection,
    CancelMessage,
    Capability,
    ExecutionContext,
    FinalMessage,
    HelloMessage,
    ModelCallMessage,
    ModelResultMessage,
    RefusedMessage,
    ToolCallMessage,
    ToolResultMessage,
    WelcomeMessage,
)
from moody_blues.contracts.agent import (
    AgentStep,
    ClaimOutcome,
    EvidenceSource,
    TerminationReason,
    TokenTotals,
    ToolCallDisposition,
    ToolCallRecord,
)
from moody_blues.contracts.common import MoodyBluesError
from moody_blues.contracts.inference import (
    ConversationMessage,
    InferenceRequest,
    InferenceResult,
    ToolCall,
    ToolSpec,
)
from moody_blues.contracts.world import ClaimStatus, FinalClaim
from moody_blues.external.protocol import parse_line
from moody_blues.sandbox.session import (
    ReadStatus,
    SandboxSession,
    SessionClosedError,
    SessionExit,
)
from moody_blues.world.gateway import ToolPort

log = logging.getLogger("moody_blues.external")

_POLL_SECONDS = 0.05
_CONVERSATION: TypeAdapter[list[ConversationMessage]] = TypeAdapter(list[ConversationMessage])


@dataclass(frozen=True, slots=True)
class InferenceBroker:
    """A model the host will call on an agent's behalf. Absent unless an operator enabled it."""

    inference: InferencePort
    evidence: EvidenceSource
    provider: str
    model: str
    max_model_calls: int
    max_total_tokens: int
    max_completion_tokens: int


class _Stopped(Exception):
    def __init__(self, termination: TerminationReason) -> None:
        super().__init__(termination.value)
        self.termination = termination


@dataclass(slots=True)
class DriverOutcome:
    termination: TerminationReason = TerminationReason.ADAPTER_STARTUP_FAILED
    hello: HelloMessage | None = None
    final: FinalMessage | None = None
    claim: FinalClaim | None = None
    startup_ms: int | None = None
    rejection: AdapterRejection | None = None
    rejected_line_sha256: str | None = None
    exit: SessionExit | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list[ToolCallRecord])
    model_steps: list[AgentStep] = field(default_factory=list[AgentStep])
    tokens: TokenTotals = field(default_factory=TokenTotals)
    inference_ms: int = 0
    unknown_evidence_refs: list[str] = field(default_factory=list[str])
    events: list[AdapterEvent] = field(default_factory=list[AdapterEvent])
    transcript_sha256: str = "0" * 64
    transcript_lines: int = 0

    @property
    def claim_outcome(self) -> ClaimOutcome:
        return ClaimOutcome.VALID if self.claim is not None else ClaimOutcome.MISSING


class AdapterDriver:
    def __init__(
        self,
        *,
        session: SandboxSession,
        port: ToolPort,
        manifest: AgentManifest,
        context: ExecutionContext,
        limits: AdapterLimits,
        specs: list[ToolSpec],
        bundle_frame: bytes,
        broker: InferenceBroker | None = None,
        cancel: Event | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._port = port
        self._manifest = manifest
        self._context = context
        self._limits = limits
        self._specs = specs
        self._bundle_frame = bundle_frame
        self._broker = broker
        self._cancel = cancel
        self._monotonic = monotonic
        self._granted = {t.name for t in context.tools}
        self._started = monotonic()
        self._deadline = self._started
        self._cancel_deadline: float | None = None
        self._executed = 0
        self._rejected = 0
        self._seen_calls: set[str] = set()
        self._gateway_refs: set[str] = set()
        self._outcome = DriverOutcome()

    # --- lifecycle ----------------------------------------------------------------------

    def run(self, *, handshake_only: bool = False) -> DriverOutcome:
        """Everything up to the end of the process. The caller then asks the Oracle."""
        out = self._outcome
        self._event(AdapterEventKind.REGISTERED, code=self._manifest.agent_id)
        self._event(AdapterEventKind.STARTED)
        try:
            self._handshake()
            if handshake_only:
                out.termination = TerminationReason.CANCELLED
            else:
                self._loop()
        except _Stopped as stop:
            out.termination = stop.termination
        except SessionClosedError:
            cancelled = self._cancel_deadline is not None
            out.termination = (
                TerminationReason.CANCELLED if cancelled else TerminationReason.ADAPTER_CRASHED
            )
        finally:
            out.exit = self._session.close(self._limits.exit_grace_seconds)
        self._conclude(out, out.exit)
        return out

    def _conclude(self, out: DriverOutcome, ended: SessionExit) -> None:
        """Read the end of the run from what the host saw, not from what the agent said."""
        if out.termination is TerminationReason.ADAPTER_CRASHED and ended.exit_code == 0:
            out.termination = TerminationReason.NO_FINAL_CLAIM  # a clean exit with no report
        if out.termination is TerminationReason.ADAPTER_CRASHED:
            self._event(AdapterEventKind.ADAPTER_CRASHED, code=str(ended.exit_code))
        elif out.termination is TerminationReason.CANCELLED:
            self._event(AdapterEventKind.EXECUTION_CANCELLED)
        else:
            self._event(AdapterEventKind.EXECUTION_COMPLETED, code=out.termination.value)

    def _elapsed_ms(self) -> int:
        return int((self._monotonic() - self._started) * 1000)

    def _event(
        self, kind: AdapterEventKind, *, call_id: str | None = None, code: str | None = None
    ) -> None:
        event = AdapterEvent(
            seq=len(self._outcome.events) + 1,
            elapsed_ms=self._elapsed_ms(),
            kind=kind,
            call_id=call_id,
            code=code,
        )
        self._outcome.events.append(event)
        log.info(
            "adapter_event",
            extra={
                "kind": kind.value,
                "run_id": self._context.run_id,
                "correlation_id": self._context.correlation_id,
                "call_id": call_id,
                "code": code,
            },
        )

    # --- the wire -----------------------------------------------------------------------

    def _note(self, direction: bytes, line: bytes) -> None:
        out = self._outcome
        out.transcript_lines += 1
        out.transcript_sha256 = hashlib.sha256(
            out.transcript_sha256.encode() + direction + line
        ).hexdigest()

    def _send(self, message: BaseModel) -> None:
        line = message.model_dump_json().encode("utf-8")
        self._note(b">", line)
        self._session.send(line + b"\n")

    def _reject_line(self, rejection: AdapterRejection, line: bytes | None) -> None:
        self._outcome.rejection = rejection
        if line is not None:
            self._outcome.rejected_line_sha256 = hashlib.sha256(line).hexdigest()
        self._event(AdapterEventKind.MESSAGE_REJECTED, code=rejection.code.value)

    def _next_line(self, deadline: float, on_timeout: TerminationReason) -> bytes:
        while True:
            self._check_cancel()
            now = self._monotonic()
            if now >= deadline:
                raise _Stopped(on_timeout)
            limit = deadline if self._cancel_deadline is None else self._cancel_deadline
            read = self._session.read_line(min(_POLL_SECONDS, max(limit - now, 0.0)))
            match read.status:
                case ReadStatus.TIMEOUT:
                    continue
                case ReadStatus.LINE:
                    self._note(b"<", read.line)
                    return read.line
                case ReadStatus.CLOSED:
                    raise SessionClosedError
                case ReadStatus.OVERSIZED:
                    self._reject_line(
                        AdapterRejection(
                            code=AdapterRejectionCode.OVERSIZED, detail="a line passed the limit"
                        ),
                        None,
                    )
                    raise _Stopped(TerminationReason.MALFORMED_MESSAGE)

    def _check_cancel(self) -> None:
        if self._cancel is None or not self._cancel.is_set():
            return
        if self._cancel_deadline is None:
            self._cancel_deadline = self._monotonic() + self._limits.cancel_grace_seconds
            self._outcome.termination = TerminationReason.CANCELLED
            self._send(CancelMessage())
        elif self._monotonic() >= self._cancel_deadline:
            raise _Stopped(TerminationReason.CANCELLED)

    # --- handshake ----------------------------------------------------------------------

    def _handshake(self) -> None:
        limit = self._started + self._limits.startup_timeout_seconds
        try:
            self._session.send(self._bundle_frame)
            line = self._next_line(limit, TerminationReason.ADAPTER_STARTUP_FAILED)
        except SessionClosedError:
            raise _Stopped(TerminationReason.ADAPTER_STARTUP_FAILED) from None
        parsed = parse_line(line)
        if isinstance(parsed, AdapterRejection):
            self._refuse(parsed, line)
        if not isinstance(parsed, HelloMessage):
            self._refuse(
                AdapterRejection(
                    code=AdapterRejectionCode.OUT_OF_ORDER, detail="the first message must be hello"
                ),
                line,
            )
        self._outcome.hello = parsed
        problem = self._identity_problem(parsed)
        if problem is not None:
            self._refuse(problem, line)
        self._outcome.startup_ms = self._elapsed_ms()
        self._deadline = self._monotonic() + self._limits.run_timeout_seconds
        self._send(WelcomeMessage(context=self._context))
        self._event(AdapterEventKind.HANDSHAKE_ACCEPTED)

    def _identity_problem(self, hello: HelloMessage) -> AdapterRejection | None:
        agent, manifest = hello.agent, self._manifest
        same = (
            agent.agent_id == manifest.agent_id
            and agent.version == manifest.version
            and agent.target_type == manifest.target_type.value
        )
        if not same:
            return AdapterRejection(
                code=AdapterRejectionCode.IDENTITY_MISMATCH,
                detail="hello does not match the registered manifest",
            )
        if not set(agent.capabilities) <= {c.value for c in manifest.capabilities}:
            return AdapterRejection(
                code=AdapterRejectionCode.CAPABILITY_REFUSED,
                detail="hello claims a capability the manifest does not declare",
            )
        if Capability.TOOLS.value not in agent.capabilities:
            return AdapterRejection(
                code=AdapterRejectionCode.CAPABILITY_REFUSED, detail="tools is required"
            )
        return None

    def _refuse(self, rejection: AdapterRejection, line: bytes) -> NoReturn:
        self._reject_line(rejection, line)
        self._event(AdapterEventKind.HANDSHAKE_REJECTED, code=rejection.code.value)
        with contextlib.suppress(SessionClosedError):  # it is being refused anyway
            self._send(RefusedMessage(code=rejection.code))
        version = rejection.code is AdapterRejectionCode.UNSUPPORTED_PROTOCOL
        raise _Stopped(
            TerminationReason.PROTOCOL_VERSION_MISMATCH
            if version
            else TerminationReason.HANDSHAKE_REJECTED
        )

    # --- the run ------------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            line = self._next_line(self._deadline, TerminationReason.WALL_TIMEOUT)
            parsed = parse_line(line)
            match parsed:
                case AdapterRejection():
                    self._reject_line(parsed, line)
                    raise _Stopped(TerminationReason.MALFORMED_MESSAGE)
                case HelloMessage():
                    self._reject_line(
                        AdapterRejection(
                            code=AdapterRejectionCode.OUT_OF_ORDER, detail="hello was already sent"
                        ),
                        line,
                    )
                    raise _Stopped(TerminationReason.MALFORMED_MESSAGE)
                case ToolCallMessage():
                    self._tool(parsed)
                case ModelCallMessage():
                    self._model(parsed)
                case FinalMessage():
                    self._final(parsed)
                    return

    def _count_rejection(self) -> None:
        self._rejected += 1
        if self._rejected > self._limits.max_rejected_calls:
            raise _Stopped(TerminationReason.REJECTED_CALL_LIMIT)

    def _calls_remaining(self) -> int:
        return max(self._limits.max_tool_calls - self._executed, 0)

    def _refuse_call(
        self,
        message: ToolCallMessage,
        arguments_json: str,
        disposition: ToolCallDisposition,
        text: str,
    ) -> None:
        self._outcome.tool_calls.append(
            ToolCallRecord(
                step=len(self._outcome.tool_calls) + 1,
                tool_call_id=message.call_id,
                name=message.tool,
                arguments_json=arguments_json,
                disposition=disposition,
                result_content=error_result(disposition.value, text),
                error=text,
            )
        )
        self._event(
            AdapterEventKind.TOOL_REQUEST_REJECTED, call_id=message.call_id, code=disposition.value
        )
        self._send(
            ToolResultMessage(
                call_id=message.call_id,
                evidence_ref=None,
                response=None,
                rejection=CallRejection(code=disposition.value, message=text[:500]),
                calls_remaining=self._calls_remaining(),
            )
        )
        self._count_rejection()

    def _check_call(
        self, message: ToolCallMessage, arguments_json: str
    ) -> tuple[ToolCallDisposition, str] | dict[str, JsonValue]:
        """What may run, or why not. Allowlist, scopes and budget are decided here alone."""
        if message.call_id in self._seen_calls:
            return ToolCallDisposition.DUPLICATE_CALL_ID, "this call_id was already used"
        self._seen_calls.add(message.call_id)
        if self._cancel_deadline is not None:
            return ToolCallDisposition.CANCELLED, "not executed: run cancelled"
        if message.tool not in self._granted:
            if message.tool in CRM_TOOLS:
                return ToolCallDisposition.TOOL_NOT_PERMITTED, "outside the scopes of this agent"
            return ToolCallDisposition.UNKNOWN_TOOL, "unknown tool"
        if not isinstance(message.arguments, dict):
            return ToolCallDisposition.INVALID_ARGUMENTS, "arguments must be a JSON object"
        checked = validate_call(
            ToolCall(id=message.call_id, name=message.tool, arguments_json=arguments_json)
        )
        if checked.disposition is not None:
            return checked.disposition, checked.error or checked.disposition.value
        if checked.arguments is None:  # pragma: no cover - valid calls carry arguments
            raise AssertionError("validated call without arguments")
        if self._executed >= self._limits.max_tool_calls:
            return ToolCallDisposition.TOOL_BUDGET_EXHAUSTED, (
                f"not executed: the tool-call budget ({self._limits.max_tool_calls}) is exhausted"
            )
        return checked.arguments

    def _tool(self, message: ToolCallMessage) -> None:
        arguments_json = json.dumps(message.arguments, separators=(",", ":"))
        checked = self._check_call(message, arguments_json)
        if isinstance(checked, tuple):
            self._refuse_call(message, arguments_json, *checked)
            return
        self._event(AdapterEventKind.TOOL_REQUEST_ACCEPTED, call_id=message.call_id)
        self._executed += 1
        delivered = self._port.call(message.tool, checked)  # once, and only here
        self._gateway_refs.add(delivered.call_id)
        self._outcome.tool_calls.append(
            ToolCallRecord(
                step=len(self._outcome.tool_calls) + 1,
                tool_call_id=message.call_id,
                name=message.tool,
                arguments_json=arguments_json,
                disposition=ToolCallDisposition.EXECUTED,
                validated_arguments=checked,
                gateway_call_id=delivered.call_id,
                delivered=delivered,
                result_content=delivered.model_dump_json(exclude_none=True),
            )
        )
        self._send(
            ToolResultMessage(
                call_id=message.call_id,
                evidence_ref=delivered.call_id,
                response=delivered,
                rejection=None,
                calls_remaining=self._calls_remaining(),
            )
        )
        self._event(AdapterEventKind.TOOL_RESPONSE_DELIVERED, call_id=message.call_id)

    # --- host-brokered inference --------------------------------------------------------

    def _refuse_model(self, message: ModelCallMessage, code: str, text: str) -> None:
        self._send(
            ModelResultMessage(
                call_id=message.call_id, rejection=CallRejection(code=code, message=text[:500])
            )
        )
        self._event(AdapterEventKind.TOOL_REQUEST_REJECTED, call_id=message.call_id, code=code)
        self._count_rejection()

    def _model(self, message: ModelCallMessage) -> None:
        broker = self._broker
        out = self._outcome
        if broker is None or Capability.MODEL.value not in self._context.capabilities:
            self._refuse_model(message, "capability_not_granted", "no model for this run")
            return
        if self._cancel_deadline is not None:
            self._refuse_model(message, "cancelled", "run cancelled")
            return
        if len(out.model_steps) >= broker.max_model_calls:
            self._refuse_model(message, "model_call_budget_exhausted", "no model calls left")
            return
        if out.tokens.total_tokens >= broker.max_total_tokens:
            self._refuse_model(message, "token_budget_exhausted", "no tokens left")
            return
        try:
            request = InferenceRequest(
                messages=_CONVERSATION.validate_python(message.messages),
                model=broker.model,
                tools=self._specs,
                tool_choice="auto",
                max_tokens=broker.max_completion_tokens,
                temperature=0.0,
            )
        except ValidationError:
            self._refuse_model(message, "invalid_messages", "the conversation is not valid")
            return
        try:
            result = broker.inference.complete(request)
        except MoodyBluesError as exc:
            # A failed request may still be billed, so the reservation must stay open in full.
            out.tokens = out.tokens.model_copy(update={"complete": False})
            self._refuse_model(message, "provider_error", exc.detail.category.value)
            return
        self._account(request, result)
        self._send(
            ModelResultMessage(
                call_id=message.call_id,
                content=result.content,
                tool_calls=result.tool_calls,
                finish_reason=result.finish_reason,
            )
        )
        self._event(AdapterEventKind.MODEL_CALL_BROKERED, call_id=message.call_id)

    def _account(self, request: InferenceRequest, result: InferenceResult) -> None:
        out = self._outcome
        out.inference_ms += result.latency_ms
        out.model_steps.append(
            AgentStep(
                index=len(out.model_steps) + 1,
                provider=result.provider,
                requested_model=result.requested_model,
                reported_model=result.reported_model,
                response_id=result.response_id,
                finish_reason=result.finish_reason,
                content=result.content,
                tool_call_ids=[c.id for c in result.tool_calls],
                usage=result.usage,
                latency_ms=result.latency_ms,
            )
        )
        usage = result.usage
        if usage is not None and usage.total_tokens is not None:
            prompt, completion = usage.prompt_tokens or 0, usage.completion_tokens or 0
            total, complete = usage.total_tokens, out.tokens.complete
        else:
            prompt = len(request.model_dump_json()) // 4
            completion = len(result.model_dump_json(include={"content", "tool_calls"})) // 4
            total, complete = prompt + completion, False
        out.tokens = TokenTotals(
            prompt_tokens=out.tokens.prompt_tokens + prompt,
            completion_tokens=out.tokens.completion_tokens + completion,
            total_tokens=out.tokens.total_tokens + total,
            complete=complete,
        )

    # --- the report ---------------------------------------------------------------------

    def _final(self, message: FinalMessage) -> None:
        out = self._outcome
        out.final = message
        out.unknown_evidence_refs = sorted(set(message.evidence_refs) - self._gateway_refs)
        if message.completion == "finished" and message.outcome is not None:
            out.claim = FinalClaim(
                status=ClaimStatus(message.outcome.status),
                customer_id=message.outcome.customer_id or None,
                message=message.message,
            )
        if self._cancel_deadline is not None:
            out.termination = TerminationReason.CANCELLED
        elif out.claim is not None:
            out.termination = TerminationReason.FINAL_CLAIM
        else:
            # "cancelled" with no cancel from the host is the agent giving up, too.
            out.termination = TerminationReason.AGENT_REPORTED_FAILURE
