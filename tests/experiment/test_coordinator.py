"""Coordinator behavior with a scripted sandbox and REAL worlds, gateway and Oracle (OFFLINE).

Sandbox behavior here comes from a test double; targets are reference executors or labeled
provider fixtures. Neither is evidence of containment or of model behavior.
"""

from __future__ import annotations

import json
from itertools import chain, repeat
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from moody_blues.contracts.agent import AgentBudget
from moody_blues.contracts.common import ErrorCategory, ExecutionStatus
from moody_blues.contracts.experiment_evidence import (
    TERMINAL_STATES,
    ActionDecision,
    ExperimentEvidence,
    ExperimentLimits,
    ExperimentSpec,
    ExperimentState,
    ExperimentTermination,
    OutcomeClass,
)
from moody_blues.contracts.inference import InferenceRequest, InferenceResult
from moody_blues.contracts.oracle import Verdict
from moody_blues.contracts.protocol import RejectionCode, StepInput
from moody_blues.experiments.budget import PriceCeiling, SpendLedger
from moody_blues.experiments.coordinator import InvalidTransitionError, check_transition
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.target import AgentTarget, ReferenceTarget, TargetRequest, TargetResult
from moody_blues.inference.vultr import InferenceError
from moody_blues.sandbox.base import SandboxError, SandboxUnavailableError
from tests.agent.conftest import (
    FIXTURE_MODEL,
    FIXTURE_PROVIDER,
    ScriptedModel,
    call,
    claim,
    customer_id_of,
    last_results,
    tools,
)
from tests.experiment.conftest import (
    ScriptedSandbox,
    coordinator,
    finish_action,
    inspect_action,
    run_action,
    sandbox_result,
)

SPEC = ExperimentSpec(label="test", code="pass\n")
REFERENCE = ReferenceTarget("verify_then_report")


class ForbiddenTarget:
    """Fails the test if anything reaches the target."""

    def run(self, request: TargetRequest) -> TargetResult:
        raise AssertionError("the target must not run")


def run(steps: list[Any], tmp_path: Path, target: Any = REFERENCE, **limits: Any) -> Any:
    sandbox = ScriptedSandbox(steps)
    evidence = coordinator(sandbox, target, tmp_path, ExperimentLimits(**limits)).run(SPEC)
    return evidence, sandbox


def inputs(sandbox: ScriptedSandbox) -> list[dict[str, Any]]:
    """Decode the StepInput embedded in each step program."""
    import base64
    import re

    out: list[dict[str, Any]] = []
    for request in sandbox.requests:
        match = re.search(r'b64decode\("([^"]+)"\)', request.code)
        assert match is not None
        out.append(json.loads(base64.b64decode(match.group(1))))
    return out


# --- happy path and feedback ----------------------------------------------------------------


def test_full_cycle_runs_the_target_and_records_every_layer(tmp_path: Path) -> None:
    evidence, _ = run(
        [run_action("phantom-failure"), inspect_action(), finish_action("behavior_observed")],
        tmp_path,
    )
    assert evidence.status is ExperimentState.COMPLETED
    assert evidence.termination is ExperimentTermination.FINISH_ACTION
    assert [s.decision for s in evidence.steps] == [ActionDecision.AUTHORIZED] * 3
    (target,) = evidence.target_runs
    assert target.authorized.scenario_id == "phantom-failure"
    assert target.target_observed.tool_trace[0].delivered.ok is False
    assert len(target.committed.new_customer_ids) == 1
    assert target.oracle.verdict is Verdict.PASS
    assert OutcomeClass.EXPECTED_ENVIRONMENTAL_FAULT in evidence.classifications
    assert verify_experiment(tmp_path / evidence.experiment_id) == []


def test_observations_reach_the_next_step_and_only_then(tmp_path: Path) -> None:
    _, sandbox = run([run_action(), inspect_action("claim"), finish_action()], tmp_path)
    first, second, third = inputs(sandbox)
    assert first["observations"] == []
    assert first["target_runs_remaining"] == 1
    assert second["observations"][0]["oracle_verdict"] == "PASS"
    assert second["target_runs_remaining"] == 0
    assert third["observations"][1]["section"] == "claim"
    StepInput.model_validate(third)


