"""Provider-neutral inference contracts, including multi-turn tool calling.

A conversation is an ordered list of ``ConversationMessage``:

- ``ChatMessage`` — plain text from ``system``, ``user`` or ``assistant`` (unchanged since
  Sprint 1).
- ``AssistantToolCallMessage`` — an assistant turn that requested one or more tool calls,
  optionally with text. The provider's original tool-call ids are kept verbatim, and so are
  the raw ``arguments_json`` strings, even when they are malformed.
- ``ToolResultMessage`` — the result of one tool call, linked by ``tool_call_id``.

``validate_tool_protocol`` enforces the OpenAI-compatible ordering rule: every assistant
tool-call turn is immediately followed by exactly one tool result per call id, before any
other message. Tool results are never flattened into user messages.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    model_validator,
)


class ChatMessage(BaseModel):
    """A plain text message."""

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class ToolSpec(BaseModel):
    """A function tool offered to the model. ``parameters`` is a JSON Schema object."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str
    parameters: dict[str, Any]


class ToolCall(BaseModel):
    """A tool call as returned by the provider. Arguments are raw JSON text;
    callers must validate them with a Pydantic model before use."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=256)
    name: str = Field(max_length=256)
    arguments_json: str


class AssistantToolCallMessage(BaseModel):
    """An assistant turn that requested tool calls. Preserved exactly as received."""

    model_config = ConfigDict(frozen=True)

    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [c.id for c in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise ValueError("tool call ids within one assistant message must be unique")
        return self


class ToolResultMessage(BaseModel):
    """The result of one tool call, delivered back to the model under the original id."""

    model_config = ConfigDict(frozen=True)

    role: Literal["tool"] = "tool"
    tool_call_id: str = Field(min_length=1, max_length=256)
    content: str


def _message_tag(value: Any) -> str:
    if isinstance(value, dict):
        role = value.get("role")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        has_calls = bool(value.get("tool_calls"))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    else:
        role = getattr(value, "role", None)
        has_calls = bool(getattr(value, "tool_calls", None))
    if role == "tool":
        return "tool_result"
    if role == "assistant" and has_calls:
        return "assistant_tool_calls"
    return "text"


ConversationMessage = Annotated[
    Annotated[ChatMessage, Tag("text")]
    | Annotated[AssistantToolCallMessage, Tag("assistant_tool_calls")]
    | Annotated[ToolResultMessage, Tag("tool_result")],
    Discriminator(_message_tag),
]


class ToolProtocolError(ValueError):
    pass


def validate_tool_protocol(messages: Sequence[BaseModel]) -> None:
    """Raise ``ToolProtocolError`` unless tool calls and results pair up correctly.

    After an ``AssistantToolCallMessage``, the next messages must be ``ToolResultMessage``s
    answering each of its call ids exactly once; nothing else may intervene, and the
    conversation must not end with unanswered calls. A tool result anywhere else is an error.
    Ids may repeat across *different* assistant turns (some providers restart numbering).
    """
    pending: set[str] = set()
    for index, message in enumerate(messages):
        if isinstance(message, ToolResultMessage):
            if message.tool_call_id not in pending:
                raise ToolProtocolError(
                    f"message {index}: tool result for {message.tool_call_id!r} does not answer "
                    "an unanswered call of the immediately preceding assistant turn"
                )
            pending.remove(message.tool_call_id)
            continue
        if pending:
            raise ToolProtocolError(
                f"message {index}: tool calls {sorted(pending)} were not answered before the "
                "next message"
            )
        if isinstance(message, AssistantToolCallMessage):
            pending = {c.id for c in message.tool_calls}
    if pending:
        raise ToolProtocolError(f"conversation ends with unanswered tool calls {sorted(pending)}")


class InferenceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: list[ConversationMessage] = Field(min_length=1)
    model: str | None = None  # None -> adapter default
    tools: list[ToolSpec] = Field(default_factory=list[ToolSpec])
    tool_choice: Literal["auto", "required", "none"] | None = None
    max_tokens: int = Field(default=256, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0, le=2)

    @model_validator(mode="after")
    def _protocol(self) -> Self:
        validate_tool_protocol(self.messages)
        return self


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

    def assistant_message(self) -> ChatMessage | AssistantToolCallMessage | None:
        """This result as the assistant turn to append to the conversation history.

        ``None`` when the model returned neither text nor tool calls.
        """
        if self.tool_calls:
            return AssistantToolCallMessage(content=self.content, tool_calls=self.tool_calls)
        if self.content:
            return ChatMessage(role="assistant", content=self.content)
        return None
