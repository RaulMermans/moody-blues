"""``ExternalAgentTarget``: an external agent as one more kind of target.

The coordinator depends on ``TargetPort`` and nothing else, so everything around a run stays as it
is: authorization, faults, the journal, recovery, the Oracle and the evidence. Only what drives the
tools differs. An agent receives ``world.gateway`` through the driver, and the Oracle reads
committed state only after its process is gone, so a run can never race its own verdict.

External code is untrusted, so a target refuses to exist on a runner that is not approved for it.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import JsonValue

from moody_blues.agents.policies import mission_prompt
from moody_blues.agents.tooling import agent_tool_specs
from moody_blues.contracts.adapter import (
    ADAPTER_PROTOCOL,
    MAX_AGENT_MESSAGE_BYTES,
    MAX_STDERR_EXCERPT_CHARS,
    AdapterEnvironment,
    AdapterEvent,
    AdapterEventKind,
    AdapterExit,
    AdapterLimits,
    Capability,
    ExecutionContext,
    ExternalAgentRecord,
    Scope,
    TaskSpec,
    ToolDefinition,
)
from moody_blues.contracts.agent import AgentBudget, AgentTrajectory, ExternalEvidenceSource
from moody_blues.contracts.common import ErrorCategory, ErrorDetail
from moody_blues.contracts.inference import ChatMessage, ToolSpec
from moody_blues.contracts.sandbox import SandboxLimits, SandboxRequest
from moody_blues.contracts.scenario import Scenario
from moody_blues.contracts.world import ToolName, ToolResponse
from moody_blues.experiments.budget import SpendPort, worst_case_run_tokens
from moody_blues.experiments.target import TargetRequest, TargetResult
from moody_blues.external.bundle import AgentBundle
from moody_blues.external.driver import AdapterDriver, DriverOutcome, InferenceBroker
from moody_blues.sandbox.base import SandboxError
from moody_blues.sandbox.session import SandboxSession, SessionRunner
from moody_blues.services.agent_world_runner import build_report, observe_world
from moody_blues.world.engine import World

log = logging.getLogger("moody_blues.external")

_SCOPE_TOOLS: dict[Scope, frozenset[str]] = {
    Scope.CRM_READ: frozenset({ToolName.GET_CUSTOMER.value, ToolName.SEARCH_CUSTOMERS.value}),
    Scope.CRM_WRITE: frozenset({ToolName.CREATE_CUSTOMER.value}),
}
_FINISH_LINE = "When you are finished, return your final result."
_NOT_CHARGED = "no model was used through the host; nothing was charged"


@dataclass(frozen=True, slots=True)
class LiveInference:
    """A broker plus the ledger that pays for it. Only a live broker needs one."""

    broker: InferenceBroker
    ledger: SpendPort | None


def _granted_specs(bundle: AgentBundle) -> list[ToolSpec]:
    """The manifest's scopes against the host's tools, never the other way round."""
    allowed = {tool for scope in bundle.manifest.scopes for tool in _SCOPE_TOOLS[scope]}
    return [s for s in agent_tool_specs() if s.name in allowed]


def _opaque_scenario_ref(run_id: str, scenario_ref: str) -> str:
    """Stable for one run, and unrelated to the scenario's name, which describes its faults."""
    return "wrld_" + hashlib.sha256(f"{run_id}|{scenario_ref}".encode()).hexdigest()[:16]


def _exit_record(outcome: DriverOutcome) -> AdapterExit | None:
    ended = outcome.exit
    if ended is None:
        return None
    return AdapterExit(
        exit_code=ended.exit_code,
        oom_killed=ended.oom_killed,
        killed_by_host=ended.killed_by_host,
        cleaned_up=ended.cleaned_up,
        stdout_bytes=ended.stdout_bytes,
        stderr_bytes=ended.stderr_bytes,
        stderr_sha256=hashlib.sha256(ended.stderr_tail).hexdigest(),
        untrusted_stderr_excerpt=ended.stderr_tail[-MAX_STDERR_EXCERPT_CHARS:].decode(
            "utf-8", errors="replace"
        )[-MAX_STDERR_EXCERPT_CHARS:],
    )


