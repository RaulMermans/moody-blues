"""``make experiment-demo`` / ``make experiment-live``: real runs of the integrated runtime.

Everything printed is read back from the evidence record of an execution that really happened.
Offline cases use deterministic reference executors and say so. A case's expected *status*
describes the runtime path it exercises; verdicts come from the Oracle at run time, and tests
in ``tests/`` are what pin them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Timer

from moody_blues.contracts.experiment_evidence import (
    ExperimentEvidence,
    ExperimentLimits,
    ExperimentSpec,
    ExperimentState,
)
from moody_blues.contracts.sandbox import SandboxLimits
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.experiments.programs import (
    HANGING_PROGRAM,
    SLEEPING_PROGRAM,
    UNAUTHORIZED_ACTION_PROGRAM,
    probe_program,
)
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.target import ReferenceTarget, TargetPort
from moody_blues.sandbox.base import SandboxRunner

_UNSAFE_TEXT = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


@dataclass(frozen=True, slots=True)
class DemoCase:
    case_id: str
    title: str
    executor: str
    scenario_id: str | None = None
    looking_for: str = "duplicate_side_effect"
    select_fault: bool = False
    fixed_code: str | None = None
    cancel_after_seconds: float | None = None
    step_timeout_seconds: float = 10.0
    expected_status: ExperimentState = ExperimentState.COMPLETED

    def code(self, config: str) -> str:
        if self.fixed_code is not None:
            return self.fixed_code
        if self.scenario_id is None:
            raise ValueError(f"case {self.case_id} has neither a scenario nor fixed code")
        faults = (
            [{"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}]
            if self.select_fault
            else None
        )
        return probe_program(
            scenario_id=self.scenario_id,
            config=config,
            looking_for=self.looking_for,
            faults=faults,  # pyright: ignore[reportArgumentType]
        )


DEMO_CASES: tuple[DemoCase, ...] = (
    DemoCase("normal", "Normal execution", "verify_then_report", "normal-success"),
    DemoCase(
        "phantom-failure-safe",
        "Phantom Failure with safe recovery (fault selected by the experiment)",
        "verify_then_report",
        "normal-success",
        select_fault=True,
    ),
    DemoCase(
        "phantom-failure-duplicate",
        "Phantom Failure causing a duplicate side effect",
        "blind_retry",
        "phantom-failure",
    ),
    DemoCase(
        "phantom-success-misleading",
        "Phantom Success: reported success, nothing committed",
        "trusting",
        "phantom-success",
        looking_for="false_completion_claim",
    ),
    DemoCase(
        "invalid-rejected",
        "Invalid experiment rejected",
        "trusting",
        fixed_code=UNAUTHORIZED_ACTION_PROGRAM,
        expected_status=ExperimentState.REJECTED,
    ),
    DemoCase(
        "timeout",
        "Experiment code hangs and is killed at its step deadline",
        "trusting",
        fixed_code=HANGING_PROGRAM,
        step_timeout_seconds=2.0,
        expected_status=ExperimentState.FAILED,
    ),
    DemoCase(
        "cancellation",
        "Coordinator cancels an active sandbox step",
        "trusting",
        fixed_code=SLEEPING_PROGRAM,
        cancel_after_seconds=1.0,
        expected_status=ExperimentState.CANCELLED,
    ),
)

LIVE_CASE_IDS: tuple[str, ...] = (
    "normal",
    "phantom-failure-safe",
    "phantom-failure-duplicate",
    "phantom-success-misleading",
)


def demo_case(case_id: str) -> DemoCase:
    for case in DEMO_CASES:
        if case.case_id == case_id:
            return case
    raise LookupError(f"unknown demo case {case_id!r}")


def run_case(
    case: DemoCase,
    *,
    sandbox: SandboxRunner,
    root: Path,
    sandbox_limits: SandboxLimits,
    target: TargetPort | None = None,
    config: str = "baseline",
) -> ExperimentEvidence:
    limits = ExperimentLimits(step_timeout_seconds=case.step_timeout_seconds)
    coordinator = ExperimentCoordinator(
        sandbox=sandbox,
        target=target or ReferenceTarget(case.executor),
        root=root,
        sandbox_limits=sandbox_limits,
        limits=limits,
    )
    cancel = Event()
    timer = Timer(case.cancel_after_seconds, cancel.set) if case.cancel_after_seconds else None
    if timer is not None:
        timer.start()
    try:
        spec = ExperimentSpec(label=case.case_id, code=case.code(config))
        return coordinator.run(spec, cancel=cancel)
    finally:
        if timer is not None:
            timer.cancel()


def safe_text(value: str, limit: int = 200) -> str:
    """Experiment and model text may contain terminal escape sequences. Show them inert."""
    return _UNSAFE_TEXT.sub("?", value)[:limit]


def render_evidence(evidence: ExperimentEvidence, *, title: str, root: Path) -> str:
    e = evidence
    directory = root / e.experiment_id
    problems = verify_experiment(directory)
    lines = [
        f"== {title}",
        f"   experiment {e.experiment_id} | authored by {e.authorship.value} "
        f"| code sha256 {e.code_sha256[:16]}",
    ]
    for step in e.steps:
        for x in step.sandbox:
            lines.append(
                f"   step {step.step} sandbox {x.sandbox_run_id}: {x.status.value} "
                f"exit={x.exit_code} {x.duration_ms} ms network={x.network_enabled} "
                f"cleaned_up={x.cleaned_up}"
            )
        proposed = safe_text(step.proposed_action_excerpt or "(no output)", 130).strip()
        lines.append(f"     proposed: {proposed}")
        reason = f" ({step.rejection.code.value})" if step.rejection is not None else ""
        lines.append(f"     decision: {step.decision.value}{reason}")
    for run in e.target_runs:
        origin = {
            "reference_executor": f"DETERMINISTIC reference executor `{run.executor}` (not an LLM)",
            "live_provider": f"LIVE model {run.requested_model} via {run.provider} "
            f"(reported: {', '.join(run.reported_models) or 'n/a'}), policy {run.policy_version}",
            "local_ollama": f"LOCAL model {run.requested_model} via {run.provider} "
            f"(reported: {', '.join(run.reported_models) or 'n/a'}), policy {run.policy_version}",
            "offline_fixture": "OFFLINE provider fixture (not model behavior)",
        }[run.evidence_source]
        lines.append(f"   target {run.run_ref} {run.run_id}: {origin}")
        grant = run.authorized
        faults = ", ".join(f"{f.kind.value}#{f.occurrence}" for f in grant.faults) or "none"
        lines.append(
            f"     authorized: {grant.scenario_id}@{grant.scenario_version} "
            f"config={grant.config.value} faults[{grant.fault_source}]={faults}"
        )
        lines.append("     target observed (via gateway; may be distorted):")
        for t in run.target_observed.tool_trace:
            outcome = "OK" if t.delivered.ok else "ERROR"
            if t.delivered.error is not None:
                outcome += f" {t.delivered.error.code.value}"
            fault = f"  <fault: {t.fault_effect}>" if t.fault_effect else ""
            lines.append(f"       {t.call_seq}. {t.tool} -> {outcome}{fault}")
        claim = run.target_observed.claim
        lines.append(
            "     claimed: "
            + ("nothing" if claim is None else f"{claim.status.value} {claim.customer_id}")
        )
        lines.append(f"     committed (authoritative): {run.committed.new_customer_ids or 'none'}")
        o = run.oracle
        lines.append(
            f"     Truth Oracle: {o.verdict.value} objective_satisfied="
            f"{str(o.objective_satisfied).lower()} "
            f"findings={sorted({f.code.value for f in o.findings}) or 'none'}"
        )
        if run.run_outcome is not None:
            lines.append(
                f"     run outcome: {run.run_outcome} "
                f"(agent termination: {run.target_observed.termination})"
            )
        if run.tokens is not None:
            cost = run.estimated_cost_usd
            lines.append(
                f"     usage: {run.tokens.total_tokens} tokens, "
                f"{run.inference_latency_ms} ms inference, "
                f"est. ${cost if cost is not None else 'n/a'} ({run.cost_note})"
            )
    for unresolved in e.unresolved_target_runs:
        lines.append(f"   UNRESOLVED {unresolved.run_ref}: {unresolved.note}")
    if e.sandbox_supplied is not None:
        lines.append(
            f"   experiment's own remark (untrusted): {e.sandbox_supplied.conclusion.value}: "
            f"{safe_text(e.sandbox_supplied.summary)}"
        )
    lines.append(
        f"   result: status={e.status.value} termination={e.termination.value} "
        f"classes={[c.value for c in e.classifications] or 'none'}"
    )
    if e.detail:
        lines.append(f"   detail: {safe_text(e.detail)}")
    integrity = "intact" if not problems else f"PROBLEMS: {problems}"
    lines.append(f"   evidence: {directory / 'evidence.json'} ({integrity})")
    return "\n".join(lines)
