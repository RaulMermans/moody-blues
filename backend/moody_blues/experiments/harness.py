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
from moody_blues.contracts.oracle import WorldStateObservation
from moody_blues.contracts.protocol import (
    MAX_UNTRUSTED_TEXT_CHARS,
    InspectionObservation,
    InspectionSection,
    RunObservation,
    ToolCallObservation,
)
from moody_blues.contracts.run import ToolTraceEntry
from moody_blues.contracts.validity import ValidityClass
from moody_blues.contracts.world import WorldClaim
from moody_blues.contracts.world_plugin import ToolShape
from moody_blues.experiments.validity import assess_delivery
from moody_blues.world.crm_plugin import CRM_SHAPE
from moody_blues.world.registry import world_plugin

_PROLOGUE = """\
import base64 as _b64, json as _json, sys as _sys
EXPERIMENT_INPUT = _json.loads(_b64.b64decode("{payload}"))
def emit(action):
    _sys.stdout.write(_json.dumps(action) + "\\n")
"""


PROLOGUE_LINES = _PROLOGUE.count("\n")


def build_step_program(code: str, step_input_json: str) -> str:
    payload = base64.b64encode(step_input_json.encode()).decode("ascii")
    return _PROLOGUE.format(payload=payload) + code


def _shape(run: TargetRunEvidence) -> ToolShape:
    return world_plugin(run.world_type).descriptor.shape


def chosen_fault_validity(run: TargetRunEvidence) -> ValidityClass | None:
    """For faults the experiment selected. A world's own conditions stay unnamed."""
    if run.authorized.fault_source != "experiment_selection":
        return None
    validity = run.validity or assess_delivery(
        run.authorized.faults, run.target_observed.tool_trace, run.authorized.fault_source
    )
    return validity.classification


def observe_run(run: TargetRunEvidence) -> RunObservation:
    """Compact, sanitized outcome. Contains no paths, ids of worlds, rows or trusted metadata."""
    observed, oracle = run.target_observed, run.oracle
    validity = chosen_fault_validity(run)
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
        invariants_violated=[str(i) for i in oracle.invariants_violated],
        finding_codes=sorted({str(f.code) for f in oracle.findings}),
        tool_calls=len(observed.tool_trace),
        faults_delivered=observed.faults_delivered,
        tokens=run.tokens.total_tokens if run.tokens is not None else None,
        fault_validity=validity.value if validity is not None else None,
    )


def _call_observation(entry: ToolTraceEntry, shape: ToolShape = CRM_SHAPE) -> ToolCallObservation:
    data = entry.delivered.data or {}
    creating = entry.tool == shape.write_tool
    replay = data.get("idempotent_replay")
    count = data.get("count")
    return ToolCallObservation(
        seq=entry.call_seq,
        tool=entry.tool,
        ok=entry.delivered.ok,
        error_code=entry.delivered.error.code.value if entry.delivered.error else None,
        used_idempotency_key=entry.arguments.get(shape.key_argument) is not None
        if creating
        else None,
        idempotent_replay=replay if isinstance(replay, bool) else None,
        result_count=count if isinstance(count, int) else None,
    )


def _claim_points_to(run: TargetRunEvidence) -> str:
    """Where the claimed id leads in committed state. Never the id itself: it is model text."""
    claim = run.target_observed.claim
    if claim is None or claim.record_ref is None:
        return "none"
    observation = run.oracle.observation
    if claim.record_ref in observation.new_ids:
        return "new_record"
    if claim.record_ref in observation.seed_ids:
        return "seed_record"
    return "uncommitted"


def inspect_run(run: TargetRunEvidence, section: InspectionSection) -> InspectionObservation:
    match section:
        case InspectionSection.TOOL_TRACE:
            shape = _shape(run)
            calls = [_call_observation(t, shape) for t in run.target_observed.tool_trace]
            return InspectionObservation(run_ref=run.run_ref, section=section, tool_calls=calls)
        case InspectionSection.CLAIM:
            claim = run.target_observed.claim
            neutral = isinstance(claim, WorldClaim)
            return InspectionObservation(
                run_ref=run.run_ref,
                section=section,
                claim_status=claim.status.value if claim is not None else None,
                claimed_customer_id=claim.record_ref if claim is not None and not neutral else None,
                claimed_record_id=claim.record_ref if claim is not None and neutral else None,
                untrusted_claim_message=claim.message[:MAX_UNTRUSTED_TEXT_CHARS]
                if claim is not None
                else None,
            )
        case InspectionSection.STATE_SUMMARY:
            observation = run.oracle.observation
            neutral = isinstance(observation, WorldStateObservation)
            new, seeds = len(observation.new_ids), len(observation.seed_ids)
            return InspectionObservation(
                run_ref=run.run_ref,
                section=section,
                new_customers=None if neutral else new,
                new_records=new if neutral else None,
                objective_matching_records=len(observation.objective_matching_ids),
                seed_customers=None if neutral else seeds,
                seed_records=seeds if neutral else None,
                claim_points_to=_claim_points_to(run),
            )
