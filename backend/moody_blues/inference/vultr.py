"""Vultr Serverless Inference adapter (OpenAI-compatible API via the OpenAI SDK).

No network traffic happens at construction time. Every method call is a live,
potentially chargeable request; nothing in the app calls them implicitly.
"""

from __future__ import annotations

import logging
import time
from typing import cast

import httpx2
import openai
from openai import OpenAI, omit
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from moody_blues.config import Settings
from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.inference import (
    InferenceRequest,
    InferenceResult,
    TokenUsage,
    ToolCall,
)

log = logging.getLogger("moody_blues.inference")

PROVIDER = "vultr"


class InferenceError(MoodyBluesError):
    pass


def classify_provider_error(exc: Exception) -> InferenceError:
    """Map OpenAI-SDK exceptions to our error categories. Order matters: the SDK's
    exception hierarchy has APITimeoutError <: APIConnectionError."""
    category: ErrorCategory
    retryable = False
    match exc:
        case openai.APITimeoutError():
            category, retryable = ErrorCategory.PROVIDER_TIMEOUT, True
        case openai.APIConnectionError():
            category, retryable = ErrorCategory.PROVIDER_CONNECTION, True
        case openai.AuthenticationError() | openai.PermissionDeniedError():
            category = ErrorCategory.PROVIDER_AUTH
        case openai.RateLimitError():
            category, retryable = ErrorCategory.PROVIDER_RATE_LIMITED, True
        case openai.NotFoundError():
            category = ErrorCategory.PROVIDER_MODEL_NOT_FOUND
        case openai.BadRequestError() | openai.UnprocessableEntityError():
            category = ErrorCategory.PROVIDER_BAD_REQUEST
        case openai.InternalServerError():
            category, retryable = ErrorCategory.PROVIDER_SERVER_ERROR, True
        case openai.APIResponseValidationError():
            category = ErrorCategory.PROVIDER_INVALID_RESPONSE
        case openai.APIStatusError(status_code=code) if code >= 500:
            category, retryable = ErrorCategory.PROVIDER_SERVER_ERROR, True
        case _:
            category = ErrorCategory.PROVIDER_BAD_REQUEST
    status = getattr(exc, "status_code", None)
    message = f"{type(exc).__name__}" + (f" (HTTP {status})" if status else "") + f": {exc}"
    return InferenceError(category, message, retryable=retryable)


class VultrInferenceClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        # The SDK performs bounded exponential-backoff retries on connection errors,
        # 408/409/429 and 5xx responses; ``max_retries`` caps them.
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
            http_client=http_client,
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, *, http_client: httpx2.Client | None = None
    ) -> VultrInferenceClient:
        key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
        if not key:
            raise InferenceError(
                ErrorCategory.PROVIDER_NOT_CONFIGURED,
                "MOODY_VULTR_API_KEY is not set; see docs/deployment/vultr-preflight.md",
            )
        return cls(
            api_key=key,
            model=settings.vultr_model,
            base_url=settings.vultr_base_url,
            timeout_seconds=settings.vultr_timeout_seconds,
            max_retries=settings.vultr_max_retries,
            http_client=http_client,
        )

    def list_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self._client.models.list())
        except openai.OpenAIError as exc:
            raise classify_provider_error(exc) from exc

    def complete(self, request: InferenceRequest) -> InferenceResult:
        model = request.model or self.model
        messages = cast(
            "list[ChatCompletionMessageParam]", [m.model_dump() for m in request.messages]
        )
        tools: list[ChatCompletionToolParam] = [
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
        tool_choice = request.tool_choice if tools and request.tool_choice else None

        started = time.perf_counter()
        try:
            completion = self._client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                tools=tools or omit,
                tool_choice=tool_choice or omit,
            )
        except openai.OpenAIError as exc:
            err = classify_provider_error(exc)
            log.warning("inference_failed", extra={"model": model, "category": err.detail.category})
            raise err from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = self._to_result(completion, requested_model=model, latency_ms=latency_ms)
        log.info(
            "inference_completed",
            extra={
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
        completion: ChatCompletion, *, requested_model: str, latency_ms: int
    ) -> InferenceResult:
        if not completion.choices:
            raise InferenceError(
                ErrorCategory.PROVIDER_INVALID_RESPONSE, "provider returned no choices"
            )
        choice = completion.choices[0]
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments_json=tc.function.arguments)
            for tc in (choice.message.tool_calls or [])
            if tc.type == "function"
        ]
        usage = (
            TokenUsage(
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                total_tokens=completion.usage.total_tokens,
            )
            if completion.usage
            else None
        )
        return InferenceResult(
            provider=PROVIDER,
            requested_model=requested_model,
            reported_model=completion.model or None,
            response_id=completion.id or None,
            content=choice.message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage,
            latency_ms=latency_ms,
        )
