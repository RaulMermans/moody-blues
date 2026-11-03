"""OFFLINE tests for the multi-turn tool-calling protocol (C3-A).

Provider responses are in-process FIXTURES served through ``httpx2.MockTransport``; the real
OpenAI SDK serialization path runs unmodified. They show that our contracts and the adapter
produce and consume the OpenAI-compatible message shapes. They are NOT evidence that Vultr
accepts these shapes; that is checked live by ``make agent-run`` (see docs/testing).
"""

from __future__ import annotations

from typing import Any

import httpx2
import pytest
from pydantic import TypeAdapter, ValidationError

from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import (
    AssistantToolCallMessage,
    ChatMessage,
    ConversationMessage,
    InferenceRequest,
    ToolCall,
    ToolResultMessage,
)
from moody_blues.inference.vultr import InferenceError, to_wire_message
from tests.unit.test_vultr_adapter import fixture_completion, make_client

CREATE = ToolCall(
    id="functions.create_customer:0",
    name="create_customer",
    arguments_json='{"name": "Ada Lovelace", "email": "ada@analytical.example"}',
)
SEARCH = ToolCall(
    id="functions.search_customers:1",
    name="search_customers",
    arguments_json='{"email": "ada@analytical.example"}',
)


def conversation() -> list[ConversationMessage]:
    return [
        ChatMessage(role="system", content="You operate a CRM."),
        ChatMessage(role="user", content="Create Ada."),
        AssistantToolCallMessage(content="Creating and checking.", tool_calls=[CREATE, SEARCH]),
        ToolResultMessage(tool_call_id=SEARCH.id, content='{"ok": true, "count": 0}'),
        ToolResultMessage(tool_call_id=CREATE.id, content='{"ok": false, "error": "timeout"}'),
        ChatMessage(role="assistant", content="The create timed out."),
        ChatMessage(role="user", content="Please verify."),
    ]


def test_full_conversation_validates_and_round_trips_through_json() -> None:
    request = InferenceRequest(messages=conversation())
    restored = InferenceRequest.model_validate_json(request.model_dump_json())
    assert restored == request
    assert [type(m) for m in restored.messages] == [type(m) for m in conversation()]
    calls = restored.messages[2]
    assert isinstance(calls, AssistantToolCallMessage)
    assert [c.id for c in calls.tool_calls] == [CREATE.id, SEARCH.id]
    assert calls.tool_calls[0].arguments_json == CREATE.arguments_json  # byte-for-byte
    results = [m for m in restored.messages if isinstance(m, ToolResultMessage)]
    assert [r.tool_call_id for r in results] == [SEARCH.id, CREATE.id]


def test_messages_parse_from_plain_dicts_by_role_and_shape() -> None:
    adapter: TypeAdapter[list[ConversationMessage]] = TypeAdapter(list[ConversationMessage])
    parsed = adapter.validate_python(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": [CREATE.model_dump()]},
            {"role": "tool", "tool_call_id": CREATE.id, "content": "{}"},
            {"role": "assistant", "content": "done"},
        ]
    )
    assert [type(m) for m in parsed] == [
        ChatMessage,
        AssistantToolCallMessage,
        ToolResultMessage,
        ChatMessage,
    ]


def test_adapter_sends_openai_compatible_tool_message_shapes() -> None:
    client, rec = make_client(lambda _: httpx2.Response(200, json=fixture_completion(content="ok")))
    client.complete(InferenceRequest(messages=conversation()))
    sent = rec.body()["messages"]
    assert sent[2] == {
        "role": "assistant",
        "content": "Creating and checking.",
        "tool_calls": [
            {
                "id": CREATE.id,
                "type": "function",
                "function": {"name": "create_customer", "arguments": CREATE.arguments_json},
            },
            {
                "id": SEARCH.id,
                "type": "function",
                "function": {"name": "search_customers", "arguments": SEARCH.arguments_json},
            },
        ],
    }
    assert sent[3] == {
        "role": "tool",
        "tool_call_id": SEARCH.id,
        "content": '{"ok": true, "count": 0}',
    }
    assert sent[4]["role"] == "tool"
    assert sent[4]["tool_call_id"] == CREATE.id
    # Tool results are never flattened into user messages.
    assert [m["role"] for m in sent] == [
        "system",
        "user",
        "assistant",
        "tool",
        "tool",
        "assistant",
        "user",
    ]


def _wire(message: ConversationMessage) -> dict[str, Any]:
    return dict(to_wire_message(message))


