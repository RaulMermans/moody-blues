"""The Target Agent: one LLM-driven CRM Operations Agent, used for every configuration.

The model decides which tools to call and when to stop. Everything around the model is
deterministic code: tool validation, execution budgets, termination and claim parsing.

The agent is given exactly:

- a system policy (``policies.py``) and the mission built from the objective;
- the allowed tool definitions (``tooling.agent_tool_specs``);
- its own conversation history;
- tool responses delivered through the ``ToolPort``.

It never receives a store, a database path, fault configuration, the scenario description,
Oracle output or protected evidence. The loop is bounded by ``AgentBudget``.

Exactly-once execution: each ``InferenceResult`` is processed once, in order. Provider-level
retries (the SDK's bounded backoff) happen before a response exists, so they cannot replay a
tool call. A run that fails at the provider stops; it never re-sends earlier calls.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from threading import Event
from typing import Protocol

from pydantic import JsonValue, ValidationError

from moody_blues.agents.policies import CLAIM_REMINDER, AgentPolicy, mission_prompt
from moody_blues.agents.tooling import (
    FINAL_CLAIM_TOOL,
    agent_tool_specs,
    error_result,
    validate_call,
)
from moody_blues.contracts.agent import (
    AgentBudget,
    AgentStep,
    AgentTrajectory,
    ClaimOutcome,
    TerminationReason,
    TokenTotals,
    ToolCallDisposition,
    ToolCallRecord,
)
from moody_blues.contracts.common import ErrorCategory, ErrorDetail, MoodyBluesError
from moody_blues.contracts.inference import (
    AssistantToolCallMessage,
    ChatMessage,
    ConversationMessage,
    InferenceRequest,
    InferenceResult,
    ToolCall,
    ToolResultMessage,
)
from moody_blues.contracts.scenario import Objective
from moody_blues.contracts.world import FinalClaim, ToolResponse
from moody_blues.world.gateway import ToolPort


class InferencePort(Protocol):
    """What the agent needs from a model provider. ``VultrInferenceClient`` satisfies it."""

    def complete(self, request: InferenceRequest) -> InferenceResult: ...


def _estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


class _Run:
    """Mutable state of one agent run. Never shared between runs."""

    def __init__(self, budget: AgentBudget, policy: AgentPolicy, objective: Objective) -> None:
        self.budget = budget
        self.messages: list[ConversationMessage] = [
            ChatMessage(role="system", content=policy.system_prompt),
            ChatMessage(role="user", content=mission_prompt(objective)),
        ]
        self.steps: list[AgentStep] = []
        self.calls: list[ToolCallRecord] = []
        self.executed = 0
        self.claim: FinalClaim | None = None
        self.invalid_claims = 0
        self.reminders = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.usage_complete = True
        self.inference_ms = 0
        self.error: ErrorDetail | None = None

    def account(self, request: InferenceRequest, result: InferenceResult) -> None:
        self.inference_ms += result.latency_ms
        usage = result.usage
        if usage is not None and usage.total_tokens is not None:
            self.prompt_tokens += usage.prompt_tokens or 0
            self.completion_tokens += usage.completion_tokens or 0
            self.total_tokens += usage.total_tokens
            return
        # No provider-reported usage: estimate so the budget is still enforced, and say so.
        self.usage_complete = False
        prompt = _estimate_tokens(request.model_dump_json())
        completion = _estimate_tokens(result.model_dump_json(include={"content", "tool_calls"}))
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion


class TargetAgent:
    def __init__(
        self,
        *,
        policy: AgentPolicy,
        inference: InferencePort,
        budget: AgentBudget | None = None,
        model: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy
        self.budget = budget or AgentBudget()
        self.model = model
        self._inference = inference
        self._monotonic = monotonic
        self._tools = agent_tool_specs()

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self._tools]

    def run(
        self, port: ToolPort, objective: Objective, *, cancel: Event | None = None
    ) -> AgentTrajectory:
        started = self._monotonic()
        deadline = started + self.budget.max_wall_seconds
        state = _Run(self.budget, self.policy, objective)
        termination = TerminationReason.MAX_STEPS

        for index in range(1, self.budget.max_steps + 1):
            if cancel is not None and cancel.is_set():
                termination = TerminationReason.CANCELLED
                break
            if self._monotonic() >= deadline:
                termination = TerminationReason.WALL_TIMEOUT
                break
            if state.total_tokens >= self.budget.max_total_tokens:
                termination = TerminationReason.TOKEN_BUDGET
                break

            request = InferenceRequest(
                messages=state.messages,
                model=self.model,
                tools=self._tools,
                tool_choice="auto",
                max_tokens=self.budget.max_completion_tokens,
                temperature=self.budget.temperature,
            )
            try:
                result = self._inference.complete(request)
            except MoodyBluesError as exc:
                state.error = exc.detail
                # A failed request may still be billed and reports no usage, so the run's measured
                # tokens are a lower bound and the ledger must keep the full reservation.
                state.usage_complete = False
                termination = TerminationReason.PROVIDER_ERROR
                break
            state.account(request, result)

            try:
                turn = result.assistant_message()
            except ValidationError as exc:  # e.g. duplicate tool-call ids within one turn
                self._record_step(state, index, result)
                state.error = ErrorDetail(
                    category=ErrorCategory.PROVIDER_INVALID_RESPONSE,
                    message=f"unusable assistant turn: {exc.errors()[0]['msg']}"[:300],
                )
                termination = TerminationReason.INVALID_MODEL_RESPONSE
                break

            if not isinstance(turn, AssistantToolCallMessage):
                remind = state.reminders < self.budget.max_claim_reminders
                self._record_step(state, index, result, reminder=remind)
                if turn is not None:
                    state.messages.append(turn)
                if not remind:
                    termination = TerminationReason.NO_FINAL_CLAIM
                    break
                state.reminders += 1
                state.messages.append(ChatMessage(role="user", content=CLAIM_REMINDER))
                continue

            self._record_step(state, index, result)
            # The assistant turn is appended before any of its results (protocol order).
            state.messages.append(turn)
            cancelled = False
            for call in turn.tool_calls:
                if state.claim is not None:
                    record = self._not_executed(
                        index,
                        call,
                        ToolCallDisposition.SKIPPED_AFTER_FINAL_CLAIM,
                        "not executed: the final claim was already submitted in this turn",
                    )
                elif cancelled or (cancel is not None and cancel.is_set()):
                    cancelled = True
                    record = self._not_executed(
                        index, call, ToolCallDisposition.CANCELLED, "not executed: run cancelled"
                    )
                else:
                    record = self._handle(state, index, call, port)
                state.calls.append(record)
                state.messages.append(
                    ToolResultMessage(tool_call_id=call.id, content=record.result_content)
                )
            if state.claim is not None:
                termination = TerminationReason.FINAL_CLAIM
                break
            if cancelled:
                termination = TerminationReason.CANCELLED
                break

        if state.claim is not None:
            claim_outcome = ClaimOutcome.VALID
        elif state.invalid_claims:
            claim_outcome = ClaimOutcome.INVALID
        else:
            claim_outcome = ClaimOutcome.MISSING
        return AgentTrajectory(
            config=self.policy.config,
            policy_version=self.policy.version,
            policy_sha256=self.policy.sha256,
            budget=self.budget,
            tool_names=self.tool_names,
            messages=state.messages,
            steps=state.steps,
            tool_calls=state.calls,
            claim=state.claim,
            claim_outcome=claim_outcome,
            invalid_claim_attempts=state.invalid_claims,
            termination=termination,
            error=state.error,
            tokens=TokenTotals(
                prompt_tokens=state.prompt_tokens,
                completion_tokens=state.completion_tokens,
                total_tokens=state.total_tokens,
                complete=state.usage_complete,
            ),
            inference_latency_ms=state.inference_ms,
            wall_ms=int((self._monotonic() - started) * 1000),
        )

    # --- helpers ------------------------------------------------------------------------

    @staticmethod
    def _record_step(
        state: _Run, index: int, result: InferenceResult, *, reminder: bool = False
    ) -> None:
        state.steps.append(
            AgentStep(
                index=index,
                provider=result.provider,
                requested_model=result.requested_model,
                reported_model=result.reported_model,
                response_id=result.response_id,
                finish_reason=result.finish_reason,
                content=result.content,
                tool_call_ids=[c.id for c in result.tool_calls],
                usage=result.usage,
                latency_ms=result.latency_ms,
                claim_reminder_sent=reminder,
            )
        )

    @staticmethod
    def _not_executed(
        step: int, call: ToolCall, disposition: ToolCallDisposition, message: str
    ) -> ToolCallRecord:
        return ToolCallRecord(
            step=step,
            tool_call_id=call.id,
            name=call.name,
            arguments_json=call.arguments_json,
            disposition=disposition,
            result_content=error_result(disposition.value, message),
            error=message,
        )

    def _handle(self, state: _Run, step: int, call: ToolCall, port: ToolPort) -> ToolCallRecord:
        checked = validate_call(call)

        def record(
            disposition: ToolCallDisposition,
            result_content: str,
            *,
            validated: dict[str, JsonValue] | None = None,
            delivered: ToolResponse | None = None,
            error: str | None = None,
        ) -> ToolCallRecord:
            return ToolCallRecord(
                step=step,
                tool_call_id=call.id,
                name=call.name,
                arguments_json=call.arguments_json,
                disposition=disposition,
                validated_arguments=validated,
                gateway_call_id=delivered.call_id if delivered is not None else None,
                delivered=delivered,
                result_content=result_content,
                error=error,
            )

        if checked.disposition is ToolCallDisposition.FINAL_CLAIM_ACCEPTED:
            state.claim = checked.claim
            return record(
                checked.disposition, '{"ok":true,"accepted":true}', validated=checked.arguments
            )
        if checked.disposition is not None:
            if checked.disposition is ToolCallDisposition.FINAL_CLAIM_INVALID:
                state.invalid_claims += 1
            message = checked.error or checked.disposition.value
            return record(
                checked.disposition,
                error_result(checked.disposition.value, message),
                error=message,
            )
        if call.name == FINAL_CLAIM_TOOL:  # pragma: no cover - validate_call handles it
            raise AssertionError("final claim reached execution")
        if state.executed >= self.budget.max_tool_calls:
            message = (
                f"not executed: the tool-call budget ({self.budget.max_tool_calls}) is "
                "exhausted; call submit_final_claim now"
            )
            return record(
                ToolCallDisposition.TOOL_BUDGET_EXHAUSTED,
                error_result(ToolCallDisposition.TOOL_BUDGET_EXHAUSTED.value, message),
                error=message,
            )
        if checked.arguments is None:  # pragma: no cover - valid calls carry arguments
            raise AssertionError("validated call without arguments")
        state.executed += 1
        delivered = port.call(call.name, checked.arguments)
        return record(
            ToolCallDisposition.EXECUTED,
            delivered.model_dump_json(exclude_none=True),
            validated=checked.arguments,
            delivered=delivered,
        )
