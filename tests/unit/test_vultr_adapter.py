"""OFFLINE contract tests for the Vultr adapter.

Responses come from in-process FIXTURES via ``httpx2.MockTransport``; the real OpenAI SDK
code path (serialization, retries, error mapping) runs unmodified. These prove adapter
behavior against the OpenAI-compatible wire format — they are NOT evidence that Vultr
itself works. Live verification: ``make vultr-smoke``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from moody_blues.config import VULTR_INFERENCE_BASE_URL
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import ChatMessage, InferenceRequest
from moody_blues.inference import smoke
from moody_blues.inference.vultr import InferenceError, VultrInferenceClient
from tests.conftest import make_settings

Handler = Callable[[httpx2.Request], httpx2.Response]


def fixture_completion(**message: Any) -> dict[str, Any]:
    return {
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "created": 0,
        "model": "fixture-served-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                "message": {"role": "assistant", "content": None} | message,
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    def body(self, i: int = -1) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.requests[i].content)
        return data


def make_client(handler: Handler, *, max_retries: int = 0) -> tuple[VultrInferenceClient, Recorder]:
    rec = Recorder(handler)
    client = VultrInferenceClient(
        api_key="sk-fixture",
        model="kimi-k2-instruct",
        base_url=VULTR_INFERENCE_BASE_URL,
        timeout_seconds=5,
        max_retries=max_retries,
        http_client=httpx2.Client(transport=httpx2.MockTransport(rec)),
    )
    return client, rec


PING = InferenceRequest(messages=[ChatMessage(role="user", content="ping")])


def test_construction_makes_no_network_calls() -> None:
    _, rec = make_client(lambda _: httpx2.Response(500))
    assert rec.requests == []


def test_basic_completion_maps_metadata() -> None:
    client, rec = make_client(
        lambda _: httpx2.Response(200, json=fixture_completion(content="pong"))
    )
    result = client.complete(PING)

    req = rec.requests[0]
    assert str(req.url) == f"{VULTR_INFERENCE_BASE_URL}/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-fixture"
    body = rec.body()
    assert body["model"] == "kimi-k2-instruct"
    assert body["messages"] == [{"role": "user", "content": "ping"}]
    assert "tools" not in body

    assert result.provider == "vultr"
    assert result.content == "pong"
    assert result.requested_model == "kimi-k2-instruct"
    assert result.reported_model == "fixture-served-model"
    assert result.response_id == "chatcmpl-fixture"
    assert result.usage is not None
    assert result.usage.total_tokens == 14
    assert result.finish_reason == "stop"


def test_missing_usage_is_none_not_zero() -> None:
    payload = fixture_completion(content="hi")
    del payload["usage"]
    client, _ = make_client(lambda _: httpx2.Response(200, json=payload))
    assert client.complete(PING).usage is None


def _tool_call_payload(arguments: str) -> dict[str, Any]:
    return fixture_completion(
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "add_numbers", "arguments": arguments},
            }
        ]
    )


def test_tool_calling_request_and_parsing() -> None:
    client, rec = make_client(
        lambda _: httpx2.Response(200, json=_tool_call_payload('{"a": 17, "b": 25}'))
    )
    report = smoke.tool_calling(client)

    body = rec.body()
    assert body["tool_choice"] == "required"
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["function"]["name"] == "add_numbers"
    assert body["tools"][0]["function"]["parameters"]["required"] == ["a", "b"]
    assert report["status"] == smoke.SmokeStatus.PASS
    assert report["validated_arguments"] == {"a": 17, "b": 25}
    assert report["tool_output"] == 42


@pytest.mark.parametrize(
    "arguments", ['{"a": "seventeen", "b": 25}', '{"a": 17}', "not json", '{"a": 1, "b": 2}']
)
def test_tool_calling_rejects_bad_arguments(arguments: str) -> None:
    client, _ = make_client(lambda _: httpx2.Response(200, json=_tool_call_payload(arguments)))
    assert smoke.tool_calling(client)["status"] == smoke.SmokeStatus.FAIL


def test_tool_calling_fails_without_tool_call() -> None:
    client, _ = make_client(lambda _: httpx2.Response(200, json=fixture_completion(content="42")))
    assert smoke.tool_calling(client)["status"] == smoke.SmokeStatus.FAIL


@pytest.mark.parametrize(
    ("status", "category", "retryable"),
    [
        (400, ErrorCategory.PROVIDER_BAD_REQUEST, False),
        (401, ErrorCategory.PROVIDER_AUTH, False),
        (403, ErrorCategory.PROVIDER_AUTH, False),
        (404, ErrorCategory.PROVIDER_MODEL_NOT_FOUND, False),
        (422, ErrorCategory.PROVIDER_BAD_REQUEST, False),
        (429, ErrorCategory.PROVIDER_RATE_LIMITED, True),
        (500, ErrorCategory.PROVIDER_SERVER_ERROR, True),
        (503, ErrorCategory.PROVIDER_SERVER_ERROR, True),
    ],
)
def test_http_error_classification(status: int, category: ErrorCategory, retryable: bool) -> None:
    client, _ = make_client(
        lambda _: httpx2.Response(status, json={"error": {"message": "fixture"}})
    )
    with pytest.raises(InferenceError) as info:
        client.complete(PING)
    assert info.value.detail.category is category
    assert info.value.detail.retryable is retryable
    assert "sk-fixture" not in info.value.detail.message


def test_connection_error_classification() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("fixture: refused", request=request)

    client, _ = make_client(fail)
    with pytest.raises(InferenceError) as info:
        client.complete(PING)
    assert info.value.detail.category is ErrorCategory.PROVIDER_CONNECTION


def test_timeout_classification() -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("fixture: timed out", request=request)

    client, _ = make_client(slow)
    with pytest.raises(InferenceError) as info:
        client.complete(PING)
    assert info.value.detail.category is ErrorCategory.PROVIDER_TIMEOUT


def test_retries_are_bounded() -> None:
    client, rec = make_client(lambda _: httpx2.Response(503, json={}), max_retries=2)
    with pytest.raises(InferenceError):
        client.complete(PING)
    assert len(rec.requests) == 3  # 1 attempt + 2 retries, then give up


def test_auth_errors_are_not_retried() -> None:
    client, rec = make_client(lambda _: httpx2.Response(401, json={}), max_retries=2)
    with pytest.raises(InferenceError):
        client.complete(PING)
    assert len(rec.requests) == 1


def test_empty_choices_is_invalid_response() -> None:
    payload: dict[str, Any] = {**fixture_completion(content="x"), "choices": []}
    client, _ = make_client(lambda _: httpx2.Response(200, json=payload))
    with pytest.raises(InferenceError) as info:
        client.complete(PING)
    assert info.value.detail.category is ErrorCategory.PROVIDER_INVALID_RESPONSE


def test_list_models() -> None:
    client, rec = make_client(
        lambda _: httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "b-model", "object": "model", "created": 0, "owned_by": "x"},
                    {"id": "a-model", "object": "model", "created": 0, "owned_by": "x"},
                ],
            },
        )
    )
    assert client.list_models() == ["a-model", "b-model"]
    assert str(rec.requests[0].url) == f"{VULTR_INFERENCE_BASE_URL}/models"


def test_from_settings_requires_key() -> None:
    with pytest.raises(InferenceError) as info:
        VultrInferenceClient.from_settings(make_settings())
    assert info.value.detail.category is ErrorCategory.PROVIDER_NOT_CONFIGURED


def test_smoke_reports_blocked_without_credentials() -> None:
    code, report = smoke.run(list(smoke.CHECKS), make_settings())
    assert code == 2
    assert {c["status"] for c in report["checks"].values()} == {
        smoke.SmokeStatus.BLOCKED_BY_CREDENTIALS
    }
