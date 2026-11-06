"""The Ollama adapter against a labeled double of its HTTP API. No model runs here.

``OllamaDouble`` is a TEST DOUBLE that answers in the shape a real server was observed to use. It
shows what the adapter does with an answer. It says nothing about what any model would say.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event, Thread
from typing import Any

import httpx2
import pytest

from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.inference import (
    AssistantToolCallMessage,
    ChatMessage,
    InferenceRequest,
    LocalInferencePolicy,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
)
from moody_blues.inference.ollama import (
    LocalEndpointError,
    OllamaInferenceClient,
    to_ollama_messages,
    validate_local_endpoint,
)

MODEL = "fixture-local:1b"
DIGEST = "d" * 64
POLICY = LocalInferencePolicy(
    max_model_calls_per_run=4,
    max_total_tokens_per_run=4_000,
    max_completion_tokens=64,
    max_prompt_bytes=4_000,
    call_timeout_seconds=5.0,
    run_timeout_seconds=30.0,
    max_concurrent_generations=1,
    context_tokens=2_048,
    max_experiments=1,
    max_investigator_calls=2,
    max_investigation_seconds=60.0,
)
Q = InferenceRequest(messages=[ChatMessage(role="user", content="hi")], max_tokens=32)


def frames(*items: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(i).encode() + b"\n" for i in items)


def done(**extra: Any) -> dict[str, Any]:
    return {
        "model": MODEL,
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "stop",
        "total_duration": 9_000_000,
        "load_duration": 1_000_000,
        "prompt_eval_count": 7,
        "prompt_eval_duration": 2_000_000,
        "eval_count": 3,
        "eval_duration": 5_000_000,
    } | extra


def text(value: str) -> dict[str, Any]:
    return {"model": MODEL, "message": {"role": "assistant", "content": value}, "done": False}


def call(name: str = "create_customer", **extra: Any) -> dict[str, Any]:
    raw = {"id": "call_x", "function": {"name": name, "arguments": {"a": 1}}} | extra
    return {
        "model": MODEL,
        "message": {"role": "assistant", "content": "", "tool_calls": [raw]},
        "done": False,
    }


class OllamaDouble:
    """TEST DOUBLE. Records what it was asked, and answers with what the test gave it."""

    def __init__(self, handler: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.handler = handler
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def sent(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


def client(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    policy: LocalInferencePolicy = POLICY,
    think: bool = False,
) -> tuple[OllamaInferenceClient, OllamaDouble]:
    double = OllamaDouble(handler)
    return (
        OllamaInferenceClient(
            base_url="http://127.0.0.1:11434",
            model=MODEL,
            allowlist=(MODEL,),
            policy=policy,
            think=think,
            transport=httpx2.MockTransport(double),
        ),
        double,
    )


def answering(*items: dict[str, Any]) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda _: httpx2.Response(200, content=frames(*items))


def fails(category: ErrorCategory, action: Callable[[], object]) -> None:
    with pytest.raises(MoodyBluesError) as caught:
        action()
    assert caught.value.detail.category is category


# --- which address, which model -----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:11434", "http://127.0.0.1:11434/", "http://127.0.0.1", "http://[::1]:11434"],
)
def test_loopback_addresses_are_accepted(url: str) -> None:
    assert validate_local_endpoint(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434",
        "http://localhost:11434",  # a name can resolve anywhere
        "http://0.0.0.0:11434",
        "http://192.168.1.5:11434",
        "http://169.254.169.254/latest/meta-data",
        "https://api.vultrinference.com/v1",
        "http://127.0.0.1@evil.example:11434",
        "http://127.0.0.1:11434@evil.example",
        "http://user:pw@127.0.0.1:11434",
        "http://127.0.0.1.evil.example:11434",
        "http://127.0.0.1:11434/v1",
        "http://127.0.0.1:11434?x=1",
        "http://127.0.0.1:11434#x",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:0",
        "file:///etc/passwd",
        "http://127.0.0.1:11434\n.evil.example",
        "",
    ],
)
def test_anything_else_is_refused_before_contact(url: str) -> None:
    with pytest.raises(LocalEndpointError):
        validate_local_endpoint(url)
    with pytest.raises(LocalEndpointError):
        OllamaInferenceClient(
            base_url=url, model=MODEL, allowlist=(MODEL,), policy=POLICY, think=False
        )


def test_a_model_off_the_allowlist_is_refused_at_construction() -> None:
    fails(
        ErrorCategory.PROVIDER_MODEL_NOT_FOUND,
        lambda: OllamaInferenceClient(
            base_url="http://127.0.0.1:11434",
            model="other:7b",
            allowlist=(MODEL,),
            policy=POLICY,
            think=False,
        ),
    )


def test_a_request_cannot_substitute_a_model() -> None:
    adapter, double = client(answering(text("x"), done()))
    other = Q.model_copy(update={"model": "other:7b"})
    fails(ErrorCategory.PROVIDER_MODEL_NOT_FOUND, lambda: adapter.complete(other))
    assert double.requests == []


def test_a_redirect_is_never_followed() -> None:
    adapter, double = client(
        lambda _: httpx2.Response(302, headers={"location": "http://evil.example/api/chat"})
    )
    fails(ErrorCategory.PROVIDER_BAD_REQUEST, lambda: adapter.complete(Q))
    assert len(double.requests) == 1


def test_proxy_settings_in_the_environment_are_ignored() -> None:
    adapter, _ = client(answering(done()))
    assert adapter._client.trust_env is False  # pyright: ignore[reportPrivateUsage]


# --- what is sent -------------------------------------------------------------------------


def test_the_request_sets_context_output_and_thinking_explicitly() -> None:
    adapter, double = client(answering(text("x"), done()), think=True)
    adapter.complete(Q)
    assert double.requests[0].url.path == "/api/chat"
    sent = double.sent
    assert sent["model"] == MODEL
    assert sent["stream"] is True
    assert sent["think"] is True
    assert sent["options"] == {"num_ctx": 2_048, "num_predict": 32, "temperature": 0.0}


def test_output_is_capped_by_the_policy_whatever_a_request_asks() -> None:
    adapter, double = client(answering(text("x"), done()))
    adapter.complete(Q.model_copy(update={"max_tokens": 8_000}))
    assert double.sent["options"]["num_predict"] == POLICY.max_completion_tokens


def test_tools_and_tool_results_translate_to_the_native_shape() -> None:
    call_ = ToolCall(id="c1", name="create_customer", arguments_json='{"name":"A"}')
    wire = to_ollama_messages(
        [
            ChatMessage(role="system", content="s"),
            AssistantToolCallMessage(content=None, tool_calls=[call_]),
            ToolResultMessage(tool_call_id="c1", content="{}"),
        ]
    )
    assert wire[1]["tool_calls"][0]["function"] == {
        "name": "create_customer",
        "arguments": {"name": "A"},
    }
    assert wire[2] == {
        "role": "tool",
        "tool_name": "create_customer",
        "tool_call_id": "c1",
        "content": "{}",
    }


@pytest.mark.parametrize("arguments", ["{not json", "[1]", '"x"'])
def test_history_with_bad_arguments_is_refused_and_not_repaired(arguments: str) -> None:
    adapter, double = client(answering(done()))
    request = InferenceRequest(
        messages=[
            ChatMessage(role="user", content="u"),
            AssistantToolCallMessage(
                tool_calls=[ToolCall(id="c1", name="t", arguments_json=arguments)]
            ),
            ToolResultMessage(tool_call_id="c1", content="{}"),
        ]
    )
    fails(ErrorCategory.PROVIDER_BAD_REQUEST, lambda: adapter.complete(request))
    assert double.requests == []


def test_tool_choice_none_offers_no_tools() -> None:
    spec = ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})
    adapter, double = client(answering(text("x"), done()))
    adapter.complete(Q.model_copy(update={"tools": [spec], "tool_choice": "none"}))
    assert "tools" not in double.sent
    adapter.complete(Q.model_copy(update={"tools": [spec], "tool_choice": "required"}))
    assert double.sent["tools"][0]["function"]["name"] == "t"


def test_an_oversized_prompt_never_reaches_the_server() -> None:
    adapter, double = client(answering(done()))
    big = InferenceRequest(messages=[ChatMessage(role="user", content="x" * 5_000)])
    fails(ErrorCategory.PROVIDER_BAD_REQUEST, lambda: adapter.complete(big))
    assert double.requests == []


def test_a_prompt_that_would_not_fit_the_context_is_refused_not_truncated() -> None:
    policy = POLICY.model_copy(update={"context_tokens": 600, "max_prompt_bytes": 40_000})
    adapter, double = client(answering(done()), policy=policy)
    big = InferenceRequest(messages=[ChatMessage(role="user", content="x" * 2_000)], max_tokens=64)
    fails(ErrorCategory.PROVIDER_BAD_REQUEST, lambda: adapter.complete(big))
    assert double.requests == []


# --- what comes back ----------------------------------------------------------------------


def test_text_usage_timings_and_identity_are_taken_from_the_answer() -> None:
    adapter, _ = client(answering(text("he"), text("llo"), done()))
    result = adapter.complete(Q)
    assert result.provider == "ollama"
    assert result.requested_model == MODEL
    assert result.reported_model == MODEL
    assert result.content == "hello"
    assert result.finish_reason == "stop"
    assert result.usage is not None
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (7, 3)
    assert result.timings is not None
    assert (result.timings.load_ms, result.timings.generation_ms) == (1, 5)
    assert result.response_id is not None


def test_each_call_gets_its_own_correlation_id() -> None:
    adapter, _ = client(answering(text("x"), done()))
    assert adapter.complete(Q).response_id != adapter.complete(Q).response_id


def test_tool_calls_keep_the_providers_id_and_become_json_text() -> None:
    adapter, _ = client(answering(call(), done()))
    result = adapter.complete(Q)
    assert [c.id for c in result.tool_calls] == ["call_x"]
    assert json.loads(result.tool_calls[0].arguments_json) == {"a": 1}
    assert result.finish_reason == "tool_calls"


def test_a_tool_call_without_an_id_is_given_one_that_links_results() -> None:
    raw = call()
    del raw["message"]["tool_calls"][0]["id"]
    adapter, _ = client(answering(raw, done()))
    result = adapter.complete(Q)
    assert result.tool_calls[0].id == f"{result.response_id}_t1"


def test_tool_call_arguments_sent_as_text_are_kept_verbatim() -> None:
    raw = call(function={"name": "t", "arguments": "{broken"})
    adapter, _ = client(answering(raw, done()))
    assert adapter.complete(Q).tool_calls[0].arguments_json == "{broken"


def test_a_cut_off_tool_call_still_reads_as_cut_off() -> None:
    adapter, _ = client(answering(call(), done(done_reason="length")))
    assert adapter.complete(Q).finish_reason == "length"


def test_hidden_reasoning_is_measured_and_never_passed_on() -> None:
    thinking = {
        "model": MODEL,
        "message": {"role": "assistant", "content": "", "thinking": "secret plan"},
        "done": False,
    }
    adapter, _ = client(answering(thinking, text("ok"), done()), think=True)
    result = adapter.complete(Q)
    assert result.content == "ok"
    assert "secret" not in result.model_dump_json()
    assert result.timings is not None
    assert result.timings.thinking_chars == len("secret plan")


def test_missing_usage_is_unknown_and_never_zero() -> None:
    final = done()
    del final["eval_count"]
    adapter, _ = client(answering(text("x"), final))
    assert adapter.complete(Q).usage is None


@pytest.mark.parametrize(
    ("body", "category"),
    [
        (frames(text("x")), ErrorCategory.PROVIDER_INVALID_RESPONSE),  # no final frame
        (b"", ErrorCategory.PROVIDER_INVALID_RESPONSE),
        (b"not json\n", ErrorCategory.PROVIDER_INVALID_RESPONSE),
        (b"[1,2]\n", ErrorCategory.PROVIDER_INVALID_RESPONSE),
        (frames(call(function={"arguments": {}}), done()), ErrorCategory.PROVIDER_INVALID_RESPONSE),
        (frames(text("x"), {"error": "boom"}), ErrorCategory.PROVIDER_SERVER_ERROR),
    ],
)
def test_a_malformed_answer_is_refused_whole(body: bytes, category: ErrorCategory) -> None:
    adapter, double = client(lambda _: httpx2.Response(200, content=body))
    fails(category, lambda: adapter.complete(Q))
    assert len(double.requests) == 1


def test_an_answer_past_the_output_limit_is_refused() -> None:
    flood = [text("x") for _ in range(200)]
    adapter, _ = client(answering(*flood, done()))
    fails(ErrorCategory.PROVIDER_INVALID_RESPONSE, lambda: adapter.complete(Q))


def test_an_answer_past_the_size_limit_is_refused() -> None:
    adapter, _ = client(answering(text("x" * 5_000_000), done()))
    fails(ErrorCategory.PROVIDER_INVALID_RESPONSE, lambda: adapter.complete(Q))


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (400, ErrorCategory.PROVIDER_BAD_REQUEST),
        (404, ErrorCategory.PROVIDER_MODEL_NOT_FOUND),
        (429, ErrorCategory.PROVIDER_RATE_LIMITED),
        (500, ErrorCategory.PROVIDER_SERVER_ERROR),
        (503, ErrorCategory.PROVIDER_SERVER_ERROR),
    ],
)
def test_status_codes_map_and_nothing_is_retried(status: int, category: ErrorCategory) -> None:
    adapter, double = client(lambda _: httpx2.Response(status, json={"error": "x"}))
    fails(category, lambda: adapter.complete(Q))
    assert len(double.requests) == 1


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (httpx2.ReadTimeout("t"), ErrorCategory.PROVIDER_TIMEOUT),
        (httpx2.ConnectError("c"), ErrorCategory.PROVIDER_CONNECTION),
    ],
)
def test_transport_failures_are_explicit_and_not_retried(
    error: Exception, category: ErrorCategory
) -> None:
    def raises(_: httpx2.Request) -> httpx2.Response:
        raise error

    adapter, double = client(raises)
    fails(category, lambda: adapter.complete(Q))
    assert len(double.requests) == 1


# --- deadlines, cancellation, concurrency -------------------------------------------------


class _Slow(httpx2.SyncByteStream):
    """Frames at a steady pace, as a generation arrives. ``closed`` is what ends one in Ollama."""

    def __init__(self, seconds: float = 0.01, count: int = 50) -> None:
        self.seconds = seconds
        self.count = count
        self.closed = Event()
        self.started = Event()

    def __iter__(self) -> Iterator[bytes]:
        for _ in range(self.count):
            self.started.set()
            time.sleep(self.seconds)
            yield frames(text("x"))
        yield frames(done())

    def close(self) -> None:
        self.closed.set()


def test_the_deadline_covers_the_whole_answer_not_each_read() -> None:
    stream = _Slow()
    policy = POLICY.model_copy(update={"call_timeout_seconds": 0.05})
    adapter, _ = client(lambda _: httpx2.Response(200, stream=stream), policy=policy)
    fails(ErrorCategory.PROVIDER_TIMEOUT, lambda: adapter.complete(Q))
    assert stream.closed.is_set()


def test_abort_closes_the_connection_and_frees_the_slot() -> None:
    stream = _Slow()
    adapter, double = client(lambda _: httpx2.Response(200, stream=stream))
    errors: list[MoodyBluesError] = []

    def work() -> None:
        try:
            adapter.complete(Q)
        except MoodyBluesError as exc:
            errors.append(exc)

    thread = Thread(target=work)
    thread.start()
    assert stream.started.wait(2)
    adapter.abort()
    thread.join(2)
    assert not thread.is_alive()
    assert errors[0].detail.category is ErrorCategory.PROVIDER_TIMEOUT
    assert stream.closed.is_set()
    double.handler = answering(text("x"), done())
    assert adapter.complete(Q).content == "x"


def test_a_second_generation_is_refused_while_the_only_slot_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("moody_blues.inference.ollama._SLOT_WAIT_SECONDS", 0.01)
    stream = _Slow(seconds=0.02)
    adapter, _ = client(lambda _: httpx2.Response(200, stream=stream))
    thread = Thread(
        target=lambda: fails(ErrorCategory.PROVIDER_TIMEOUT, lambda: adapter.complete(Q))
    )
    thread.start()
    assert stream.started.wait(2)
    fails(ErrorCategory.PROVIDER_RATE_LIMITED, lambda: adapter.complete(Q))
    adapter.abort()
    thread.join(2)


# --- identity -----------------------------------------------------------------------------


def _server(
    *, capabilities: list[str] | None = None, context: int = 8_192, installed: bool = True
) -> Callable[[httpx2.Request], httpx2.Response]:
    def handle(request: httpx2.Request) -> httpx2.Response:
        match request.url.path:
            case "/api/version":
                return httpx2.Response(200, json={"version": "0.0.1-double"})
            case "/api/tags":
                models = [{"name": MODEL, "digest": DIGEST}] if installed else []
                return httpx2.Response(200, json={"models": models})
            case _:
                return httpx2.Response(
                    200,
                    json={
                        "capabilities": ["completion", "tools"]
                        if capabilities is None
                        else capabilities,
                        "details": {
                            "family": "fx",
                            "parameter_size": "1B",
                            "quantization_level": "Q4",
                        },
                        "model_info": {"fx.context_length": context},
                    },
                )

    return handle


def test_identity_is_read_from_the_running_server() -> None:
    adapter, _ = client(_server())
    identity = adapter.describe()
    assert identity.digest == DIGEST
    assert identity.server_version == "0.0.1-double"
    assert (identity.family, identity.parameter_size, identity.quantization) == ("fx", "1B", "Q4")
    assert identity.context_limit == 8_192
    assert identity.thinking_enabled is False
    assert identity.policy == POLICY


def test_describing_generates_nothing() -> None:
    adapter, double = client(_server())
    adapter.describe()
    assert all(r.url.path != "/api/chat" for r in double.requests)


def test_a_model_that_is_not_installed_is_refused() -> None:
    adapter, _ = client(_server(installed=False))
    fails(ErrorCategory.PROVIDER_MODEL_NOT_FOUND, adapter.describe)


def test_a_model_without_tools_is_refused() -> None:
    adapter, _ = client(_server(capabilities=["completion"]))
    fails(ErrorCategory.PROVIDER_BAD_REQUEST, adapter.describe)


def test_thinking_needs_a_model_that_can() -> None:
    adapter, _ = client(_server(), think=True)
    fails(ErrorCategory.PROVIDER_BAD_REQUEST, adapter.describe)


def test_a_context_below_the_policy_is_refused() -> None:
    adapter, _ = client(_server(context=512))
    fails(ErrorCategory.PROVIDER_BAD_REQUEST, adapter.describe)


def test_nothing_is_sent_at_construction(tmp_path: Path) -> None:
    _, double = client(answering(done()))
    assert double.requests == []
