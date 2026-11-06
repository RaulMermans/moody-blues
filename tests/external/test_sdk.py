"""The SDK on its own, against a fake host. No retries, and late replies are never matched."""

from __future__ import annotations

import threading
from typing import Any, cast

import pytest

from moody_blues_sdk import AgentResult, Cancelled, ToolCallTimeout, ToolClient
from moody_blues_sdk.client import Exchange, HostGone
from moody_blues_sdk.protocol import MAX_MESSAGE_BYTES, Channel


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


def _reply(call_id: str, ok: bool = True) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "call_id": call_id,
        "evidence_ref": "call_0001",
        "response": {"ok": ok, "data": {"x": 1}},
        "rejection": None,
        "calls_remaining": 1,
    }


def _client() -> tuple[FakeChannel, Exchange, ToolClient, threading.Event]:
    channel = FakeChannel()
    cancel = threading.Event()
    exchange = Exchange(cast(Channel, channel), cancel)
    return channel, exchange, ToolClient(exchange), cancel


def test_a_timed_out_call_is_not_retried() -> None:
    channel, _, tools, _ = _client()
    with pytest.raises(ToolCallTimeout):
        tools.call("create_customer", timeout=0.1, name="x")
    assert len(channel.sent) == 1


def test_a_late_reply_is_never_taken_for_the_next_call() -> None:
    channel, exchange, tools, _ = _client()
    with pytest.raises(ToolCallTimeout):
        tools.call("create_customer", timeout=0.1, name="x")
    exchange.deliver(_reply("tool-1", ok=False))  # late: belongs to the call that timed out
    threading.Timer(0.1, lambda: exchange.deliver(_reply("tool-2"))).start()
    result = tools.call("search_customers", timeout=2)
    assert result.ok
    assert [m["call_id"] for m in channel.sent] == ["tool-1", "tool-2"]


def test_every_call_has_its_own_id() -> None:
    channel, exchange, tools, _ = _client()
    for n in (1, 2, 3):
        threading.Timer(0.02, exchange.deliver, args=(_reply(f"tool-{n}"),)).start()
        tools.call("search_customers", timeout=2)
    assert len({m["call_id"] for m in channel.sent}) == 3


def test_cancellation_interrupts_a_waiting_call() -> None:
    _, exchange, tools, cancel = _client()
    threading.Timer(0.05, lambda: exchange.deliver({"type": "cancel"})).start()
    with pytest.raises(Cancelled):
        tools.call("search_customers", timeout=5)
    assert cancel.is_set()


def test_no_call_is_sent_after_cancellation() -> None:
    channel, exchange, tools, _ = _client()
    exchange.deliver({"type": "cancel"})
    with pytest.raises(Cancelled):
        tools.call("create_customer", name="x")
    assert channel.sent == []


def test_a_closed_host_is_not_mistaken_for_a_timeout() -> None:
    _, exchange, tools, _ = _client()
    threading.Timer(0.05, lambda: exchange.deliver(None)).start()
    with pytest.raises(HostGone):
        tools.call("search_customers", timeout=5)


def test_a_rejection_is_not_an_exception_and_says_nothing_happened() -> None:
    _, exchange, tools, _ = _client()
    rejected = {
        "call_id": "tool-1",
        "rejection": {"code": "unknown_tool", "message": "no"},
        "calls_remaining": 3,
    }
    threading.Timer(0.02, lambda: exchange.deliver(rejected)).start()
    result = tools.call("nope", timeout=2)
    assert result.rejected
    assert not result.ok
    assert result.evidence_ref is None


def test_a_message_over_the_limit_is_refused_before_sending() -> None:
    import io
    import os

    read_end, write_end = os.pipe()
    channel = Channel(io.BytesIO(), write_end)
    with pytest.raises(ValueError, match="limit"):
        channel.send({"type": "final", "message": "x" * MAX_MESSAGE_BYTES})
    os.close(read_end)
    os.close(write_end)


def test_a_long_message_is_cut_to_the_contract() -> None:
    assert len(AgentResult.completed(message="x" * 5_000).to_message()["message"]) == 2_000