class _NoTools:
    """A handshake reaches no tool. If one is called, the driver is broken."""

    def call(self, tool: str, arguments: Mapping[str, JsonValue]) -> ToolResponse:
        raise AssertionError(f"tool {tool} called during a handshake check")


class ExternalAgentTarget:
    def __init__(
        self,
        *,
        runner: SessionRunner,
        bundle: AgentBundle,
        sandbox_limits: SandboxLimits,
        limits: AdapterLimits | None = None,
        live: LiveInference | None = None,
    ) -> None:
        if not runner.approved_for_generated_code:
            raise ValueError("external agents need a sandbox approved by the preflight")
        if sandbox_limits.network_enabled:
            raise ValueError("external agents never run with networking")
        if live is not None and live.broker.evidence == "live_provider" and live.ledger is None:
            raise ValueError("a live model requires a spend ledger")
        self._runner = runner
        self._bundle = bundle
        self._limits = limits or AdapterLimits()
        self._live = live
        # The hard deadline trails the run, startup and exit, so the host normally decides.
        wall = (
            self._limits.startup_timeout_seconds
            + self._limits.run_timeout_seconds
            + self._limits.exit_grace_seconds
        )
        self._sandbox_limits = sandbox_limits.model_copy(
            update={"wall_timeout_seconds": min(wall, 120)}
        )

    def _capabilities(self) -> list[str]:
        declared = {c.value for c in self._bundle.manifest.capabilities}
        if self._live is None:
            declared.discard(Capability.MODEL.value)
        return sorted(declared)

    def _context(
        self, scenario: Scenario, run_id: str, deadline: float, specs: list[ToolSpec]
    ) -> ExecutionContext:
        objective = scenario.objective
        return ExecutionContext(
            run_id=run_id,
            correlation_id=f"cor_{uuid4().hex[:12]}",
            scenario_ref=_opaque_scenario_ref(run_id, scenario.ref),
            task=TaskSpec(
                mission=mission_prompt(objective, closing=_FINISH_LINE), objective=objective
            ),
            tools=[
                ToolDefinition(
                    name=s.name,
                    description=s.description,
                    parameters=s.parameters,
                    access="write" if s.name in _SCOPE_TOOLS[Scope.CRM_WRITE] else "read",
                )
                for s in specs
            ],
            scopes=[s.value for s in self._bundle.manifest.scopes],
            deadline_seconds=deadline,
            max_tool_calls=self._limits.max_tool_calls,
            capabilities=self._capabilities(),
        )

    def _reserve(self, request: TargetRequest) -> str | None:
        """Raises ``BudgetExceededError`` before anything exists, as ``AgentTarget`` does."""
        if self._live is None or self._live.ledger is None:
            return None
        broker = self._live.broker
        budget = AgentBudget(
            max_steps=broker.max_model_calls,
            max_total_tokens=broker.max_total_tokens,
            max_completion_tokens=broker.max_completion_tokens,
        )
        return self._live.ledger.reserve(
            f"external:{self._bundle.manifest.agent_id}:{request.scenario.scenario_id}",
            worst_case_tokens=worst_case_run_tokens(budget),
        )

    def _environment(self, session: SandboxSession) -> AdapterEnvironment:
        mode = session.execution_mode
        if mode not in {"docker_sandbox", "local_process_test_double"}:
            raise ValueError(f"unknown execution mode {mode}")
        return AdapterEnvironment(
            execution_mode="docker_sandbox"
            if mode == "docker_sandbox"
            else "local_process_test_double",
            session_id=session.session_id,
            image=session.image,
            image_id=session.image_id,
            network_enabled=self._sandbox_limits.network_enabled,
            memory_mb=self._sandbox_limits.memory_mb,
            pids_limit=self._sandbox_limits.pids_limit,
        )

    def _trajectory(
        self,
        request: TargetRequest,
        outcome: DriverOutcome,
        context: ExecutionContext,
        wall_ms: int,
        error: ErrorDetail | None,
    ) -> AgentTrajectory:
        manifest = self._bundle.manifest
        return AgentTrajectory(
            config=request.config,
            policy_version=f"external:{manifest.agent_id}@{manifest.version}",
            policy_sha256=self._bundle.sha256,
            budget=AgentBudget(
                max_tool_calls=self._limits.max_tool_calls,
                max_wall_seconds=self._limits.run_timeout_seconds,
            ),
            tool_names=[t.name for t in context.tools],
            messages=[ChatMessage(role="user", content=context.task.mission)],
            steps=outcome.model_steps,
            tool_calls=outcome.tool_calls,
            claim=outcome.claim,
            claim_outcome=outcome.claim_outcome,
            invalid_claim_attempts=0,
            termination=outcome.termination,
            error=error,
            tokens=outcome.tokens,
            inference_latency_ms=outcome.inference_ms,
            wall_ms=wall_ms,
        )

    def _record(
        self,
        outcome: DriverOutcome,
        environment: AdapterEnvironment | None,
        context: ExecutionContext,
        wall_ms: int,
    ) -> ExternalAgentRecord:
        manifest = self._bundle.manifest
        return ExternalAgentRecord(
            agent_id=manifest.agent_id,
            name=manifest.name,
            agent_version=manifest.version,
            declared_target_type=manifest.target_type,
            protocol=ADAPTER_PROTOCOL,
            sdk_version=outcome.hello.agent.sdk_version if outcome.hello else None,
            manifest_sha256=self._bundle.manifest_sha256,
            bundle_sha256=self._bundle.sha256,
            environment=environment,
            limits=self._limits,
            granted_tools=[t.name for t in context.tools],
            granted_scopes=context.scopes,
            model_calls=len(outcome.model_steps),
            startup_ms=outcome.startup_ms,
            wall_ms=wall_ms,
            exit=_exit_record(outcome),
            rejection=outcome.rejection,
            rejected_line_sha256=outcome.rejected_line_sha256,
            final=outcome.final,
            unknown_evidence_refs=outcome.unknown_evidence_refs,
            transcript_sha256=outcome.transcript_sha256,
            transcript_lines=outcome.transcript_lines,
            events=outcome.events,
        )

    def _evidence(self, outcome: DriverOutcome) -> ExternalEvidenceSource:
        """Only a model call the host itself brokered can make this an LLM run."""
        if self._live is None or not outcome.model_steps:
            return "external_scripted"
        return self._live.broker.evidence

    def _settle(self, entry: str | None, outcome: DriverOutcome) -> tuple[float | None, str]:
        if self._live is None or self._live.ledger is None or entry is None:
            return None, _NOT_CHARGED
        cost = round(self._live.ledger.settle(entry, outcome.tokens), 6)
        return cost, "estimate at assumed ceiling prices; not a provider invoice"

    def _drive(
        self,
        request: TargetRequest,
        world: World,
        context: ExecutionContext,
        specs: list[ToolSpec],
        limits: AdapterLimits,
    ) -> tuple[DriverOutcome, AdapterEnvironment | None, ErrorDetail | None]:
        try:
            session = self._runner.open_session(
                SandboxRequest(code=self._bundle.bootstrap, limits=self._sandbox_limits),
                max_line_bytes=MAX_AGENT_MESSAGE_BYTES,
            )
        except SandboxError as exc:
            never = DriverOutcome(
                events=[
                    AdapterEvent(
                        seq=1,
                        elapsed_ms=0,
                        kind=AdapterEventKind.REGISTERED,
                        code=self._bundle.manifest.agent_id,
                    )
                ]
            )
            return never, None, exc.detail
        environment = self._environment(session)
        driver = AdapterDriver(
            session=session,
            port=world.gateway,
            manifest=self._bundle.manifest,
            context=context,
            limits=limits,
            specs=specs,
            bundle_frame=self._bundle.frame,
            broker=self._live.broker if self._live is not None else None,
            cancel=request.cancel,
        )
        outcome = driver.run()
        error = None
        if outcome.exit is not None and not outcome.exit.cleaned_up:
            error = ErrorDetail(
                category=ErrorCategory.SANDBOX_RUNTIME,
                message=f"container of {session.session_id} was not removed",
            )
        return outcome, environment, error

    def check_handshake(self, scenario: Scenario) -> DriverOutcome:
        """Start the agent in its sandbox and shake hands. No world exists, and nothing runs."""
        specs = _granted_specs(self._bundle)
        run_id = f"run_{uuid4().hex[:12]}"
        session = self._runner.open_session(
            SandboxRequest(code=self._bundle.bootstrap, limits=self._sandbox_limits),
            max_line_bytes=MAX_AGENT_MESSAGE_BYTES,
        )
        return AdapterDriver(
            session=session,
            port=_NoTools(),
            manifest=self._bundle.manifest,
            context=self._context(scenario, run_id, self._limits.run_timeout_seconds, specs),
            limits=self._limits,
            specs=specs,
            bundle_frame=self._bundle.frame,
        ).run(handshake_only=True)

    def run(self, request: TargetRequest) -> TargetResult:
        manifest = self._bundle.manifest
        specs = _granted_specs(self._bundle)
        run_id = f"run_{uuid4().hex[:12]}"
        entry = self._reserve(request)
        started_at = datetime.now(UTC)
        deadline = min(self._limits.run_timeout_seconds, request.max_wall_seconds)
        limits = self._limits.model_copy(update={"run_timeout_seconds": deadline})
        context = self._context(request.scenario, run_id, deadline, specs)
        world = World(request.scenario, root_dir=request.world_root)
        # Kept, so that recovery can read committed state if this process dies. The coordinator
        # removes resolved worlds when the experiment closes.
        try:
            outcome, environment, error = self._drive(request, world, context, specs, limits)
            observed = observe_world(world, outcome.claim)
        finally:
            world.close(remove=False)
        wall_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        outcome.events.append(
            AdapterEvent(
                seq=len(outcome.events) + 1,
                elapsed_ms=wall_ms,
                kind=AdapterEventKind.ORACLE_VERIFIED,
                code=observed.oracle.verdict.value,
            )
        )
        log.info(
            "adapter_event",
            extra={
                "kind": AdapterEventKind.ORACLE_VERIFIED.value,
                "run_id": run_id,
                "code": observed.oracle.verdict.value,
            },
        )
        record = self._record(outcome, environment, context, wall_ms)
        trajectory = self._trajectory(request, outcome, context, wall_ms, error)
        cost, note = self._settle(entry, outcome)
        evidence = self._evidence(outcome)
        used_model = evidence != "external_scripted" and self._live is not None
        provider = self._live.broker.provider if used_model and self._live else None
        model = self._live.broker.model if used_model and self._live else None
        report = build_report(
            request.scenario,
            world.world_id,
            trajectory,
            observed,
            run_id=run_id,
            started_at=started_at,
            evidence=evidence,
            provider=provider,
            model=model,
            cost=cost,
            cost_note=note,
            external=record,
        )
        return TargetResult(
            run_id=run_id,
            target_kind="external_agent",
            evidence_source=evidence,
            executor=manifest.agent_id,
            provider=provider,
            requested_model=model,
            reported_models=report.reported_models,
            policy_version=trajectory.policy_version,
            policy_sha256=trajectory.policy_sha256,
            termination=outcome.termination.value,
            run_outcome=report.assessment.outcome.value,
            error=error,
            claim=outcome.claim,
            world_id=world.world_id,
            world_trace=report.world_trace,
            final_state=report.final_state,
            committed_changes=report.committed_changes,
            oracle=report.oracle,
            tokens=outcome.tokens if outcome.model_steps else None,
            inference_latency_ms=outcome.inference_ms if outcome.model_steps else None,
            wall_ms=wall_ms,
            estimated_cost_usd=cost,
            cost_note=note,
            full_report=report.model_dump(mode="json"),
            external=record,
        )