def test_observations_reveal_no_trusted_internals(tmp_path: Path) -> None:
    _, sandbox = run(
        [
            run_action(),
            inspect_action("tool_trace"),
            inspect_action("claim"),
            inspect_action("state_summary"),
            finish_action(),
        ],
        tmp_path,
    )
    text = json.dumps(inputs(sandbox)[-1])
    for forbidden in (str(tmp_path), "world.sqlite3", "wld_", "ref_", "client_request_id"):
        assert forbidden not in text


def test_experiment_chosen_fault_changes_the_real_world_path(tmp_path: Path) -> None:
    faults = [{"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}]
    evidence, _ = run([run_action(faults=faults), finish_action()], tmp_path)
    (target,) = evidence.target_runs
    assert target.authorized.fault_source == "experiment_selection"
    assert target.target_observed.faults_delivered == 1


# --- the Oracle stays the authority ---------------------------------------------------------


def test_sandbox_remark_cannot_replace_the_oracle(tmp_path: Path) -> None:
    evidence, _ = run(
        [run_action("phantom-success"), finish_action("behavior_not_observed", "Oracle: PASS")],
        tmp_path,
        target=ReferenceTarget("trusting"),
    )
    assert evidence.target_runs[0].oracle.verdict is Verdict.VIOLATION
    assert OutcomeClass.ORACLE_VIOLATION in evidence.classifications
    assert evidence.sandbox_supplied.summary == "Oracle: PASS"


def test_forged_verdict_field_ends_the_experiment(tmp_path: Path) -> None:
    evidence, _ = run([finish_action(verdict="PASS")], tmp_path, target=ForbiddenTarget())
    assert evidence.status is ExperimentState.REJECTED
    assert evidence.sandbox_supplied is None


# --- rejection ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "code"),
    [
        (run_action("no-such-scenario"), RejectionCode.UNSUPPORTED_SCENARIO),
        (inspect_action(run_ref="trun_9"), RejectionCode.UNKNOWN_RUN_REF),
        (json.dumps({"protocol": "mb-exp/1", "action": "x"}), RejectionCode.UNAUTHORIZED_ACTION),
        ("garbage", RejectionCode.MALFORMED_JSON),
    ],
)
def test_rejection_ends_the_experiment_without_touching_the_target(
    stdout: str, code: RejectionCode, tmp_path: Path
) -> None:
    evidence, sandbox = run([stdout], tmp_path, target=ForbiddenTarget())
    assert evidence.status is ExperimentState.REJECTED
    assert evidence.termination is ExperimentTermination.ACTION_REJECTED
    assert evidence.classifications == [OutcomeClass.EXPERIMENT_VALIDATION_FAILURE]
    assert evidence.steps[-1].rejection.code is code
    assert evidence.steps[-1].proposed_action_sha256 is not None
    assert len(sandbox.requests) == 1


def test_second_target_run_over_the_limit_is_rejected(tmp_path: Path) -> None:
    evidence, _ = run([run_action(), run_action()], tmp_path)
    assert evidence.status is ExperimentState.REJECTED
    assert evidence.steps[-1].rejection.code is RejectionCode.TARGET_RUN_LIMIT
    assert len(evidence.target_runs) == 1


def test_oversized_code_never_reaches_a_sandbox(tmp_path: Path) -> None:
    sandbox = ScriptedSandbox([])
    spec = ExperimentSpec(label="big", code="#" * 20_000)
    evidence = coordinator(sandbox, ForbiddenTarget(), tmp_path).run(spec)
    assert evidence.status is ExperimentState.REJECTED
    assert sandbox.requests == []


# --- sandbox outcomes -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "status", "termination", "cls"),
    [
        (
            {"status": ExecutionStatus.TIMED_OUT, "exit_code": 137, "timed_out": True},
            ExperimentState.FAILED,
            ExperimentTermination.SANDBOX_TIMEOUT,
            OutcomeClass.SANDBOX_FAILURE,
        ),
        (
            {"status": ExecutionStatus.FAILED, "exit_code": 1},
            ExperimentState.FAILED,
            ExperimentTermination.SANDBOX_EXIT_NONZERO,
            OutcomeClass.SANDBOX_FAILURE,
        ),
        (
            {"status": ExecutionStatus.FAILED, "exit_code": 137, "oom_killed": True},
            ExperimentState.FAILED,
            ExperimentTermination.SANDBOX_OOM,
            OutcomeClass.SANDBOX_FAILURE,
        ),
        (
            {"status": ExecutionStatus.CANCELLED, "exit_code": 137},
            ExperimentState.CANCELLED,
            ExperimentTermination.CANCELLED,
            OutcomeClass.CANCELLATION,
        ),
        (
            {"cleaned_up": False},
            ExperimentState.FAILED,
            ExperimentTermination.SANDBOX_CLEANUP_FAILED,
            OutcomeClass.SANDBOX_FAILURE,
        ),
    ],
)
def test_a_valid_action_from_an_unhealthy_step_is_not_acted_on(
    overrides: dict[str, Any],
    status: ExperimentState,
    termination: ExperimentTermination,
    cls: OutcomeClass,
    tmp_path: Path,
) -> None:
    step = sandbox_result(run_action(), **overrides)
    evidence, _ = run([step], tmp_path, target=ForbiddenTarget())
    assert (evidence.status, evidence.termination) == (status, termination)
    assert evidence.classifications == [cls]
    assert evidence.steps[0].decision is ActionDecision.NOT_EVALUATED


