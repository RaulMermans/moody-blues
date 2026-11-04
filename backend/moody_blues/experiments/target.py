"""Trusted adapters that run a target against one fresh world.

The coordinator depends on ``TargetPort`` and nothing else. Which target runs is decided by
trusted code when the coordinator is built; an experiment cannot choose it.

``AgentTarget`` goes through the unchanged ``run_agent_scenario`` path, so the Target Agent
keeps its own tools, budgets and gateway. ``ReferenceTarget`` drives the same world with a
scripted executor, and its results are always labeled ``reference_executor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from moody_blues.agents.target import InferencePort
from moody_blues.contracts.agent import (
    AgentBudget,
    AgentConfigName,
    EvidenceSource,
    TerminationReason,
    TokenTotals,
)
from moody_blues.contracts.common import ErrorDetail
from moody_blues.contracts.oracle import OracleReport
from moody_blues.contracts.run import ToolTraceEntry
from moody_blues.contracts.scenario import Scenario
from moody_blues.contracts.world import CommittedChange, CustomerRecord, FinalClaim
from moody_blues.experiments.budget import SpendPort, worst_case_run_tokens
from moody_blues.services.agent_world_runner import run_agent_scenario
from moody_blues.services.world_runner import run_scenario


@dataclass(frozen=True, slots=True)
class TargetRequest:
    scenario: Scenario
    config: AgentConfigName
    world_root: Path
    max_wall_seconds: float
    cancel: Event | None


class TargetResult(BaseModel):
    """What came back from one run, normalized across target kinds."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    target_kind: Literal["llm_agent", "reference_executor"]
    evidence_source: Literal["live_provider", "offline_fixture", "reference_executor"]
    executor: str | None
    provider: str | None
    requested_model: str | None
    reported_models: list[str]
    policy_version: str | None
    policy_sha256: str | None
    termination: str
    run_outcome: str | None
    error: ErrorDetail | None
    claim: FinalClaim | None
    world_id: str
    world_trace: list[ToolTraceEntry]
    final_state: list[CustomerRecord]
    committed_changes: list[CommittedChange]
    oracle: OracleReport
    tokens: TokenTotals | None
    inference_latency_ms: int | None
    wall_ms: int
    estimated_cost_usd: float | None
    cost_note: str
    full_report: dict[str, JsonValue]


class TargetPort(Protocol):
    def run(self, request: TargetRequest) -> TargetResult: ...


class AgentTarget:
    """The real Target Agent. With a ledger, every run is reserved and settled."""

    def __init__(
        self,
        *,
        inference: InferencePort,
        evidence: EvidenceSource,
        provider: str,
        model: str,
        budget: AgentBudget,
        ledger: SpendPort | None = None,
    ) -> None:
        if evidence == "live_provider" and ledger is None:
            raise ValueError("a live target requires a spend ledger")
        self._inference = inference
        self._evidence: EvidenceSource = evidence
        self._provider = provider
        self._model = model
        self._budget = budget
        self._ledger = ledger

    def run(self, request: TargetRequest) -> TargetResult:
        budget = self._budget.model_copy(
            update={
                "max_wall_seconds": min(self._budget.max_wall_seconds, request.max_wall_seconds)
            }
        )
        # Raises BudgetExceededError before anything has happened. If the run below dies, the
        # reservation stays open and keeps counting in full.
        entry = (
            self._ledger.reserve(
                f"experiment:{request.scenario.scenario_id}:{request.config.value}",
                worst_case_tokens=worst_case_run_tokens(budget),
            )
            if self._ledger is not None
            else None
        )
        report = run_agent_scenario(
            request.scenario,
            config=request.config,
            inference=self._inference,
            evidence=self._evidence,
            provider=self._provider,
            model=self._model,
            budget=budget,
            root_dir=request.world_root,
            # Kept so that recovery can read committed state if this run dies. The coordinator
            # removes resolved worlds when the experiment closes.
            keep=True,
            cancel=request.cancel,
        )
        trajectory = report.agent
        cost: float | None = None
        note = "not a live run; nothing was charged"
        if self._ledger is not None and entry is not None:
            cost = round(self._ledger.settle(entry, trajectory.tokens), 6)
            note = "estimate at assumed ceiling prices; not a provider invoice"
        return TargetResult(
            run_id=report.run_id,
            target_kind="llm_agent",
            evidence_source=report.evidence_source,
            executor=None,
            provider=report.provider,
            requested_model=report.requested_model,
            reported_models=report.reported_models,
            policy_version=trajectory.policy_version,
            policy_sha256=trajectory.policy_sha256,
            termination=trajectory.termination.value,
            run_outcome=report.assessment.outcome.value,
            error=trajectory.error,
            claim=trajectory.claim,
            world_id=report.world_id,
            world_trace=report.world_trace,
            final_state=report.final_state,
            committed_changes=report.committed_changes,
            oracle=report.oracle,
            tokens=trajectory.tokens,
            inference_latency_ms=trajectory.inference_latency_ms,
            wall_ms=trajectory.wall_ms,
            estimated_cost_usd=cost,
            cost_note=note,
            full_report=report.model_dump(mode="json"),
        )


class ReferenceTarget:
    """A scripted executor. Shows world mechanics; says nothing about any model."""

    def __init__(self, executor: str) -> None:
        self._executor = executor

    def run(self, request: TargetRequest) -> TargetResult:
        report = run_scenario(
            request.scenario, self._executor, root_dir=request.world_root, keep=True
        )
        return TargetResult(
            run_id=f"ref_{report.fingerprint[:12]}_{report.world_id[-6:]}",
            target_kind="reference_executor",
            evidence_source="reference_executor",
            executor=self._executor,
            provider=None,
            requested_model=None,
            reported_models=[],
            policy_version=None,
            policy_sha256=None,
            termination=TerminationReason.FINAL_CLAIM.value
            if report.claim is not None
            else TerminationReason.NO_FINAL_CLAIM.value,
            run_outcome=None,
            error=None,
            claim=report.claim,
            world_id=report.world_id,
            world_trace=report.tool_trace,
            final_state=report.final_state,
            committed_changes=report.committed_changes,
            oracle=report.oracle,
            tokens=None,
            inference_latency_ms=None,
            wall_ms=0,
            estimated_cost_usd=None,
            cost_note="reference executor; no model was called",
            full_report=report.model_dump(mode="json"),
        )
