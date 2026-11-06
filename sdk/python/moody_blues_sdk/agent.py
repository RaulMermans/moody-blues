"""What you implement, and what you are given."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from moody_blues_sdk.client import ModelClient, ToolClient


@dataclass(frozen=True, slots=True)
class CustomerTask:
    name: str
    email: str
    metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class Task:
    """What you are asked to do. It says nothing about how the test environment behaves."""

    mission: str  # The whole assignment as prose: hand this to a model.
    instructions: str
    objective: dict[str, Any]  # The task as data, in the terms of the world it belongs to.
    _customer: CustomerTask | None = None

    @property
    def customer(self) -> CustomerTask:
        """The customer to create. Only a CRM task has one; read ``objective`` anywhere else."""
        if self._customer is None:
            raise ValueError("this task has no customer; read task.objective")
        return self._customer


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema of the arguments
    access: Literal["read", "write"]


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    correlation_id: str
    scenario_ref: str  # Opaque on purpose: it identifies the run's world, not what it does.
    task: Task
    tools: tuple[ToolDefinition, ...]
    scopes: tuple[str, ...]
    deadline_seconds: float  # From the moment you received this context.
    max_tool_calls: int
    capabilities: tuple[str, ...]
    model: ModelClient | None
    _cancel: Event

    @property
    def cancelled(self) -> bool:
        """True once the host asked you to stop. ``ToolClient.call`` also raises ``Cancelled``."""
        return self._cancel.is_set()


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Your final report. It is recorded as a claim and then checked; it decides nothing."""

    completion: Literal["finished", "failed", "cancelled"]
    status: Literal["completed", "not_completed"] | None = None
    customer_id: str | None = None
    message: str = ""
    error_class: str | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple[str, ...])
    record_id: str | None = None  # The record you mean, in a world without customers.

    @classmethod
    def completed(
        cls,
        *,
        customer_id: str | None = None,
        record_id: str | None = None,
        message: str = "",
        evidence: tuple[str, ...] = (),
    ) -> AgentResult:
        return cls("finished", "completed", customer_id, message, None, evidence, record_id)

    @classmethod
    def not_completed(
        cls,
        *,
        customer_id: str | None = None,
        record_id: str | None = None,
        message: str = "",
        evidence: tuple[str, ...] = (),
    ) -> AgentResult:
        return cls("finished", "not_completed", customer_id, message, None, evidence, record_id)

    @classmethod
    def failed(cls, error_class: str = "agent_error", *, message: str = "") -> AgentResult:
        """Your agent could not finish. Use ``not_completed`` if it finished and fell short."""
        return cls("failed", None, None, message, error_class)

    def to_message(self) -> dict[str, Any]:
        outcome: dict[str, Any] | None = (
            None
            if self.status is None
            else {"status": self.status, "customer_id": self.customer_id}
        )
        if outcome is not None and self.record_id is not None:
            outcome["record_id"] = self.record_id
        return {
            "type": "final",
            "completion": self.completion,
            "outcome": outcome,
            "message": self.message[:2000],
            "error_class": self.error_class,
            "evidence_refs": list(self.evidence),
        }


class AgentAdapter:
    """Subclass this. Set the class attributes to match your agent's manifest."""

    agent_id: ClassVar[str]
    name: ClassVar[str]
    version: ClassVar[str] = "0.1.0"
    target_type: ClassVar[Literal["scripted", "llm"]] = "scripted"
    capabilities: ClassVar[tuple[str, ...]] = ("tools", "cancellation")
    config_refs: ClassVar[tuple[str, ...]] = ()

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        raise NotImplementedError