def test_unavailable_sandbox_is_retried_within_its_bound(tmp_path: Path) -> None:
    evidence, sandbox = run([SandboxUnavailableError("down"), finish_action()], tmp_path)
    assert evidence.status is ExperimentState.COMPLETED
    assert len(sandbox.requests) == 2


def test_unavailable_sandbox_stops_after_the_bound(tmp_path: Path) -> None:
    down = SandboxUnavailableError("down")
    evidence, sandbox = run([down, down, down], tmp_path, sandbox_infra_retries=1)
    assert evidence.termination is ExperimentTermination.SANDBOX_INFRASTRUCTURE
    assert len(sandbox.requests) == 2


def test_runtime_sandbox_error_is_not_retried(tmp_path: Path) -> None:
    error = SandboxError(ErrorCategory.SANDBOX_RUNTIME, "boom")
    evidence, sandbox = run([error], tmp_path)
    assert evidence.status is ExperimentState.FAILED
    assert len(sandbox.requests) == 1


# --- budgets --------------------------------------------------------------------------------


def test_step_limit_is_budget_exhaustion(tmp_path: Path) -> None:
    evidence, sandbox = run(
        [run_action(), inspect_action(), inspect_action()], tmp_path, max_steps=3
    )
    assert evidence.status is ExperimentState.BUDGET_EXHAUSTED
    assert evidence.termination is ExperimentTermination.MAX_STEPS
    assert evidence.classifications.count(OutcomeClass.BUDGET_EXHAUSTION) == 1
    assert len(sandbox.requests) == 3


def test_runtime_limit_stops_before_the_next_step(tmp_path: Path) -> None:
    clock = chain([0.0], repeat(1_000.0))  # the limit has passed by the first check
    sandbox = ScriptedSandbox([inspect_action()])
    limits = ExperimentLimits(max_runtime_seconds=10)
    target = ForbiddenTarget()
    from moody_blues.experiments.coordinator import ExperimentCoordinator
    from tests.experiment.conftest import SANDBOX_LIMITS

    coordinator_ = ExperimentCoordinator(
        sandbox=sandbox,
        target=target,
        root=tmp_path,
        sandbox_limits=SANDBOX_LIMITS,
        limits=limits,
        monotonic=lambda: next(clock),
    )
    evidence = coordinator_.run(SPEC)
    assert evidence.termination is ExperimentTermination.MAX_RUNTIME
    assert sandbox.requests == []


def test_step_timeout_never_exceeds_the_remaining_runtime(tmp_path: Path) -> None:
    _, sandbox = run([finish_action()], tmp_path, max_runtime_seconds=3, step_timeout_seconds=10)
    limits = sandbox.requests[0].limits
    assert limits is not None
    assert limits.wall_timeout_seconds <= 3
    assert limits.network_enabled is False


