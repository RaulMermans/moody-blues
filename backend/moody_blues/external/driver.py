"""Drives one external agent through one run. The host side of ``mb-agent/1``.

The agent proposes; this decides. Every tool request is checked here before it can reach the
gateway, every answer is exactly what the gateway delivered, and the driver keeps the only clock
and the only counters. It holds a ``ToolPort``, so even it cannot touch the world by other means.

Failure rules:

- A line that is not a valid message ends the run. It is never repaired or re-asked.
- A well-formed call that may not run is answered with a rejection, as a model-driven target's
  would be. Rejected calls are counted, and a flood of them ends the run.
- Nothing here repeats a call. A duplicate ``call_id`` is refused, never run again. That holds for
  model calls too, and the broker's client must not retry: a request that timed out may have run
  and may be billed, so it is recorded as uncertain and the agent decides what to do next.
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
from pathlib import Path
from threading import Event, Thread
from typing import NoReturn

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from moody_blues.agents.target import InferencePort
from moody_blues.agents.tooling import error_result, validate_call
from moody_blues.contracts.adapter import (
    MODEL_ATTEMPTED,
    AdapterEvent,
    AdapterEventKind,
    AdapterLimits,
    AdapterRejection,
    AdapterRejectionCode,
    AgentManifest,
    AgentOutcome,
    CallRejection,
    CancelMessage,
    Capability,
    ExecutionContext,
    FinalMessage,
    HelloMessage,
    ModelCallMessage,
    ModelCallRecord,
    ModelCallStatus,
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
from moody_blues.contracts.common import ErrorCategory, ErrorDetail, MoodyBluesError
from moody_blues.contracts.inference import (
    ConversationMessage,
    InferenceRequest,
    InferenceResult,
    LocalModelIdentity,
    ToolCall,
    ToolSpec,
)
from moody_blues.contracts.world import AnyClaim, ClaimStatus
from moody_blues.external.protocol import parse_line
from moody_blues.sandbox.session import (
    ReadStatus,
    SandboxSession,
    SessionClosedError,
    SessionExit,
)
from moody_blues.world.crm_plugin import WORLD_TYPE as CRM_WORLD_TYPE
from moody_blues.world.gateway import ToolPort
from moody_blues.world.plugin import WorldPlugin
from moody_blues.world.registry import world_plugin

log = logging.getLogger("moody_blues.external")

_POLL_SECONDS = 0.05
_CONVERSATION: TypeAdapter[list[ConversationMessage]] = TypeAdapter(list[ConversationMessage])
# Below the agent's line limit, so that a prompt is refused as a prompt and not as a broken line.
DEFAULT_MAX_PROMPT_BYTES = 48_000
DEFAULT_MODEL_CALL_TIMEOUT_SECONDS = 45.0
# The provider may have done the work, so a failure of these kinds cannot be read as "not billed".
_AMBIGUOUS_FAILURES = frozenset(
    {
        ErrorCategory.PROVIDER_TIMEOUT,
        ErrorCategory.PROVIDER_CONNECTION,
        ErrorCategory.PROVIDER_SERVER_ERROR,
    }
)
# A model the host stopped lending explains why the agent gave up, so the run says so.
_REFUSALS_THAT_END_A_RUN = {
    "model_call_budget_exhausted": TerminationReason.MAX_STEPS,
    "token_budget_exhausted": TerminationReason.TOKEN_BUDGET,
}
_FAILED_MODEL_STATES = frozenset(
    {ModelCallStatus.FAILED, ModelCallStatus.MALFORMED, ModelCallStatus.UNCERTAIN}
)


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
    max_prompt_bytes: int = DEFAULT_MAX_PROMPT_BYTES
    call_timeout_seconds: float = DEFAULT_MODEL_CALL_TIMEOUT_SECONDS
    # Sprint 17. Stops a generation the host gave up on, where the provider can. Without it an
    # abandoned local call would keep the machine busy after the run had moved on.
    abort: Callable[[], None] | None = None
    identity: LocalModelIdentity | None = None


class _Stopped(Exception):
    def __init__(self, termination: TerminationReason) -> None:
        super().__init__(termination.value)
        self.termination = termination


@dataclass(slots=True)
class DriverOutcome:
    termination: TerminationReason = TerminationReason.ADAPTER_STARTUP_FAILED
    hello: HelloMessage | None = None
    final: FinalMessage | None = None
    claim: AnyClaim | None = None
    startup_ms: int | None = None
    rejection: AdapterRejection | None = None
    rejected_line_sha256: str | None = None
    exit: SessionExit | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list[ToolCallRecord])
    model_steps: list[AgentStep] = field(default_factory=list[AgentStep])
    model_requests: list[ModelCallRecord] = field(default_factory=list[ModelCallRecord])
    model_error: ErrorDetail | None = None
    tokens: TokenTotals = field(default_factory=TokenTotals)
    inference_ms: int = 0
    unknown_evidence_refs: list[str] = field(default_factory=list[str])
    events: list[AdapterEvent] = field(default_factory=list[AdapterEvent])
    transcript_sha256: str = "0" * 64
    transcript_lines: int = 0

    @property
    def claim_outcome(self) -> ClaimOutcome:
        return ClaimOutcome.VALID if self.claim is not None else ClaimOutcome.MISSING

    @property
    def model_attempts(self) -> int:
        """Requests that reached a provider. Only these can make a run an LLM run."""
        return sum(r.status in MODEL_ATTEMPTED for r in self.model_requests)


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
        model_intents: Path | None = None,
        world: WorldPlugin | None = None,
    ) -> None:
        self._model_intents = model_intents
        self._world = world or world_plugin(CRM_WORLD_TYPE)
        self._arg_models = self._world.arg_models()
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
        self._attribute_to_model(out)
        if out.termination is TerminationReason.ADAPTER_CRASHED:
            self._event(AdapterEventKind.ADAPTER_CRASHED, code=str(ended.exit_code))
        elif out.termination is TerminationReason.CANCELLED:
            self._event(AdapterEventKind.EXECUTION_CANCELLED)
        else:
            self._event(AdapterEventKind.EXECUTION_COMPLETED, code=out.termination.value)

    @staticmethod
    def _attribute_to_model(out: DriverOutcome) -> None:
        """An agent that gave up because the host's model failed it did not fall short itself.

        Only when the last thing that happened to it was that failure, and it made no claim.
        """
        gave_up = out.termination in {
            TerminationReason.AGENT_REPORTED_FAILURE,
            TerminationReason.NO_FINAL_CLAIM,
        }
        if not gave_up or not out.model_requests:
            return
        last = out.model_requests[-1]
        if last.status in _FAILED_MODEL_STATES:
            out.termination = TerminationReason.PROVIDER_ERROR
        elif last.code in _REFUSALS_THAT_END_A_RUN:
            out.termination = _REFUSALS_THAT_END_A_RUN[last.code]

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
            # A tool of this world the agent's scopes leave out. Any other world's tool is, from
            # here, simply unknown: it does not exist in this run, and no gateway hears of it.
            if message.tool in self._arg_models:
                return ToolCallDisposition.TOOL_NOT_PERMITTED, "outside the scopes of this agent"
            return ToolCallDisposition.UNKNOWN_TOOL, "unknown tool"
        if not isinstance(message.arguments, dict):
            return ToolCallDisposition.INVALID_ARGUMENTS, "arguments must be a JSON object"
        checked = validate_call(
            ToolCall(id=message.call_id, name=message.tool, arguments_json=arguments_json),
            self._arg_models,
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

    def _note_model(
        self,
        message: ModelCallMessage,
        request_id: str,
        status: ModelCallStatus,
        code: str | None,
        result: InferenceResult | None = None,
        latency_ms: int | None = None,
    ) -> None:
        text = json.dumps(message.messages, separators=(",", ":"), sort_keys=True).encode()
        broker = self._broker
        usage = result.usage if result is not None else None
        record = ModelCallRecord(
            request_id=request_id,
            call_id=message.call_id,
            status=status,
            code=code,
            provider=None if status is ModelCallStatus.REJECTED or not broker else broker.provider,
            model=None if status is ModelCallStatus.REJECTED or not broker else broker.model,
            reported_model=result.reported_model if result is not None else None,
            response_id=result.response_id if result is not None else None,
            finish_reason=result.finish_reason if result is not None else None,
            prompt_bytes=len(text),
            prompt_sha256=hashlib.sha256(text).hexdigest(),
            response_sha256=hashlib.sha256(
                result.model_dump_json(include={"content", "tool_calls"}).encode()
            ).hexdigest()
            if result is not None
            else None,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
            latency_ms=latency_ms,
            timings=result.timings if result is not None else None,
        )
        self._outcome.model_requests.append(record)
        self._write_intent({"request_id": request_id, "status": status.value})
        log.info(
            "adapter_model_call",
            extra={
                "run_id": self._context.run_id,
                "correlation_id": self._context.correlation_id,
                "request_id": request_id,
                "status": status.value,
                "code": code,
                "latency_ms": latency_ms,
                "retries": 0,  # the broker never retries; see the module docstring
            },
        )

    def _write_intent(self, entry: dict[str, str]) -> None:
        """Write-ahead, so that a crash cannot lose the fact that a provider may have been asked."""
        if self._model_intents is None:
            return
        with self._model_intents.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\n")
            stream.flush()

    def _refuse_model(
        self,
        message: ModelCallMessage,
        request_id: str,
        code: str,
        text: str,
        *,
        status: ModelCallStatus = ModelCallStatus.REJECTED,
        result: InferenceResult | None = None,
        latency_ms: int | None = None,
    ) -> None:
        self._note_model(message, request_id, status, code, result, latency_ms)
        kind = {
            ModelCallStatus.REJECTED: AdapterEventKind.MODEL_REQUEST_REJECTED,
            ModelCallStatus.UNCERTAIN: AdapterEventKind.MODEL_CALL_UNCERTAIN,
        }.get(status, AdapterEventKind.MODEL_CALL_FAILED)
        self._event(kind, call_id=message.call_id, code=code)
        self._send(
            ModelResultMessage(
                call_id=message.call_id, rejection=CallRejection(code=code, message=text[:500])
            )
        )
        self._count_rejection()

    def _model_refusal(
        self, message: ModelCallMessage, broker: InferenceBroker | None
    ) -> tuple[str, str] | None:
        """Why this may not reach a provider. Every limit is the host's, and is checked here."""
        out = self._outcome
        if message.call_id in self._seen_calls:
            return "duplicate_call_id", "this call_id was already used"
        self._seen_calls.add(message.call_id)
        if broker is None or Capability.MODEL.value not in self._context.capabilities:
            return "capability_not_granted", "no model for this run"
        if self._cancel_deadline is not None:
            return "cancelled", "run cancelled"
        if out.model_attempts >= broker.max_model_calls:
            return "model_call_budget_exhausted", "no model calls left"
        size = len(json.dumps(message.messages, separators=(",", ":")).encode())
        if size > broker.max_prompt_bytes:
            return "prompt_too_large", f"the conversation is over {broker.max_prompt_bytes} bytes"
        # Worst case for this call, so that a run cannot pass what was reserved for it.
        worst = out.tokens.total_tokens + size // 2 + broker.max_completion_tokens
        if worst > broker.max_total_tokens:
            return "token_budget_exhausted", "no tokens left"
        return None

    def _model(self, message: ModelCallMessage) -> None:
        broker = self._broker
        out = self._outcome
        request_id = f"{self._context.run_id}.m{len(out.model_requests) + 1}"
        refusal = self._model_refusal(message, broker)
        if refusal is not None or broker is None:
            code, text = refusal or ("capability_not_granted", "no model for this run")
            self._refuse_model(message, request_id, code, text)
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
            self._refuse_model(
                message, request_id, "invalid_messages", "the conversation is not valid"
            )
            return
        self._event(AdapterEventKind.MODEL_REQUEST_ACCEPTED, call_id=message.call_id)
        self._write_intent({"request_id": request_id, "status": "requested"})
        self._broker_call(message, request_id, broker, request)

    def _broker_call(
        self,
        message: ModelCallMessage,
        request_id: str,
        broker: InferenceBroker,
        request: InferenceRequest,
    ) -> None:
        """Exactly one provider request. Whatever comes of it, it is recorded before the reply."""
        out = self._outcome
        started = self._monotonic()
        answer = self._await_provider(broker, request)
        waited = int((self._monotonic() - started) * 1000)
        if answer is None or isinstance(answer, MoodyBluesError | ValidationError):
            out.tokens = out.tokens.model_copy(update={"complete": False})
        match answer:
            case None:
                self._model_abandoned(message, request_id, waited)
            case MoodyBluesError() if (
                answer.detail.category is ErrorCategory.PROVIDER_INVALID_RESPONSE
            ):
                self._model_malformed(message, request_id, None, waited)
            case MoodyBluesError():
                out.model_error = answer.detail
                ambiguous = answer.detail.category in _AMBIGUOUS_FAILURES
                self._refuse_model(
                    message,
                    request_id,
                    "provider_error",
                    answer.detail.category.value,
                    status=ModelCallStatus.UNCERTAIN if ambiguous else ModelCallStatus.FAILED,
                    latency_ms=waited,
                )
            case ValidationError():
                self._model_malformed(message, request_id, None, waited)
            case InferenceResult() if not answer.content and not answer.tool_calls:
                self._account(request, answer)
                self._model_malformed(message, request_id, answer, answer.latency_ms)
            case InferenceResult():
                self._account(request, answer)
                self._note_model(
                    message,
                    request_id,
                    ModelCallStatus.COMPLETED,
                    None,
                    answer,
                    answer.latency_ms,
                )
                self._send(
                    ModelResultMessage(
                        call_id=message.call_id,
                        content=answer.content,
                        tool_calls=answer.tool_calls,
                        finish_reason=answer.finish_reason,
                    )
                )
                self._event(AdapterEventKind.MODEL_CALL_BROKERED, call_id=message.call_id)

    def _model_malformed(
        self,
        message: ModelCallMessage,
        request_id: str,
        result: InferenceResult | None,
        latency_ms: int,
    ) -> None:
        self._outcome.model_error = ErrorDetail(
            category=ErrorCategory.PROVIDER_INVALID_RESPONSE,
            message="the provider's answer could not be used",
        )
        self._refuse_model(
            message,
            request_id,
            "provider_malformed",
            "the provider's answer could not be used",
            status=ModelCallStatus.MALFORMED,
            result=result,
            latency_ms=latency_ms,
        )

    def _model_abandoned(self, message: ModelCallMessage, request_id: str, waited: int) -> None:
        """No answer in time. It may still run and be billed, so nothing here calls it finished."""
        out = self._outcome
        out.model_error = ErrorDetail(
            category=ErrorCategory.PROVIDER_TIMEOUT,
            message=f"{request_id} was abandoned; it may have run and may be billed",
        )
        cancelled = self._cancel_deadline is not None
        if cancelled or self._monotonic() >= self._deadline:
            self._note_model(
                message, request_id, ModelCallStatus.UNCERTAIN, "model_call_abandoned", None, waited
            )
            self._event(
                AdapterEventKind.MODEL_CALL_UNCERTAIN,
                call_id=message.call_id,
                code="model_call_abandoned",
            )
            if cancelled:
                self._send(
                    ModelResultMessage(
                        call_id=message.call_id,
                        rejection=CallRejection(code="cancelled", message="run cancelled"),
                    )
                )
                return
            raise _Stopped(TerminationReason.WALL_TIMEOUT)
        self._refuse_model(
            message,
            request_id,
            "model_call_timeout",
            "no answer in time; the call may still be billed and is not repeated",
            status=ModelCallStatus.UNCERTAIN,
            latency_ms=waited,
        )

    def _await_provider(
        self, broker: InferenceBroker, request: InferenceRequest
    ) -> InferenceResult | MoodyBluesError | ValidationError | None:
        """The answer, or None if the host stopped waiting. A late answer is never delivered."""
        answers: list[InferenceResult | MoodyBluesError | ValidationError] = []
        finished = Event()

        def work() -> None:
            try:
                answers.append(broker.inference.complete(request))
            except (MoodyBluesError, ValidationError) as exc:
                answers.append(exc)
            finally:
                finished.set()

        Thread(target=work, name="mb-model-call", daemon=True).start()
        limit = min(self._monotonic() + broker.call_timeout_seconds, self._deadline)
        while not finished.wait(_POLL_SECONDS):
            self._check_cancel()
            if self._cancel_deadline is not None or self._monotonic() >= limit:
                if broker.abort is not None:
                    broker.abort()
                return None
        return answers[0] if answers else None

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

    def _make_claim(self, status: ClaimStatus, outcome: AgentOutcome, message: str) -> AnyClaim:
        """The record is read from this world's field only. The other one means nothing here."""
        field = self._world.descriptor.shape.claim_field
        ref = outcome.record_id if field == "record_id" else outcome.customer_id
        return self._world.claim(status, ref or None, message)

    def _final(self, message: FinalMessage) -> None:
        out = self._outcome
        out.final = message
        out.unknown_evidence_refs = sorted(set(message.evidence_refs) - self._gateway_refs)
        if message.completion == "finished" and message.outcome is not None:
            out.claim = self._make_claim(
                ClaimStatus(message.outcome.status), message.outcome, message.message
            )
        if self._cancel_deadline is not None:
            out.termination = TerminationReason.CANCELLED
        elif out.claim is not None:
            out.termination = TerminationReason.FINAL_CLAIM
        else:
            # "cancelled" with no cancel from the host is the agent giving up, too.
            out.termination = TerminationReason.AGENT_REPORTED_FAILURE
