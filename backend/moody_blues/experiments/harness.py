"""Builds the program one disposable sandbox step executes, and its sanitized observations.

A step program is the experiment code preceded by a small prologue that defines
``EXPERIMENT_INPUT`` (the parsed ``StepInput``) and ``emit(action)``. The prologue is a
convenience, not a control: the code shares its process and may ignore or replace it. Every
guarantee comes from the coordinator validating whatever appears on stdout.

The input is embedded in the program text, so no host path, socket or stdin is needed.
"""

from __future__ import annotations

import base64

from moody_blues.contracts.experiment_evidence import TargetRunEvidence
from moody_blues.contracts.protocol import (
    MAX_UNTRUSTED_TEXT_CHARS,
    InspectionObservation,
    InspectionSection,
    RunObservation,
    ToolCallObservation,
)
from moody_blues.contracts.run import ToolTraceEntry
from moody_blues.contracts.world import ToolName

_PROLOGUE = """\
import base64 as _b64, json as _json, sys as _sys
EXPERIMENT_INPUT = _json.loads(_b64.b64decode("{payload}"))
def emit(action):
    _sys.stdout.write(_json.dumps(action) + "\\n")
"""


def build_step_program(code: str, step_input_json: str) -> str:
    payload = base64.b64encode(step_input_json.encode()).decode("ascii")
    return _PROLOGUE.format(payload=payload) + code


def observe_run(run: TargetRunEvidence) -> RunObservation:
    """Compact, sanitized outcome. Contains no paths, ids of worlds, rows or trusted metadata."""
    observed, oracle = run.target_observed, run.oracle
    return RunObservation(
        run_ref=run.run_ref,
        scenario_ref=oracle.scenario_ref,
        config=run.authorized.config,
        target_kind=run.target_kind,
        termination=observed.termination,
        run_outcome=run.run_outcome,
        claim_status=observed.claim.status.value if observed.claim is not None else None,
        oracle_verdict=oracle.verdict.value,
        objective_satisfied=oracle.objective_satisfied,
        invariants_violated=[i.value for i in oracle.invariants_violated],
        finding_codes=sorted({f.code.value for f in oracle.findings}),
        tool_calls=len(observed.tool_trace),
        faults_delivered=observed.faults_delivered,
        tokens=run.tokens.total_tokens if run.tokens is not None else None,
    )


def _call_observation(entry: ToolTraceEntry) -> ToolCallObservation:
    data = entry.delivered.data or {}
    creating = entry.tool == ToolName.CREATE_CUSTOMER
    replay = data.get("idempotent_replay")
    count = data.get("count")
    return ToolCallObservation(
        seq=entry.call_seq,
        tool=entry.tool,
        ok=entry.delivered.ok,
        error_code=entry.delivered.error.code.value if entry.delivered.error else None,
        used_idempotency_key=entry.arguments.get("client_request_id") is not None
        if creating
        else None,
        idempotent_replay=replay if isinstance(replay, bool) else None,
        result_count=count if isinstance(count, int) else None,
    )


def _claim_points_to(run: TargetRunEvidence) -> str:
    """Where the claimed id leads in committed state. Never the id itself: it is model text."""
    claim = run.target_observed.claim
    if claim is None or claim.customer_id is None:
        return "none"
    observation = run.oracle.observation
    if claim.customer_id in observation.new_customer_ids:
        return "new_record"
    if claim.customer_id in observation.seed_customer_ids:
        return "seed_record"
    return "uncommitted"


def inspect_run(run: TargetRunEvidence, section: InspectionSection) -> InspectionObservation:
    match section:
        case InspectionSection.TOOL_TRACE:
            calls = [_call_observation(t) for t in run.target_observed.tool_trace]
            return InspectionObservation(run_ref=run.run_ref, section=section, tool_calls=calls)
        case InspectionSection.CLAIM:
            claim = run.target_observed.claim
            return InspectionObservation(
                run_ref=run.run_ref,
                section=section,
                claim_status=claim.status.value if claim is not None else None,
                claimed_customer_id=claim.customer_id if claim is not None else None,
                untrusted_claim_message=claim.message[:MAX_UNTRUSTED_TEXT_CHARS]
                if claim is not None
                else None,
            )
        case InspectionSection.STATE_SUMMARY:
            observation = run.oracle.observation
            return InspectionObservation(
                run_ref=run.run_ref,
                section=section,
                new_customers=len(observation.new_customer_ids),
                objective_matching_records=len(observation.objective_matching_ids),
                seed_customers=len(observation.seed_customer_ids),
                claim_points_to=_claim_points_to(run),
            )