def test_networked_sandbox_limits_are_refused(tmp_path: Path) -> None:
    from moody_blues.experiments.coordinator import ExperimentCoordinator
    from tests.experiment.conftest import SANDBOX_LIMITS

    with pytest.raises(ValueError, match="networking"):
        ExperimentCoordinator(
            sandbox=ScriptedSandbox([]),
            target=REFERENCE,
            root=tmp_path,
            sandbox_limits=SANDBOX_LIMITS.model_copy(update={"network_enabled": True}),
        )


# --- the real agent runtime, driven by provider fixtures ------------------------------------


def verifying_model() -> ScriptedModel:
    """PROVIDER FIXTURE: create, then claim the id the gateway returned."""
    args = {"name": "Ada Lovelace", "email": "ada@analytical.example"}

    def report(request: InferenceRequest) -> InferenceResult:
        return claim("completed", customer_id_of(last_results(request)[0]))

    return ScriptedModel([tools(call("create_customer", args)), report])


def fixture_target(model: ScriptedModel, ledger: SpendLedger | None = None) -> AgentTarget:
    return AgentTarget(
        inference=model,
        evidence="offline_fixture",
        provider=FIXTURE_PROVIDER,
        model=FIXTURE_MODEL,
        budget=AgentBudget(),
        ledger=ledger,
    )


def test_agent_runs_through_the_existing_runtime_and_is_labeled(tmp_path: Path) -> None:
    evidence, _ = run(
        [run_action(), finish_action()], tmp_path, target=fixture_target(verifying_model())
    )
    (target,) = evidence.target_runs
    assert target.target_kind == "llm_agent"
    assert target.evidence_source == "offline_fixture"
    assert target.policy_version == "baseline-v1"
    assert target.tokens is not None
    report = json.loads((tmp_path / evidence.experiment_id / target.report_path).read_text())
    assert report["evidence_source"] == "offline_fixture"


def test_mission_contains_nothing_from_the_experiment(tmp_path: Path) -> None:
    model = verifying_model()
    marker = "EXPERIMENT_MARKER_TEXT"
    sandbox = ScriptedSandbox([run_action(), finish_action(summary=marker)])
    spec = ExperimentSpec(label=marker, code=f"# {marker}\n")
    coordinator(sandbox, fixture_target(model), tmp_path).run(spec)
    assert marker not in model.requests[0].model_dump_json()


def test_live_target_cannot_be_built_without_a_ledger() -> None:
    with pytest.raises(ValueError, match="spend ledger"):
        AgentTarget(
            inference=ScriptedModel([]),
            evidence="live_provider",
            provider="vultr",
            model="m",
            budget=AgentBudget(),
        )


def test_provider_failure_is_classified_and_not_retried(tmp_path: Path) -> None:
    model = ScriptedModel([InferenceError(ErrorCategory.PROVIDER_TIMEOUT, "timed out")])
    evidence, sandbox = run([run_action()], tmp_path, target=fixture_target(model))
    assert evidence.status is ExperimentState.FAILED
    assert evidence.termination is ExperimentTermination.PROVIDER_ERROR
    assert OutcomeClass.PROVIDER_FAILURE in evidence.classifications
    assert len(model.requests) == 1
    assert len(sandbox.requests) == 1
    assert evidence.target_runs[0].oracle is not None  # the world was still evaluated


def test_agent_stopping_short_is_a_target_outcome_not_infrastructure(tmp_path: Path) -> None:
    from tests.agent.conftest import text

    model = ScriptedModel([text("done"), text("really done")])
    evidence, _ = run([run_action(), finish_action()], tmp_path, target=fixture_target(model))
    assert evidence.status is ExperimentState.COMPLETED
    assert OutcomeClass.TARGET_AGENT_FAILURE in evidence.classifications


def test_exhausted_ledger_stops_before_any_inference(tmp_path: Path) -> None:
    prices = PriceCeiling(input_per_million_usd=1, output_per_million_usd=4)
    ledger = SpendLedger(tmp_path / "l.jsonl", limit_usd=0.0001, prices=prices)
    model = ScriptedModel([])
    evidence, _ = run([run_action()], tmp_path / "x", target=fixture_target(model, ledger))
    assert evidence.status is ExperimentState.BUDGET_EXHAUSTED
    assert evidence.termination is ExperimentTermination.SPEND_LIMIT
    assert evidence.target_runs == []
    assert evidence.unresolved_target_runs == []
    assert model.requests == []


