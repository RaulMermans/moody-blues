"""Local Ollama adapter, behind the same ``InferencePort`` as every other model.

It talks to Ollama's native ``/api/chat``, not its OpenAI-compatible route, because only the native
route takes a context size: left at its default, a long prompt is cut with no error. The native
route also reports the timings and the digest that the evidence records. See ADR 0014.

No network traffic happens at construction. Nothing here retries: a call that fails is reported and
never repeated. Ollama has no ``tool_choice``: "required" is sent as tools on offer, so a model
may still answer in text, and the caller's own validation decides what that means.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from threading import BoundedSemaphore, Event, Lock
from typing import Any, cast
from uuid import uuid4

import httpx2

from moody_blues.config import Settings
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import (
    AssistantToolCallMessage,
    ChatMessage,
    InferenceRequest,
    InferenceResult,
    InferenceTimings,
    LocalInferencePolicy,
    LocalModelIdentity,
    TokenUsage,
    ToolCall,
    ToolResultMessage,
)
from moody_blues.inference.vultr import InferenceError

log = logging.getLogger("moody_blues.inference")

PROVIDER = "ollama"
REQUIRED_CAPABILITIES = frozenset({"completion", "tools"})
# Literal loopback only. A name could resolve anywhere, and a path or userinfo could smuggle a host.
_LOOPBACK = re.compile(r"http://(127\.0\.0\.1|\[::1\])(:(?P<port>[0-9]{1,5}))?/?")
_CONNECT_SECONDS = 2.0
_METADATA_SECONDS = 10.0
_NANOS_PER_MS = 1_000_000
# One frame per token is about 150 bytes. Far above any honest answer within ``num_predict``.
_MAX_RESPONSE_BYTES = 4_000_000
# Frames that carry no token (the last one, a tool call). Beyond this the limit was not honored.
_FRAME_SLACK = 16
# Three bytes per token is below the average for this text, so the estimate errs towards refusing.
_BYTES_PER_TOKEN = 3
_SLOT_WAIT_SECONDS = 2.0


class LocalEndpointError(ValueError):
    """This address is not an approved local endpoint. Nothing was contacted."""


def validate_local_endpoint(url: str) -> str:
    """The address, normalized, or a refusal. Only plain HTTP to a literal loopback address."""
    match = _LOOPBACK.fullmatch(url)
    if match is None:
        raise LocalEndpointError(
            "the Ollama endpoint must be http://127.0.0.1[:port] or http://[::1][:port], "
            "with no path, query, credentials or host name"
        )
    port = match["port"]
    if port is not None and not 1 <= int(port) <= 65_535:
        raise LocalEndpointError("the Ollama endpoint's port is out of range")
    return url.rstrip("/")


def check_local_model(model: str, allowlist: tuple[str, ...]) -> None:
    if model not in allowlist:
        raise InferenceError(
            ErrorCategory.PROVIDER_MODEL_NOT_FOUND,
            f"model {model} is not on the host's local allowlist",
        )


def to_ollama_messages(
    messages: list[ChatMessage | AssistantToolCallMessage | ToolResultMessage],
) -> list[dict[str, Any]]:
    """The conversation in Ollama's shape. Arguments are objects there, and strings here."""
    wire: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for message in messages:
        match message:
            case ToolResultMessage():
                wire.append(
                    {
                        "role": "tool",
                        "tool_name": names.get(message.tool_call_id, ""),
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
            case AssistantToolCallMessage():
                calls: list[dict[str, Any]] = []
                for call in message.tool_calls:
                    names[call.id] = call.name
                    calls.append(
                        {
                            "id": call.id,
                            "function": {
                                "name": call.name,
                                "arguments": _arguments(call.arguments_json),
                            },
                        }
                    )
                wire.append(
                    {"role": "assistant", "content": message.content or "", "tool_calls": calls}
                )
            case ChatMessage():
                wire.append({"role": message.role, "content": message.content})
    return wire


def _arguments(text: str) -> dict[str, Any]:
    """Refused, not repaired: this format has no way to carry arguments that are not an object."""
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise InferenceError(
            ErrorCategory.PROVIDER_BAD_REQUEST, "tool call arguments in history are not JSON"
        ) from exc
    if not isinstance(value, dict):
        raise InferenceError(
            ErrorCategory.PROVIDER_BAD_REQUEST, "tool call arguments in history are not an object"
        )
    return cast("dict[str, Any]", value)


@dataclass(slots=True)
class _Stream:
    """One answer, as its frames arrived."""

    content: list[str] = field(default_factory=list[str])
    thinking_chars: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    final: dict[str, Any] | None = None
    frames: int = 0


def _status_error(status: int, body: str) -> InferenceError:
    message = f"Ollama HTTP {status}: {body[:300]}"
    if status == 404:
        return InferenceError(ErrorCategory.PROVIDER_MODEL_NOT_FOUND, message)
    if status == 429:
        return InferenceError(ErrorCategory.PROVIDER_RATE_LIMITED, message)
    if status >= 500:
        return InferenceError(ErrorCategory.PROVIDER_SERVER_ERROR, message)
    # Includes every 3xx: a redirect is never followed, because it could leave the loopback.
    return InferenceError(ErrorCategory.PROVIDER_BAD_REQUEST, message)


def _lines(response: httpx2.Response) -> Iterator[bytes]:
    pending = b""
    seen = 0
    for chunk in response.iter_bytes():
        seen += len(chunk)
        if seen > _MAX_RESPONSE_BYTES:
            raise InferenceError(
                ErrorCategory.PROVIDER_INVALID_RESPONSE, "the answer passed the size limit"
            )
        pending += chunk
        *complete, pending = pending.split(b"\n")
        yield from complete
    if pending:
        yield pending


def _frame(line: bytes) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except ValueError as exc:
        raise InferenceError(
            ErrorCategory.PROVIDER_INVALID_RESPONSE, "a frame of the answer was not JSON"
        ) from exc
    if not isinstance(value, dict):
        raise InferenceError(
            ErrorCategory.PROVIDER_INVALID_RESPONSE, "a frame of the answer was not an object"
        )
    return cast("dict[str, Any]", value)


def _tool_call(raw: dict[str, Any], response_id: str, index: int) -> ToolCall:
    function = cast("dict[str, Any]", raw.get("function") or {})
    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise InferenceError(
            ErrorCategory.PROVIDER_INVALID_RESPONSE, "a tool call in the answer had no name"
        )
    arguments = function.get("arguments")
    text = arguments if isinstance(arguments, str) else json.dumps(arguments)
    provided = raw.get("id")
    # Ollama's ids are its own. A build without them still needs results to link to calls.
    call_id = provided if isinstance(provided, str) and provided else f"{response_id}_t{index}"
    return ToolCall(id=call_id, name=name[:256], arguments_json=text)


class OllamaInferenceClient:
    """One approved model, on one approved address. Satisfies ``InferencePort``."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        allowlist: tuple[str, ...],
        policy: LocalInferencePolicy,
        think: bool,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        check_local_model(model, allowlist)
        self.base_url = validate_local_endpoint(base_url)
        self.model = model
        self._policy = policy
        self._think = think
        self._timeout = policy.call_timeout_seconds
        self._slots = BoundedSemaphore(policy.max_concurrent_generations)
        self._aborts: set[Event] = set()
        self._lock = Lock()
        # The environment's proxy settings could carry this somewhere else, so they are ignored.
        self._client = httpx2.Client(
            base_url=self.base_url,
            timeout=httpx2.Timeout(self._timeout, connect=_CONNECT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        policy: LocalInferencePolicy,
        *,
        transport: httpx2.BaseTransport | None = None,
    ) -> OllamaInferenceClient:
        return cls(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            allowlist=settings.local_model_allowlist,
            policy=policy,
            think=settings.ollama_think,
            transport=transport,
        )

    # --- what is running ----------------------------------------------------------------

    def _get_json(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, json=body, timeout=_METADATA_SECONDS)
        except httpx2.TimeoutException as exc:
            raise InferenceError(
                ErrorCategory.PROVIDER_TIMEOUT, "Ollama did not answer in time", retryable=True
            ) from exc
        except httpx2.TransportError as exc:
            raise InferenceError(
                ErrorCategory.PROVIDER_CONNECTION,
                f"Ollama is not reachable at {self.base_url}",
                retryable=True,
            ) from exc
        if response.status_code != 200:
            raise _status_error(response.status_code, response.text)
        return _frame(response.content)

    def installed_models(self) -> dict[str, str]:
        """Model name to digest, as the running server reports them."""
        models: Any = self._get_json("GET", "/api/tags", None).get("models")
        listed: dict[str, str] = {}
        for entry in cast("list[dict[str, Any]]", models or []):
            name, digest = entry.get("name"), entry.get("digest")
            if isinstance(name, str) and isinstance(digest, str):
                listed[name] = digest
        return listed

    def describe(self) -> LocalModelIdentity:
        """Identity from the running provider. Refuses a model it cannot use. Generates nothing."""
        version = self._get_json("GET", "/api/version", None).get("version")
        digest = self.installed_models().get(self.model)
        if digest is None:
            raise InferenceError(
                ErrorCategory.PROVIDER_MODEL_NOT_FOUND, f"model {self.model} is not installed"
            )
        shown = self._get_json("POST", "/api/show", {"model": self.model})
        capabilities = sorted(str(c) for c in cast("list[Any]", shown.get("capabilities") or []))
        missing = REQUIRED_CAPABILITIES - set(capabilities)
        if missing:
            raise InferenceError(
                ErrorCategory.PROVIDER_BAD_REQUEST,
                f"model {self.model} lacks {sorted(missing)}",
            )
        if self._think and "thinking" not in capabilities:
            raise InferenceError(
                ErrorCategory.PROVIDER_BAD_REQUEST, f"model {self.model} has no thinking mode"
            )
        details = cast("dict[str, Any]", shown.get("details") or {})
        info = cast("dict[str, Any]", shown.get("model_info") or {})
        limits = [v for k, v in info.items() if k.endswith(".context_length")]
        context_limit = limits[0] if limits and isinstance(limits[0], int) else None
        if context_limit is not None and context_limit < self._policy.context_tokens:
            raise InferenceError(
                ErrorCategory.PROVIDER_BAD_REQUEST,
                f"model {self.model} supports {context_limit} tokens of context, "
                f"below the {self._policy.context_tokens} this policy uses",
            )
        return LocalModelIdentity(
            server_version=str(version),
            model=self.model,
            digest=digest,
            family=details.get("family"),
            parameter_size=details.get("parameter_size"),
            quantization=details.get("quantization_level"),
            capabilities=capabilities,
            context_limit=context_limit,
            thinking_enabled=self._think,
            host_os=platform.system(),
            host_arch=platform.machine(),
            policy=self._policy,
        )

    # --- inference ----------------------------------------------------------------------

    def abort(self) -> None:
        """Stops generations in progress: closing the connection is what ends one in Ollama."""
        with self._lock:
            for event in self._aborts:
                event.set()

    def _payload(self, request: InferenceRequest, model: str) -> dict[str, Any]:
        """Refuses what could not fit, rather than letting the provider cut it without saying."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
        if request.tool_choice == "none":
            tools = []
        limit = min(request.max_tokens, self._policy.max_completion_tokens)
        payload: dict[str, Any] = {
            "model": model,
            "stream": True,
            "think": self._think,
            "messages": to_ollama_messages(request.messages),
            "options": {
                "num_ctx": self._policy.context_tokens,
                "num_predict": limit,
                "temperature": request.temperature,
            },
        }
        if tools:
            payload["tools"] = tools
        size = len(json.dumps(payload).encode())
        if size > self._policy.max_prompt_bytes:
            raise InferenceError(
                ErrorCategory.PROVIDER_BAD_REQUEST,
                f"the request is {size} bytes, over the {self._policy.max_prompt_bytes} allowed",
            )
        if size // _BYTES_PER_TOKEN + limit > self._policy.context_tokens:
            raise InferenceError(
                ErrorCategory.PROVIDER_BAD_REQUEST,
                f"about {size // _BYTES_PER_TOKEN} prompt tokens and {limit} of output would not "
                f"fit the {self._policy.context_tokens} token context",
            )
        return payload

    def _read(self, response: httpx2.Response, limit: int, deadline: float, stop: Event) -> _Stream:
        stream = _Stream()
        for line in _lines(response):
            if stop.is_set():
                raise InferenceError(ErrorCategory.PROVIDER_TIMEOUT, "the host stopped this call")
            if time.monotonic() >= deadline:
                raise InferenceError(
                    ErrorCategory.PROVIDER_TIMEOUT, "the call passed its deadline", retryable=True
                )
            if not line.strip():
                continue
            frame = _frame(line)
            if "error" in frame:
                raise InferenceError(
                    ErrorCategory.PROVIDER_SERVER_ERROR, f"Ollama: {str(frame['error'])[:300]}"
                )
            stream.frames += 1
            if stream.frames > limit + _FRAME_SLACK:
                raise InferenceError(
                    ErrorCategory.PROVIDER_INVALID_RESPONSE, "the answer passed the output limit"
                )
            message = cast("dict[str, Any]", frame.get("message") or {})
            stream.content.append(str(message.get("content") or ""))
            stream.thinking_chars += len(str(message.get("thinking") or ""))
            stream.calls.extend(cast("list[dict[str, Any]]", message.get("tool_calls") or []))
            if frame.get("done") is True:
                stream.final = frame
        return stream

    def _send(self, payload: dict[str, Any], limit: int, stop: Event) -> _Stream:
        deadline = time.monotonic() + self._timeout
        try:
            with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    response.read()
                    raise _status_error(response.status_code, response.text)
                return self._read(response, limit, deadline, stop)
        except httpx2.TimeoutException as exc:
            raise InferenceError(
                ErrorCategory.PROVIDER_TIMEOUT, "Ollama did not answer in time", retryable=True
            ) from exc
        except httpx2.TransportError as exc:
            raise InferenceError(
                ErrorCategory.PROVIDER_CONNECTION,
                f"Ollama is not reachable at {self.base_url}",
                retryable=True,
            ) from exc

    def complete(self, request: InferenceRequest) -> InferenceResult:
        model = request.model or self.model
        if model != self.model:
            raise InferenceError(
                ErrorCategory.PROVIDER_MODEL_NOT_FOUND,
                f"this client serves {self.model}, not {model}",
            )
        payload = self._payload(request, model)
        limit: int = payload["options"]["num_predict"]
        response_id = f"local_{uuid4().hex[:12]}"  # Ollama issues none. This correlates the host's
        if not self._slots.acquire(timeout=_SLOT_WAIT_SECONDS):
            raise InferenceError(
                ErrorCategory.PROVIDER_RATE_LIMITED, "no generation slot is free on this machine"
            )
        stop = Event()
        with self._lock:
            self._aborts.add(stop)
        started = time.perf_counter()
        try:
            stream = self._send(payload, limit, stop)
        finally:
            with self._lock:
                self._aborts.discard(stop)
            self._slots.release()
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = self._to_result(stream, model, response_id, latency_ms)
        log.info(
            "inference_completed",
            extra={
                "provider": PROVIDER,
                "response_id": response_id,
                "requested_model": model,
                "reported_model": result.reported_model,
                "latency_ms": latency_ms,
                "tool_calls": len(result.tool_calls),
                "total_tokens": result.usage.total_tokens if result.usage else None,
            },
        )
        return result

    @staticmethod
    def _to_result(
        stream: _Stream, requested_model: str, response_id: str, latency_ms: int
    ) -> InferenceResult:
        final = stream.final
        if final is None:  # never repaired: what survived of a broken stream is not an answer
            raise InferenceError(
                ErrorCategory.PROVIDER_INVALID_RESPONSE, "the answer ended before it finished"
            )
        calls = [_tool_call(raw, response_id, i + 1) for i, raw in enumerate(stream.calls)]
        prompt, completion = final.get("prompt_eval_count"), final.get("eval_count")
        known = isinstance(prompt, int) and isinstance(completion, int)
        usage = (
            TokenUsage(
                prompt_tokens=cast("int", prompt),
                completion_tokens=cast("int", completion),
                total_tokens=cast("int", prompt) + cast("int", completion),
            )
            if known
            else None
        )
        reason = final.get("done_reason")
        return InferenceResult(
            provider=PROVIDER,
            requested_model=requested_model,
            reported_model=str(final.get("model") or "") or None,
            response_id=response_id,
            content="".join(stream.content) or None,
            tool_calls=calls,
            # "length" stays, so a cut-off tool call is still read as cut off.
            finish_reason="tool_calls" if calls and reason == "stop" else reason,
            usage=usage,
            latency_ms=latency_ms,
            timings=InferenceTimings(
                load_ms=int(final.get("load_duration") or 0) // _NANOS_PER_MS,
                prompt_eval_ms=int(final.get("prompt_eval_duration") or 0) // _NANOS_PER_MS,
                generation_ms=int(final.get("eval_duration") or 0) // _NANOS_PER_MS,
                total_ms=int(final.get("total_duration") or 0) // _NANOS_PER_MS,
                thinking_chars=stream.thinking_chars,
            ),
        )
