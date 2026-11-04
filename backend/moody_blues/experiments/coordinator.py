"""The trusted coordinator: the only code that acts on behalf of an experiment.

Each iteration runs the experiment code in a new disposable sandbox, then validates what it
printed, then performs the one authorized operation, then feeds a sanitized observation to the
next sandbox. The sandbox has no network, no mounts and no secrets. All it can do is print one
JSON document and exit, and only a process exit lets anything happen. Therefore a sandbox step
itself has no effects on the world; the only side effects are target runs, and those happen here.

Failure rules:

- An experiment that misbehaves ends deterministically; output is never repaired or re-asked.
- A sandbox step may be retried on infrastructure errors, because it cannot have had effects.
- A target run is never retried. If one does not report back, the experiment ends UNCERTAIN.
- The journal is written ahead of every effect, and ``completed`` is only ever written after
  the evidence is on disk. See ``recovery.py`` for what happens when this process dies.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from moody_blues.contracts.agent import AgentConfigName, TerminationReason
from moody_blues.contracts.common import ExecutionStatus
from moody_blues.contracts.experiment_evidence import (
    TERMINAL_STATES,
    ActionDecision,
    AuthorizedRun,
    CommittedSummary,
    ExperimentAuthorship,
    ExperimentEvidence,
    ExperimentLimits,
    ExperimentSpec,
    ExperimentState,
    ExperimentTermination,
    OutcomeClass,
    ResourceUsage,
    SandboxExecutionRecord,
    SandboxSupplied,
    StepRecord,
    TargetObserved,
    TargetRunEvidence,
    UnresolvedTargetRun,
)
from moody_blues.contracts.oracle import Verdict
from moody_blues.contracts.protocol import (
    MAX_EXPERIMENT_CODE_BYTES,
    MAX_STEP_INPUT_BYTES,
    PROTOCOL_VERSION,
    ApprovedCatalog,
    ExperimentConclusion,
    FinishExperiment,
    InspectionObservation,
    InspectionSection,
    InspectObservation,
    ProtocolRejection,
    RejectionCode,
    RunObservation,
    RunTargetAgent,
    StepInput,
)
from moody_blues.contracts.sandbox import SandboxLimits, SandboxRequest, SandboxResult
from moody_blues.contracts.scenario import FaultKind
from moody_blues.experiments.budget import BudgetExceededError
from moody_blues.experiments.harness import build_step_program, inspect_run, observe_run
from moody_blues.experiments.protocol import (
    APPROVED_SCENARIOS,
    AuthorizedTargetRun,
    authorize_run,
    parse_action,
)
from moody_blues.experiments.recovery import inspect_worlds
from moody_blues.experiments.target import TargetPort, TargetRequest, TargetResult
from moody_blues.experiments.workspace import (
    EVIDENCE,
    ExperimentWorkspace,
    atomic_write,
    sha256_text,
)
from moody_blues.sandbox.base import SandboxError, SandboxRunner, SandboxUnavailableError
from moody_blues.world.scenarios import load_scenario

log = logging.getLogger("moody_blues.experiments")

_ALLOWED_TRANSITIONS: dict[ExperimentState, frozenset[ExperimentState]] = {
    ExperimentState.CREATED: frozenset({ExperimentState.SANDBOX_RUNNING}),
    ExperimentState.SANDBOX_RUNNING: frozenset({ExperimentState.VALIDATING}),
    ExperimentState.VALIDATING: frozenset(
        {ExperimentState.TARGET_RUNNING, ExperimentState.SANDBOX_RUNNING}
    ),
    ExperimentState.TARGET_RUNNING: frozenset({ExperimentState.SANDBOX_RUNNING}),
    ExperimentState.FINALIZING: TERMINAL_STATES,
}

# Agent terminations that mean the run stopped without the agent finishing its task. They are
# target-side outcomes: the infrastructure worked and the evidence is complete.
_TARGET_SHORTFALLS = {
    TerminationReason.NO_FINAL_CLAIM.value,
    TerminationReason.MAX_STEPS.value,
    TerminationReason.TOKEN_BUDGET.value,
    TerminationReason.WALL_TIMEOUT.value,
    TerminationReason.INVALID_MODEL_RESPONSE.value,
}


class InvalidTransitionError(RuntimeError):
    pass


def check_transition(current: ExperimentState, new: ExperimentState) -> None:
    """Terminal states are final; any live state may go to FINALIZING; the rest is listed."""
    if current in TERMINAL_STATES:
        raise InvalidTransitionError(f"{current.value} is terminal")
    if new is ExperimentState.FINALIZING or new in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        return
    raise InvalidTransitionError(f"{current.value} -> {new.value}")


@dataclass(frozen=True, slots=True)
class _Stop:
    status: ExperimentState
    termination: ExperimentTermination
    classes: tuple[OutcomeClass, ...] = ()
    detail: str | None = None


@dataclass(slots=True)
class _Session:
    experiment_id: str
    spec: ExperimentSpec
    workspace: ExperimentWorkspace
    code_sha256: str
    created_at: datetime
    started: float
    cancel: Event | None
    state: ExperimentState = ExperimentState.CREATED
    steps: list[StepRecord] = field(default_factory=list[StepRecord])
    runs: list[TargetRunEvidence] = field(default_factory=list[TargetRunEvidence])
    observations: list[RunObservation | InspectionObservation] = field(
        default_factory=list[RunObservation | InspectionObservation]
    )
    sandbox_supplied: SandboxSupplied | None = None
    unresolved: list[UnresolvedTargetRun] = field(default_factory=list[UnresolvedTargetRun])
    target_in_flight: tuple[str, str] | None = None  # (run_ref, scenario_id)

    @property
    def cancelled(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()


def _sandbox_record(result: SandboxResult, attempt: int) -> SandboxExecutionRecord:
    return SandboxExecutionRecord(
        sandbox_run_id=result.run_id,
        attempt=attempt,
        status=result.status,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        oom_killed=result.oom_killed,
        cleaned_up=result.cleaned_up,
        stdout_bytes=result.stdout_bytes,
        stderr_bytes=result.stderr_bytes,
        stdout_truncated=result.stdout_truncated,
        output_complete=result.output_complete,
        stdout_sha256=sha256_text(result.stdout),
        stderr_excerpt=result.stderr[-500:],
        image=result.image,
        image_id=result.image_id,
        network_enabled=result.limits.network_enabled,
    )


def _sandbox_stop(result: SandboxResult) -> _Stop | None:
    """Why a finished sandbox step must end the experiment, if it must."""
    failure = (OutcomeClass.SANDBOX_FAILURE,)
    if not result.cleaned_up:
        return _Stop(
            ExperimentState.FAILED,
            ExperimentTermination.SANDBOX_CLEANUP_FAILED,
            failure,
            f"container of {result.run_id} was not removed",
        )
    match result.status:
        case ExecutionStatus.CANCELLED:
            return _Stop(
                ExperimentState.CANCELLED,
                ExperimentTermination.CANCELLED,
                (OutcomeClass.CANCELLATION,),
            )
        case ExecutionStatus.TIMED_OUT:
            return _Stop(
                ExperimentState.FAILED,
                ExperimentTermination.SANDBOX_TIMEOUT,
                failure,
                f"step exceeded {result.limits.wall_timeout_seconds}s and was killed",
            )
        case ExecutionStatus.SUCCEEDED:
            return None
        case _ if result.oom_killed:
            return _Stop(ExperimentState.FAILED, ExperimentTermination.SANDBOX_OOM, failure)
        case _:
            return _Stop(
                ExperimentState.FAILED,
                ExperimentTermination.SANDBOX_EXIT_NONZERO,
                failure,
                f"experiment code exited with {result.exit_code}",
            )


class ExperimentCoordinator:
    def __init__(
        self,
        *,
        sandbox: SandboxRunner,
        target: TargetPort,
        root: Path,
        sandbox_limits: SandboxLimits,
        limits: ExperimentLimits | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if sandbox_limits.network_enabled:
            raise ValueError("experiments never run with networking")
        self._sandbox = sandbox
        self._target = target
        self._root = root
        self._sandbox_limits = sandbox_limits
        self._limits = limits or ExperimentLimits()
        self._monotonic = monotonic

    # --- lifecycle ----------------------------------------------------------------------

    def run(self, spec: ExperimentSpec, *, cancel: Event | None = None) -> ExperimentEvidence:
        experiment_id = f"exp_{uuid4().hex[:12]}"
        session = _Session(
            experiment_id=experiment_id,
            spec=spec,
            workspace=ExperimentWorkspace(self._root, experiment_id),
            code_sha256=sha256_text(spec.code),
            created_at=datetime.now(UTC),
            started=self._monotonic(),
            cancel=cancel,
        )
        session.workspace.journal(
            "experiment_created",
            {
                "experiment_id": experiment_id,
                "parent_investigation_id": spec.parent_investigation_id,
                "label": spec.label,
                "code_sha256": session.code_sha256,
                "limits": self._limits.model_dump(mode="json"),
                "protocol": PROTOCOL_VERSION,
                "created_at": session.created_at.isoformat(),
            },
        )
        try:
            stop = self._loop(session)
        except Exception as exc:
            log.exception("coordinator_error", extra={"experiment_id": experiment_id})
            stop = self._crash_stop(session, exc)
        return self._finish(session, stop)

    def _crash_stop(self, session: _Session, exc: Exception) -> _Stop:
        detail = f"{type(exc).__name__} in state {session.state.value}"
        if session.target_in_flight is None:
            return _Stop(
                ExperimentState.FAILED,
                ExperimentTermination.COORDINATOR_ERROR,
                (OutcomeClass.COORDINATOR_FAILURE,),
                detail,
            )
        run_ref, scenario_id = session.target_in_flight
        found = inspect_worlds(session.workspace.worlds_dir, scenario_id)
        session.unresolved.append(
            UnresolvedTargetRun(
                run_ref=run_ref,
                scenario_id=scenario_id,
                world_found=found is not None,
                committed_new_customer_ids=found,
                note="the target run raised before reporting; not retried",
            )
        )
        return _Stop(
            ExperimentState.UNCERTAIN,
            ExperimentTermination.COORDINATOR_ERROR,
            (OutcomeClass.COORDINATOR_FAILURE,),
            detail,
        )

    def _transition(self, session: _Session, new: ExperimentState) -> None:
        check_transition(session.state, new)
        session.state = new
        session.workspace.journal("state", {"state": new.value})

    def _remaining(self, session: _Session) -> float:
        elapsed = self._monotonic() - session.started
        return self._limits.max_runtime_seconds - elapsed

    # --- the loop -----------------------------------------------------------------------

    def _loop(self, session: _Session) -> _Stop:
        if len(session.spec.code.encode()) > MAX_EXPERIMENT_CODE_BYTES:
            return _Stop(
                ExperimentState.REJECTED,
                ExperimentTermination.ACTION_REJECTED,
                (OutcomeClass.EXPERIMENT_VALIDATION_FAILURE,),
                f"experiment code exceeds {MAX_EXPERIMENT_CODE_BYTES} bytes",
            )
        for step in range(1, self._limits.max_steps + 1):
            if session.cancelled:
                return _Stop(
                    ExperimentState.CANCELLED,
                    ExperimentTermination.CANCELLED,
                    (OutcomeClass.CANCELLATION,),
                )
            if self._remaining(session) <= 0:
                return self._runtime_stop()
            stop = self._step(session, step)
            if stop is not None:
                return stop
        return _Stop(
            ExperimentState.BUDGET_EXHAUSTED,
            ExperimentTermination.MAX_STEPS,
            (OutcomeClass.BUDGET_EXHAUSTION,),
            f"no finish action within {self._limits.max_steps} steps",
        )

    def _runtime_stop(self) -> _Stop:
        return _Stop(
            ExperimentState.BUDGET_EXHAUSTED,
            ExperimentTermination.MAX_RUNTIME,
            (OutcomeClass.BUDGET_EXHAUSTION,),
            f"cumulative runtime limit of {self._limits.max_runtime_seconds}s reached",
        )

    def _step_input(self, session: _Session, step: int) -> str:
        return StepInput(
            experiment_id=session.experiment_id,
            step=step,
            max_steps=self._limits.max_steps,
            target_runs_remaining=self._limits.max_target_runs - len(session.runs),
            catalog=ApprovedCatalog(
                scenarios=list(APPROVED_SCENARIOS),
                configs=[c.value for c in AgentConfigName],
                fault_kinds=[k.value for k in FaultKind],
                fault_error_codes=["timeout", "internal_error", "unavailable"],
            ),
            observations=session.observations,
        ).model_dump_json()

    def _step(self, session: _Session, step: int) -> _Stop | None:
        started_at = datetime.now(UTC)
        step_input = self._step_input(session, step)
        if len(step_input.encode()) > MAX_STEP_INPUT_BYTES:
            return _Stop(
                ExperimentState.FAILED,
                ExperimentTermination.COORDINATOR_ERROR,
                (OutcomeClass.COORDINATOR_FAILURE,),
                f"step input exceeds {MAX_STEP_INPUT_BYTES} bytes",
            )
        input_sha = sha256_text(step_input)
        self._transition(session, ExperimentState.SANDBOX_RUNNING)
        session.workspace.journal("sandbox_step_started", {"step": step, "input_sha256": input_sha})
        records, result, stop = self._run_sandbox(session, step_input)

        def close(
            *,
            decision: ActionDecision,
            proposed: str | None = None,
            authorized: dict[str, object] | None = None,
            rejection: ProtocolRejection | None = None,
            observation: str | None = None,
        ) -> None:
            record = StepRecord.model_validate(
                {
                    "step": step,
                    "started_at": started_at,
                    "finished_at": datetime.now(UTC),
                    "step_input_sha256": input_sha,
                    "sandbox": records,
                    "proposed_action_sha256": sha256_text(proposed) if proposed else None,
                    "proposed_action_excerpt": proposed[:1_000] if proposed else None,
                    "decision": decision,
                    "authorized_action": authorized,
                    "rejection": rejection,
                    "observation_sha256": sha256_text(observation) if observation else None,
                }
            )
            session.steps.append(record)
            session.workspace.journal("step_completed", record.model_dump(mode="json"))

        if stop is not None or result is None:
            close(decision=ActionDecision.NOT_EVALUATED)
            return stop

        self._transition(session, ExperimentState.VALIDATING)
        proposed = result.stdout
        parsed = parse_action(result)
        if isinstance(parsed, ProtocolRejection):
            close(decision=ActionDecision.REJECTED, proposed=proposed, rejection=parsed)
            return self._rejected(parsed)

        rejection: ProtocolRejection | None
        match parsed:
            case FinishExperiment():
                session.sandbox_supplied = SandboxSupplied(
                    conclusion=ExperimentConclusion(parsed.conclusion), summary=parsed.summary
                )
                close(
                    decision=ActionDecision.AUTHORIZED,
                    proposed=proposed,
                    authorized=parsed.model_dump(mode="json"),
                )
                return _Stop(ExperimentState.COMPLETED, ExperimentTermination.FINISH_ACTION)
            case InspectObservation():
                rejection, observation = self._inspect(session, parsed)
                if rejection is not None or observation is None:
                    close(decision=ActionDecision.REJECTED, proposed=proposed, rejection=rejection)
                    return self._rejected(rejection)
                session.observations.append(observation)
                close(
                    decision=ActionDecision.AUTHORIZED,
                    proposed=proposed,
                    authorized=parsed.model_dump(mode="json"),
                    observation=observation.model_dump_json(),
                )
                return None
            case RunTargetAgent():
                authorized = self._authorize(session, parsed)
                if isinstance(authorized, ProtocolRejection):
                    close(decision=ActionDecision.REJECTED, proposed=proposed, rejection=authorized)
                    return self._rejected(authorized)
                stop, observation = self._execute_target(session, authorized)
                close(
                    decision=ActionDecision.AUTHORIZED,
                    proposed=proposed,
                    authorized=parsed.model_dump(mode="json"),
                    observation=observation.model_dump_json() if observation else None,
                )
                return stop

    @staticmethod
    def _rejected(rejection: ProtocolRejection | None) -> _Stop:
        detail = None if rejection is None else f"{rejection.code.value}: {rejection.detail}"
        return _Stop(
            ExperimentState.REJECTED,
            ExperimentTermination.ACTION_REJECTED,
            (OutcomeClass.EXPERIMENT_VALIDATION_FAILURE,),
            detail,
        )

    # --- sandbox ------------------------------------------------------------------------

    def _run_sandbox(
        self, session: _Session, step_input: str
    ) -> tuple[list[SandboxExecutionRecord], SandboxResult | None, _Stop | None]:
        records: list[SandboxExecutionRecord] = []
        program = build_step_program(session.spec.code, step_input)
        for attempt in range(1, self._limits.sandbox_infra_retries + 2):
            timeout = min(self._limits.step_timeout_seconds, self._remaining(session))
            if timeout <= 0:
                return records, None, self._runtime_stop()
            limits = self._sandbox_limits.model_copy(update={"wall_timeout_seconds": timeout})
            try:
                result = self._sandbox.run(
                    SandboxRequest(code=program, limits=limits), cancel=session.cancel
                )
            except SandboxUnavailableError as exc:
                # Safe to repeat: the code did not run, and a step has no world effects.
                session.workspace.journal(
                    "sandbox_unavailable", {"attempt": attempt, "message": exc.detail.message}
                )
                if attempt > self._limits.sandbox_infra_retries:
                    return records, None, self._infra_stop(exc)
                continue
            except SandboxError as exc:
                return records, None, self._infra_stop(exc)
            records.append(_sandbox_record(result, attempt))
            return records, result, _sandbox_stop(result)
        raise AssertionError("unreachable: the retry loop always returns")  # pragma: no cover

    @staticmethod
    def _infra_stop(exc: SandboxError) -> _Stop:
        return _Stop(
            ExperimentState.FAILED,
            ExperimentTermination.SANDBOX_INFRASTRUCTURE,
            (OutcomeClass.SANDBOX_FAILURE,),
            exc.detail.message[:500],
        )

    # --- authorized operations ----------------------------------------------------------

    def _authorize(
        self, session: _Session, action: RunTargetAgent
    ) -> AuthorizedTargetRun | ProtocolRejection:
        if action.scenario_id not in APPROVED_SCENARIOS:
            return ProtocolRejection(
                code=RejectionCode.UNSUPPORTED_SCENARIO, detail="scenario is not approved"
            )
        return authorize_run(
            action,
            scenario=load_scenario(action.scenario_id),
            runs_done=len(session.runs),
            max_runs=self._limits.max_target_runs,
        )

    @staticmethod
    def _inspect(
        session: _Session, action: InspectObservation
    ) -> tuple[ProtocolRejection | None, InspectionObservation | None]:
        run = next((r for r in session.runs if r.run_ref == action.run_ref), None)
        if run is None:
            return (
                ProtocolRejection(
                    code=RejectionCode.UNKNOWN_RUN_REF, detail="no such run in this experiment"
                ),
                None,
            )
        return None, inspect_run(run, InspectionSection(action.section))

    def _execute_target(
        self, session: _Session, authorized: AuthorizedTargetRun
    ) -> tuple[_Stop | None, RunObservation | None]:
        scenario = authorized.scenario
        config = AgentConfigName(authorized.config)
        remaining = self._remaining(session)
        if remaining <= 0:
            return self._runtime_stop(), None
        run_ref = f"trun_{len(session.runs) + 1}"
        grant = AuthorizedRun(
            scenario_id=scenario.scenario_id,
            scenario_version=scenario.version,
            scenario_sha256=sha256_text(scenario.model_dump_json()),
            config=config,
            fault_source="scenario"
            if authorized.fault_source == "scenario"
            else "experiment_selection",
            faults=list(scenario.faults),
        )
        # Write-ahead: from here until target_run_finished, world effects may exist.
        session.workspace.journal(
            "target_run_intent", {"run_ref": run_ref, "authorized": grant.model_dump(mode="json")}
        )
        self._transition(session, ExperimentState.TARGET_RUNNING)
        session.target_in_flight = (run_ref, scenario.scenario_id)
        started_at = datetime.now(UTC)
        try:
            result = self._target.run(
                TargetRequest(
                    scenario=scenario,
                    config=config,
                    world_root=session.workspace.worlds_dir,
                    max_wall_seconds=remaining,
                    cancel=session.cancel,
                )
            )
        except BudgetExceededError as exc:
            # Raised by the reservation, before the run began: nothing happened.
            session.target_in_flight = None
            session.workspace.journal(
                "target_run_not_started", {"run_ref": run_ref, "reason": exc.detail.message}
            )
            return (
                _Stop(
                    ExperimentState.BUDGET_EXHAUSTED,
                    ExperimentTermination.SPEND_LIMIT,
                    (OutcomeClass.BUDGET_EXHAUSTION,),
                    exc.detail.message[:500],
                ),
                None,
            )
        run = self._record_run(session, run_ref, grant, started_at, result)
        session.runs.append(run)
        session.target_in_flight = None
        observation = observe_run(run)
        session.observations.append(observation)
        return self._run_stop(run), observation

    @staticmethod
    def _record_run(
        session: _Session,
        run_ref: str,
        grant: AuthorizedRun,
        started_at: datetime,
        result: TargetResult,
    ) -> TargetRunEvidence:
        name = f"{run_ref}-{result.run_id}.json"
        report_sha = atomic_write(
            session.workspace.runs_dir / name, json.dumps(result.full_report, indent=2) + "\n"
        )
        seeds = set(result.oracle.observation.seed_customer_ids)
        faults_delivered = sum(1 for t in result.world_trace if t.fault_injected is not None)
        run = TargetRunEvidence(
            run_ref=run_ref,
            run_id=result.run_id,
            target_kind=result.target_kind,
            evidence_source=result.evidence_source,
            executor=result.executor,
            provider=result.provider,
            requested_model=result.requested_model,
            reported_models=result.reported_models,
            policy_version=result.policy_version,
            policy_sha256=result.policy_sha256,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            authorized=grant,
            target_observed=TargetObserved(
                tool_trace=result.world_trace,
                faults_delivered=faults_delivered,
                claim=result.claim,
                termination=result.termination,
            ),
            committed=CommittedSummary(
                world_id=result.world_id,
                customers=result.final_state,
                changes=result.committed_changes,
                new_customer_ids=[
                    c.customer_id for c in result.final_state if c.customer_id not in seeds
                ],
            ),
            oracle=result.oracle,
            error=result.error,
            tokens=result.tokens,
            inference_latency_ms=result.inference_latency_ms,
            wall_ms=result.wall_ms,
            estimated_cost_usd=result.estimated_cost_usd,
            cost_note=result.cost_note,
            report_path=f"runs/{name}",
            report_sha256=report_sha,
        )
        session.workspace.journal("target_run_finished", run.model_dump(mode="json"))
        return run

    @staticmethod
    def _run_stop(run: TargetRunEvidence) -> _Stop | None:
        """A provider failure or cancellation ends the experiment. Evidence stays valid: the
        Oracle still evaluated whatever the world really contains."""
        termination = run.target_observed.termination
        if termination == TerminationReason.PROVIDER_ERROR.value:
            message = run.error.message if run.error is not None else "provider error"
            return _Stop(
                ExperimentState.FAILED,
                ExperimentTermination.PROVIDER_ERROR,
                (OutcomeClass.PROVIDER_FAILURE,),
                message[:500],
            )
        if termination == TerminationReason.CANCELLED.value:
            return _Stop(
                ExperimentState.CANCELLED,
                ExperimentTermination.CANCELLED,
                (OutcomeClass.CANCELLATION,),
            )
        return None

    # --- closing ------------------------------------------------------------------------

    @staticmethod
    def _classify(session: _Session, stop: _Stop) -> list[OutcomeClass]:
        """From trusted records only. Nothing the sandbox said is consulted."""
        classes = list(stop.classes)
        for run in session.runs:
            if run.target_observed.faults_delivered > 0:
                classes.append(OutcomeClass.EXPECTED_ENVIRONMENTAL_FAULT)
            if run.oracle.verdict is Verdict.VIOLATION:
                classes.append(OutcomeClass.ORACLE_VIOLATION)
            if run.target_observed.termination in _TARGET_SHORTFALLS:
                classes.append(OutcomeClass.TARGET_AGENT_FAILURE)
        return sorted(set(classes))

    def _usage(self, session: _Session) -> ResourceUsage:
        executions = [e for s in session.steps for e in s.sandbox]
        costs = [r.estimated_cost_usd for r in session.runs if r.estimated_cost_usd is not None]
        tokens = [r.tokens for r in session.runs if r.tokens is not None]
        return ResourceUsage(
            sandbox_executions=len(executions),
            sandbox_ms=sum(e.duration_ms for e in executions),
            target_runs=len(session.runs),
            total_tokens=sum(t.total_tokens for t in tokens),
            tokens_complete=all(t.complete for t in tokens),
            estimated_cost_usd=round(sum(costs), 6) if costs else None,
            wall_ms=int((self._monotonic() - session.started) * 1000),
        )

    def _finish(self, session: _Session, stop: _Stop) -> ExperimentEvidence:
        self._transition(session, ExperimentState.FINALIZING)
        check_transition(session.state, stop.status)
        session.state = stop.status
        evidence = ExperimentEvidence(
            experiment_id=session.experiment_id,
            parent_investigation_id=session.spec.parent_investigation_id,
            label=session.spec.label,
            authorship=ExperimentAuthorship.DEVELOPER_SCRIPT,
            code_sha256=session.code_sha256,
            protocol=PROTOCOL_VERSION,
            limits=self._limits,
            status=stop.status,
            termination=stop.termination,
            classifications=self._classify(session, stop),
            detail=stop.detail,
            created_at=session.created_at,
            finished_at=datetime.now(UTC),
            steps=session.steps,
            target_runs=session.runs,
            unresolved_target_runs=session.unresolved,
            sandbox_supplied=session.sandbox_supplied,
            usage=self._usage(session),
        )
        workspace = session.workspace
        # Evidence first: the journal must never call an experiment finished before it is.
        digest = atomic_write(
            workspace.directory / EVIDENCE, evidence.model_dump_json(indent=2) + "\n"
        )
        workspace.journal(
            "experiment_finished",
            {
                "status": stop.status.value,
                "termination": stop.termination.value,
                "evidence_sha256": digest,
            },
        )
        if not session.unresolved:
            shutil.rmtree(workspace.worlds_dir, ignore_errors=True)
        workspace.release()
        return evidence