def test_settled_cost_is_recorded_in_evidence(tmp_path: Path) -> None:
    prices = PriceCeiling(input_per_million_usd=1, output_per_million_usd=4)
    ledger = SpendLedger(tmp_path / "l.jsonl", limit_usd=5, prices=prices)
    target = fixture_target(verifying_model(), ledger)
    evidence, _ = run([run_action(), finish_action()], tmp_path / "x", target=target)
    assert evidence.usage.estimated_cost_usd is not None
    assert ledger.status().open_reservations == 0


# --- cancellation and failure ---------------------------------------------------------------


def test_cancel_before_a_step_runs_nothing(tmp_path: Path) -> None:
    cancel = Event()
    cancel.set()
    sandbox = ScriptedSandbox([])
    evidence = coordinator(sandbox, ForbiddenTarget(), tmp_path).run(SPEC, cancel=cancel)
    assert evidence.status is ExperimentState.CANCELLED
    assert sandbox.requests == []


def test_cancel_during_a_target_run_records_what_committed(tmp_path: Path) -> None:
    cancel = Event()
    args = {"name": "Ada Lovelace", "email": "ada@analytical.example"}

    def cancel_then_continue(_: InferenceRequest) -> InferenceResult:
        cancel.set()
        return tools(call("get_customer", {"customer_id": "cus_none"}))

    model = ScriptedModel([tools(call("create_customer", args)), cancel_then_continue])
    sandbox = ScriptedSandbox([run_action()])
    evidence = coordinator(sandbox, fixture_target(model), tmp_path).run(SPEC, cancel=cancel)
    assert evidence.status is ExperimentState.CANCELLED
    (target,) = evidence.target_runs
    assert len(target.committed.new_customer_ids) == 1  # truthfully kept, never rolled back
    assert target.target_observed.termination == "cancelled"
    assert len(sandbox.requests) == 1


class ExplodingTarget:
    def run(self, request: TargetRequest) -> TargetResult:
        raise RuntimeError("boom after possible effects")


def test_target_crash_is_uncertain_and_never_retried(tmp_path: Path) -> None:
    evidence, sandbox = run([run_action(), finish_action()], tmp_path, target=ExplodingTarget())
    assert evidence.status is ExperimentState.UNCERTAIN
    assert evidence.termination is ExperimentTermination.COORDINATOR_ERROR
    assert evidence.classifications == [OutcomeClass.COORDINATOR_FAILURE]
    assert [u.run_ref for u in evidence.unresolved_target_runs] == ["trun_1"]
    assert len(sandbox.requests) == 1


def test_failure_before_any_effect_is_failed_not_uncertain(tmp_path: Path) -> None:
    def explode(_: Any) -> Any:
        raise RuntimeError("bug")

    evidence, _ = run([explode], tmp_path, target=ForbiddenTarget())
    assert evidence.status is ExperimentState.FAILED
    assert evidence.unresolved_target_runs == []


# --- state machine --------------------------------------------------------------------------


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATES))
def test_terminal_states_are_final(terminal: ExperimentState) -> None:
    for state in ExperimentState:
        with pytest.raises(InvalidTransitionError):
            check_transition(terminal, state)


def test_completed_is_reachable_only_through_finalizing() -> None:
    for state in set(ExperimentState) - TERMINAL_STATES - {ExperimentState.FINALIZING}:
        with pytest.raises(InvalidTransitionError):
            check_transition(state, ExperimentState.COMPLETED)
    check_transition(ExperimentState.FINALIZING, ExperimentState.COMPLETED)


def test_target_cannot_start_without_validation() -> None:
    with pytest.raises(InvalidTransitionError):
        check_transition(ExperimentState.SANDBOX_RUNNING, ExperimentState.TARGET_RUNNING)


def test_evidence_round_trips_through_its_schema(tmp_path: Path) -> None:
    evidence, _ = run([run_action(), finish_action()], tmp_path)
    assert ExperimentEvidence.model_validate_json(evidence.model_dump_json()) == evidence
