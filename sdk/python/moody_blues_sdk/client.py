"""The controlled clients your agent acts through.

Nothing here retries. A write that timed out on your side may still have happened on the host, so
deciding what to do next is your agent's job, and that decision is what is being tested.
"""

from __future__ import annotations

import itertools
import queue
import threading
from dataclasses import dataclass
from typing import Any

from moody_blues_sdk.protocol import Channel, Message

DEFAULT_CALL_TIMEOUT_SECONDS = 30.0
_POLL_SECONDS = 0.05


class Cancelled(Exception):
    """The host asked this run to stop. Let it propagate: the runtime reports it for you."""


class ToolCallTimeout(Exception):
    """No reply arrived in time. The call may still have taken effect."""


class ModelUnavailable(Exception):
    """The host gave no answer: not granted, out of budget, or the provider failed.

    ``code`` says which. After ``model_call_timeout`` the call may still have run and been billed:
    the host does not repeat it, and whether to ask again is your agent's decision.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class HostGone(Exception):
    """The host closed the stream. There is nobody left to report to."""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What came back. ``ok`` is what the tool *said*, which is not proof of what happened."""

    ok: bool
    data: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    retryable: bool
    rejected: bool  # True: refused before reaching the tool. Nothing happened.
    evidence_ref: str | None  # Quote these in AgentResult.evidence.
    calls_remaining: int


@dataclass(frozen=True, slots=True)
class ModelReply:
    content: str | None
    tool_calls: tuple[dict[str, Any], ...]  # {"id", "name", "arguments_json"}
    finish_reason: str | None


class Exchange:
    """Pairs each reply with its request. One request is in flight at a time."""

    def __init__(self, channel: Channel, cancel: threading.Event) -> None:
        self._channel = channel
        self._cancel = cancel
        self._replies: queue.SimpleQueue[Message | None] = queue.SimpleQueue()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def deliver(self, message: Message | None) -> None:
        """Called from the reader thread."""
        if message is not None and message.get("type") == "cancel":
            self._cancel.set()
            return
        self._replies.put(message)

    def request(self, message: Message, timeout: float, kind: str) -> Message:
        with self._lock:
            call_id = f"{kind}-{next(self._ids)}"
            if self._cancel.is_set():
                raise Cancelled
            self._channel.send({**message, "call_id": call_id})
            return self._await(call_id, timeout)

    def _await(self, call_id: str, timeout: float) -> Message:
        waited = 0.0
        while waited < timeout:
            if self._cancel.is_set():
                raise Cancelled
            try:
                reply = self._replies.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                waited += _POLL_SECONDS
                continue
            if reply is None:
                raise HostGone
            if reply.get("call_id") == call_id:
                return reply
            # A reply to a request that already timed out. It is dropped, never matched.
        raise ToolCallTimeout(f"no reply to {call_id} within {timeout}s")


class ToolClient:
    """The only way your agent touches the world."""

    def __init__(self, exchange: Exchange) -> None:
        self._exchange = exchange

    def call(
        self,
        tool: str,
        /,
        *,
        timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
        **arguments: Any,
    ) -> ToolResult:
        """Call a tool once. Raises ``Cancelled`` or ``ToolCallTimeout``; never retries."""
        return self.call_with(tool, arguments, timeout=timeout)

    def call_with(
        self, tool: str, arguments: Any, *, timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS
    ) -> ToolResult:
        """``call``, for arguments a model wrote. Bad ones are the host's to refuse, not yours."""
        reply = self._exchange.request(
            {"type": "tool_call", "tool": tool, "arguments": arguments}, timeout, "tool"
        )
        rejection = reply.get("rejection")
        if rejection is not None:
            return ToolResult(
                ok=False,
                data=None,
                error_code=rejection["code"],
                error_message=rejection["message"],
                retryable=False,
                rejected=True,
                evidence_ref=None,
                calls_remaining=reply["calls_remaining"],
            )
        response = reply["response"]
        error: dict[str, Any] = response.get("error") or {}
        return ToolResult(
            ok=response["ok"],
            data=response.get("data"),
            error_code=error.get("code"),
            error_message=error.get("message"),
            retryable=bool(error.get("retryable", False)),
            rejected=False,
            evidence_ref=reply["evidence_ref"],
            calls_remaining=reply["calls_remaining"],
        )


class ModelClient:
    """Reaches a model through the host, which holds the key and the budget.

    The sandbox has no network, so this is the only route. Present only when the operator enabled
    it for this run.
    """

    def __init__(self, exchange: Exchange) -> None:
        self._exchange = exchange

    def complete(self, messages: list[dict[str, Any]], *, timeout: float = 60.0) -> ModelReply:
        reply = self._exchange.request(
            {"type": "model_call", "messages": messages}, timeout, "model"
        )
        rejection = reply.get("rejection")
        if rejection is not None:
            raise ModelUnavailable(rejection["code"], rejection["message"])
        return ModelReply(
            content=reply.get("content"),
            tool_calls=tuple(reply.get("tool_calls") or ()),
            finish_reason=reply.get("finish_reason"),
        )
