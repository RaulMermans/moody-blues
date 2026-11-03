"""Provider-neutral inference contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class ToolSpec(BaseModel):
    """A function tool offered to the model. ``parameters`` is a JSON Schema object."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str
    parameters: dict[str, Any]


class InferenceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None  # None -> adapter default
    tools: list[ToolSpec] = Field(default_factory=list[ToolSpec])
    tool_choice: Literal["auto", "required", "none"] | None = None
    max_tokens: int = Field(default=256, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0, le=2)


class ToolCall(BaseModel):
    """A tool call as returned by the provider. Arguments are raw JSON text;
    callers must validate them with a Pydantic model before use."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments_json: str


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class InferenceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    requested_model: str
    reported_model: str | None  # what the provider says actually served the request
    response_id: str | None
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list[ToolCall])
    finish_reason: str | None
    usage: TokenUsage | None
    latency_ms: int = Field(ge=0)