def test_assistant_tool_call_without_text_is_sent_with_null_content() -> None:
    assert _wire(AssistantToolCallMessage(tool_calls=[CREATE]))["content"] is None


def test_malformed_arguments_are_preserved_verbatim_on_the_wire() -> None:
    bad = ToolCall(id="c1", name="create_customer", arguments_json='{"name": "Ada", ')
    wire = _wire(AssistantToolCallMessage(tool_calls=[bad]))
    assert wire["tool_calls"][0]["function"]["arguments"] == '{"name": "Ada", '


def _parallel_payload(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return fixture_completion(tool_calls=calls)


def test_multiple_tool_calls_in_one_response_keep_order_ids_and_raw_args() -> None:
    raw = [
        {
            "id": "call_a",
            "type": "function",
            "function": {"name": "search_customers", "arguments": '{"email": "a@b.example"}'},
        },
        {
            "id": "call_b",
            "type": "function",
            "function": {"name": "get_customer", "arguments": "not json"},
        },
    ]
    client, _ = make_client(lambda _: httpx2.Response(200, json=_parallel_payload(raw)))
    result = client.complete(InferenceRequest(messages=[ChatMessage(role="user", content="x")]))
    assert [(c.id, c.name, c.arguments_json) for c in result.tool_calls] == [
        ("call_a", "search_customers", '{"email": "a@b.example"}'),
        ("call_b", "get_customer", "not json"),
    ]
    turn = result.assistant_message()
    assert isinstance(turn, AssistantToolCallMessage)
    assert turn.tool_calls == result.tool_calls


def test_tool_call_without_id_is_an_invalid_provider_response() -> None:
    raw = [{"id": "", "type": "function", "function": {"name": "x", "arguments": "{}"}}]
    client, _ = make_client(lambda _: httpx2.Response(200, json=_parallel_payload(raw)))
    with pytest.raises(InferenceError) as info:
        client.complete(InferenceRequest(messages=[ChatMessage(role="user", content="x")]))
    assert info.value.detail.category is ErrorCategory.PROVIDER_INVALID_RESPONSE


def test_assistant_message_for_text_and_empty_results() -> None:
    client, _ = make_client(lambda _: httpx2.Response(200, json=fixture_completion(content="hi")))
    result = client.complete(InferenceRequest(messages=[ChatMessage(role="user", content="x")]))
    assert result.assistant_message() == ChatMessage(role="assistant", content="hi")
    empty = result.model_copy(update={"content": None})
    assert empty.assistant_message() is None


# --- protocol violations are explicit -----------------------------------------------------------

USER = ChatMessage(role="user", content="u")


@pytest.mark.parametrize(
    ("messages", "match"),
    [
        ([USER, ToolResultMessage(tool_call_id="nope", content="{}")], "does not answer"),
        (
            [USER, AssistantToolCallMessage(tool_calls=[CREATE]), USER],
            "were not answered before the next message",
        ),
        ([USER, AssistantToolCallMessage(tool_calls=[CREATE])], "ends with unanswered"),
        (
            [
                USER,
                AssistantToolCallMessage(tool_calls=[CREATE]),
                ToolResultMessage(tool_call_id=CREATE.id, content="{}"),
                ToolResultMessage(tool_call_id=CREATE.id, content="{}"),
            ],
            "does not answer",
        ),
        (
            [
                USER,
                AssistantToolCallMessage(tool_calls=[CREATE, SEARCH]),
                ToolResultMessage(tool_call_id=CREATE.id, content="{}"),
            ],
            "ends with unanswered",
        ),
    ],
)
def test_tool_protocol_violations_are_rejected(
    messages: list[ConversationMessage], match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        InferenceRequest(messages=messages)


def test_ids_may_repeat_across_separate_assistant_turns() -> None:
    reused = ToolCall(id="call_0", name="get_customer", arguments_json="{}")
    InferenceRequest(
        messages=[
            USER,
            AssistantToolCallMessage(tool_calls=[reused]),
            ToolResultMessage(tool_call_id="call_0", content="{}"),
            AssistantToolCallMessage(tool_calls=[reused]),
            ToolResultMessage(tool_call_id="call_0", content="{}"),
        ]
    )


def test_duplicate_ids_within_one_assistant_turn_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        AssistantToolCallMessage(tool_calls=[CREATE, CREATE])


def test_assistant_tool_call_message_needs_at_least_one_call() -> None:
    with pytest.raises(ValidationError):
        AssistantToolCallMessage(tool_calls=[])


def test_tool_call_id_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        ToolCall(id="", name="x", arguments_json="{}")
