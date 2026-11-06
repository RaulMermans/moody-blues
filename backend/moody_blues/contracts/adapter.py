"""External agent adapter contract, version ``mb-agent/1``.

Everything here crosses the trust boundary to code MOODY BLUES did not write. Inbound messages
(``AgentMessage``) say what an external agent *proposes*; none can carry SQL, paths, limits or a
verdict, and a final message is a claim like any other. Outbound messages are what the host
chooses to reveal: the same observations an internal target agent gets, and no more.

``ExecutionContext.scenario_ref`` is an opaque id. Scenario ids name their faults
(``phantom-failure``), and a target must never learn what its world will do to it.

The SDK in ``sdk/python`` speaks this format without importing it, so a sandbox needs no
dependencies. ``tests/external/test_contract.py`` holds the two sides together.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from moody_blues.contracts.inference import InferenceTimings, LocalModelIdentity, ToolCall
from moody_blues.contracts.world import ToolResponse

ADAPTER_PROTOCOL = "mb-agent/1"
SUPPORTED_PROTOCOLS: tuple[str, ...] = (ADAPTER_PROTOCOL,)

MAX_AGENT_MESSAGE_BYTES = 65_536  # one line from the agent
MAX_BUNDLE_BYTES = 4_000_000
MAX_EVIDENCE_REFS = 64
# Beside the world: what the host wrote down before asking a provider, for recovery to read.
MODEL_INTENTS_SUFFIX = ".model-calls.jsonl"
MAX_STDERR_EXCERPT_CHARS = 500

AgentId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")]
Version = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
CallId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
Entrypoint = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][\w.]{0,127}:[A-Za-z_]\w{0,63}$")]
PackageName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_]\w{0,63}$")]
ConfigRef = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class TargetType(StrEnum):
    """What the agent *says* it is. The evidence label comes from what was observed instead."""

    SCRIPTED = "scripted"
    LLM = "llm"


class Capability(StrEnum):
    TOOLS = "tools"
    CANCELLATION = "cancellation"
    MODEL = "model"  # host-brokered inference; granted per run, never by the agent itself


class Scope(StrEnum):
    CRM_READ = "crm:read"
    CRM_WRITE = "crm:write"
    QUEUE_READ = "queue:read"
    QUEUE_WRITE = "queue:write"


class AgentIdentity(_Wire):
    agent_id: AgentId
    name: str = Field(min_length=1, max_length=120)
    version: Version
    target_type: Literal["scripted", "llm"]
    capabilities: list[Literal["tools", "cancellation", "model"]] = Field(max_length=8)
    # Names of settings the agent reads, never their values.
    config_refs: list[ConfigRef] = Field(default_factory=list[ConfigRef], max_length=16)
    sdk_version: Version


class AgentManifest(BaseModel):
    """The registration file. Parsed by trusted code; the hello must agree with it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol: str
    agent_id: AgentId
    name: str = Field(min_length=1, max_length=120)
    version: Version
    target_type: TargetType
    package: PackageName
    entrypoint: Entrypoint
    capabilities: list[Capability] = Field(min_length=1, max_length=8)
    scopes: list[Scope] = Field(min_length=1, max_length=4)
    config_refs: list[ConfigRef] = Field(default_factory=list[ConfigRef], max_length=16)


class AdapterLimits(BaseModel):
    """Set by trusted code. Nothing an agent sends can change them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    startup_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    run_timeout_seconds: float = Field(default=60.0, gt=0, le=110)
    cancel_grace_seconds: float = Field(default=1.0, ge=0, le=5)
    exit_grace_seconds: float = Field(default=1.0, ge=0, le=5)
    max_tool_calls: int = Field(default=16, ge=1, le=100)
    # Refused calls are answered, so a broken agent can recover. A flood of them ends the run.
    max_rejected_calls: int = Field(default=8, ge=0, le=100)


# --- inbound: what an agent may propose -------------------------------------------------------


class _Inbound(_Wire):
    protocol: Literal["mb-agent/1"]


class HelloMessage(_Inbound):
    type: Literal["hello"]
    agent: AgentIdentity


class ToolCallMessage(_Inbound):
    type: Literal["tool_call"]
    call_id: CallId
    tool: str = Field(min_length=1, max_length=64)
    # Any JSON here: a non-object is answered with a rejection, like any other bad arguments.
    arguments: JsonValue


class ModelCallMessage(_Inbound):
    type: Literal["model_call"]
    call_id: CallId
    # Validated by ``InferenceRequest``. Model, temperature, tools and limits are set by the host.
    messages: list[dict[str, JsonValue]] = Field(min_length=1, max_length=64)


class AgentOutcome(_Wire):
    status: Literal["completed", "not_completed"]
    customer_id: str | None = Field(default=None, max_length=64)
    # Additive: the record in a world without customers. Agents that never set it are unaffected.
    record_id: str | None = Field(default=None, max_length=64, exclude_if=lambda v: v is None)


class FinalMessage(_Inbound):
    """The agent's report. A claim for the Oracle to check, never a result."""

    type: Literal["final"]
    completion: Literal["finished", "failed", "cancelled"]
    outcome: AgentOutcome | None = None
    message: str = Field(default="", max_length=2_000)
    error_class: str | None = Field(default=None, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    evidence_refs: list[CallId] = Field(default_factory=list[CallId], max_length=MAX_EVIDENCE_REFS)


AgentMessage = Annotated[
    HelloMessage | ToolCallMessage | ModelCallMessage | FinalMessage, Field(discriminator="type")
]
ALLOWED_MESSAGES: frozenset[str] = frozenset({"hello", "tool_call", "model_call", "final"})


class AdapterRejectionCode(StrEnum):
    """Why a line from an agent was not acted on. Each of these ends the run."""

    OVERSIZED = "oversized"
    INVALID_ENCODING = "invalid_encoding"
    MALFORMED_JSON = "malformed_json"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    UNKNOWN_MESSAGE = "unknown_message"
    SCHEMA_VIOLATION = "schema_violation"
    OUT_OF_ORDER = "out_of_order"
    IDENTITY_MISMATCH = "identity_mismatch"
    CAPABILITY_REFUSED = "capability_refused"


class AdapterRejection(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: AdapterRejectionCode
    detail: str = Field(max_length=300)


# --- outbound: what the host reveals ----------------------------------------------------------


class ToolDefinition(_Wire):
    name: str
    description: str
    parameters: dict[str, JsonValue]
    access: Literal["read", "write"]


class TaskSpec(_Wire):
    mission: str  # the same prose a model-driven target receives
    objective: dict[str, JsonValue]  # the world's objective, as that world serializes it


class ExecutionContext(_Wire):
    run_id: str
    correlation_id: str
    scenario_ref: str  # opaque; see the module docstring
    task: TaskSpec
    tools: list[ToolDefinition]
    scopes: list[str]
    deadline_seconds: float
    max_tool_calls: int
    capabilities: list[str]


class WelcomeMessage(_Wire):
    protocol: Literal["mb-agent/1"] = ADAPTER_PROTOCOL
    type: Literal["welcome"] = "welcome"
    context: ExecutionContext


class RefusedMessage(_Wire):
    protocol: Literal["mb-agent/1"] = ADAPTER_PROTOCOL
    type: Literal["refused"] = "refused"
    code: AdapterRejectionCode
    supported_protocols: list[str] = Field(default_factory=lambda: list(SUPPORTED_PROTOCOLS))


class CallRejection(_Wire):
    code: str  # a ``ToolCallDisposition`` value
    message: str = Field(max_length=500)


class ToolResultMessage(_Wire):
    """One tool's answer. ``response`` is exactly what the gateway delivered, faults included."""

    protocol: Literal["mb-agent/1"] = ADAPTER_PROTOCOL
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    evidence_ref: str | None  # the gateway's call id; None if nothing reached the gateway
    response: ToolResponse | None
    rejection: CallRejection | None
    calls_remaining: int


class ModelResultMessage(_Wire):
    protocol: Literal["mb-agent/1"] = ADAPTER_PROTOCOL
    type: Literal["model_result"] = "model_result"
    call_id: str
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list[ToolCall])
    finish_reason: str | None = None
    rejection: CallRejection | None = None


class CancelMessage(_Wire):
    protocol: Literal["mb-agent/1"] = ADAPTER_PROTOCOL
    type: Literal["cancel"] = "cancel"
    reason: Literal["operator_cancelled"] = "operator_cancelled"


# --- evidence ---------------------------------------------------------------------------------


class AdapterEventKind(StrEnum):
    REGISTERED = "adapter_registered"
    STARTED = "adapter_started"
    HANDSHAKE_ACCEPTED = "handshake_accepted"
    HANDSHAKE_REJECTED = "handshake_rejected"
    TOOL_REQUEST_ACCEPTED = "tool_request_accepted"
    TOOL_REQUEST_REJECTED = "tool_request_rejected"
    TOOL_RESPONSE_DELIVERED = "tool_response_delivered"
    MODEL_REQUEST_ACCEPTED = "model_request_accepted"
    MODEL_REQUEST_REJECTED = "model_request_rejected"
    MODEL_CALL_BROKERED = "model_call_brokered"
    MODEL_CALL_FAILED = "model_call_failed"
    MODEL_CALL_UNCERTAIN = "model_call_uncertain"
    MESSAGE_REJECTED = "message_rejected"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_CANCELLED = "execution_cancelled"
    ADAPTER_CRASHED = "adapter_crashed"
    ORACLE_VERIFIED = "oracle_verification_completed"
    EVIDENCE_PERSISTED = "evidence_persisted"


class AdapterEvent(BaseModel):
    """One lifecycle fact. Ids and fixed codes only: never agent text or tool arguments."""

    model_config = ConfigDict(frozen=True)

    seq: int = Field(ge=1)
    elapsed_ms: int = Field(ge=0)
    kind: AdapterEventKind
    call_id: str | None = None
    code: str | None = None


class AdapterEnvironment(BaseModel):
    """Where the agent ran. ``test_double`` means it was contained by nothing."""

    model_config = ConfigDict(frozen=True)

    execution_mode: Literal["docker_sandbox", "local_process_test_double"]
    session_id: str
    image: str
    image_id: str | None
    network_enabled: bool
    memory_mb: int
    pids_limit: int


class AdapterExit(BaseModel):
    model_config = ConfigDict(frozen=True)

    exit_code: int | None
    oom_killed: bool
    killed_by_host: bool
    cleaned_up: bool
    stdout_bytes: int
    stderr_bytes: int
    stderr_sha256: str
    # Written by the agent: for a person to look at, and read by nothing.
    untrusted_stderr_excerpt: str = Field(max_length=MAX_STDERR_EXCERPT_CHARS)


class ModelCallStatus(StrEnum):
    """What became of one ``model_call``, as the host saw it."""

    COMPLETED = "completed"  # an answer was delivered to the agent
    REJECTED = "rejected"  # refused before any provider was asked; nothing can be billed
    FAILED = "failed"  # the provider refused it
    MALFORMED = "malformed"  # the provider answered with something unusable; never delivered
    UNCERTAIN = "uncertain"  # no answer the host can trust: it may have run, and may be billed


# Reached a provider, so these make a run a model run, and may cost money.
MODEL_ATTEMPTED: frozenset[ModelCallStatus] = frozenset(
    {
        ModelCallStatus.COMPLETED,
        ModelCallStatus.FAILED,
        ModelCallStatus.MALFORMED,
        ModelCallStatus.UNCERTAIN,
    }
)


class ModelCallRecord(BaseModel):
    """One brokered request. Written by the host, from what the host did.

    ``request_id`` is the host's and stable for the run; ``call_id`` is the agent's word. Hashes
    stand in for the text: the conversation is the agent's, and may hold anything.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str
    call_id: str
    status: ModelCallStatus
    code: str | None = None  # why, for anything but ``completed``
    provider: str | None = None
    model: str | None = None  # the approved model, set by the host
    reported_model: str | None = None  # what the provider said it ran
    response_id: str | None = None
    finish_reason: str | None = None
    prompt_bytes: int = Field(ge=0)
    prompt_sha256: str
    response_sha256: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    # Sprint 17: what a local provider measured. Left out when absent.
    timings: InferenceTimings | None = Field(default=None, exclude_if=lambda v: v is None)


class ExternalAgentRecord(BaseModel):
    """Provenance of one external run. ``declared_target_type`` is the agent's word for it;
    ``model_calls`` is what the host saw, and only that can make a run an LLM run."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    name: str
    agent_version: str
    declared_target_type: TargetType
    protocol: str
    sdk_version: str | None  # None: no valid hello arrived
    manifest_sha256: str
    bundle_sha256: str
    environment: AdapterEnvironment | None  # None: the sandbox never started
    limits: AdapterLimits
    granted_tools: list[str]
    granted_scopes: list[str]
    model_calls: int
    startup_ms: int | None
    wall_ms: int
    exit: AdapterExit | None
    rejection: AdapterRejection | None  # the line that ended the run, if one did
    rejected_line_sha256: str | None
    # The agent's final report as sent, kept apart from the claim the Oracle checks.
    final: FinalMessage | None
    # Quoted references that match no call in this run. Recorded, and believed by nothing.
    unknown_evidence_refs: list[str]
    # sha256 chained over every protocol line, in both directions.
    transcript_sha256: str
    transcript_lines: int
    events: list[AdapterEvent]
    # Sprint 16. Absent from earlier records and left out when empty, so those stay byte-identical.
    # Sprint 17: the local model that answered, read from the running provider.
    model_identity: LocalModelIdentity | None = Field(default=None, exclude_if=lambda v: v is None)
    model_requests: list[ModelCallRecord] = Field(
        default_factory=list[ModelCallRecord], exclude_if=lambda v: not v
    )
