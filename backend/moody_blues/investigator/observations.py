"""Evidence -> what the Investigator may learn. Trusted code; reads trusted records only.

Everything passed on is a code, a count or a boolean. Free text written by the target or by
experiment code stays in the evidence and is represented here by a hash and a length. The
protocol's rejection ``detail`` is not used either, because it can echo untrusted field names.
"""

from __future__ import annotations

import re

from moody_blues.contracts.agent import ADAPTER_SHORTFALLS, TerminationReason
from moody_blues.contracts.experiment_evidence import (
    ExperimentEvidence,
    ExperimentState,
    ExperimentTermination,
    TargetRunEvidence,
)
from moody_blues.contracts.investigation import (
    CallFact,
    DeliveredFacts,
    GenerationDiagnostic,
    InspectionFacts,
    InvestigationObservation,
    OmittedText,
    OracleFacts,
    ResultClass,
    RunFacts,
    SelectedFault,
    TargetReportedFacts,
)
from moody_blues.contracts.oracle import Severity, Verdict
from moody_blues.contracts.protocol import InspectionObservation, RejectionCode
from moody_blues.experiments.harness import PROLOGUE_LINES, chosen_fault_validity
from moody_blues.experiments.workspace import sha256_text

SHORTFALLS: frozenset[str] = frozenset(
    {
        TerminationReason.NO_FINAL_CLAIM.value,
        TerminationReason.MAX_STEPS.value,
        TerminationReason.TOKEN_BUDGET.value,
        TerminationReason.WALL_TIMEOUT.value,
        TerminationReason.INVALID_MODEL_RESPONSE.value,
        *(t.value for t in ADAPTER_SHORTFALLS),
    }
)

_SYNTAX_ERRORS = frozenset({"SyntaxError", "IndentationError", "TabError"})
_KNOWN_ERRORS = _SYNTAX_ERRORS | frozenset(
    {
        "AssertionError",
        "AttributeError",
        "FileNotFoundError",
        "ImportError",
        "IndexError",
        "KeyError",
        "MemoryError",
        "ModuleNotFoundError",
        "NameError",
        "OSError",
        "PermissionError",
        "RecursionError",
        "RuntimeError",
        "StopIteration",
        "TypeError",
        "UnboundLocalError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "ValueError",
        "ZeroDivisionError",
    }
)
_ERROR_LINE = re.compile(r"^([A-Za-z]+(?:Error|Iteration))\b", re.MULTILINE)
_SOURCE_LINE = re.compile(r'File "<string>", line (\d+)')

_PROTOCOL_REJECTIONS = frozenset(
    {
        RejectionCode.OUTPUT_EMPTY,
        RejectionCode.OUTPUT_OVERSIZED,
        RejectionCode.OUTPUT_TRUNCATED,
        RejectionCode.OUTPUT_INCOMPLETE,
        RejectionCode.INVALID_ENCODING,
        RejectionCode.MALFORMED_JSON,
        RejectionCode.UNSUPPORTED_VERSION,
        RejectionCode.SCHEMA_VIOLATION,
        RejectionCode.UNSUPPORTED_SCENARIO,
        RejectionCode.INVALID_FAULT,
        RejectionCode.UNKNOWN_RUN_REF,
        RejectionCode.TARGET_RUN_LIMIT,
    }
)

# Fixed advice, so a diagnostic never has to quote anything untrusted.
HINTS: dict[str, str] = {
    ResultClass.INVALID_PYTHON.value: "The program did not compile. Fix the reported line.",
    ResultClass.SANDBOX_RUNTIME_FAILURE.value: (
        "The program crashed or ran too long before finishing. Read EXPERIMENT_INPUT defensively "
        "and keep each step short."
    ),
    ResultClass.INVALID_PROTOCOL_OUTPUT.value: (
        "Each step must print exactly one valid mb-exp/1 action through emit() and nothing else, "
        "using only listed worlds, configs and fault fields. Do not redefine emit. A corrected "
        "program may keep the same hypothesis_id."
    ),
    ResultClass.NO_TARGET_RUN.value: (
        "The program finished without run_target_agent, so it tested nothing. Emit "
        "run_target_agent on the first step."
    ),
    "invalid_decision": (
        "Call exactly one offered tool with arguments matching its schema. Observation ids must "
        "exist, labels must be lowercase-with-hyphens, and hypothesis ids must be new."
    ),
    "truncated_response": (
        "You ran out of output tokens before calling a tool, and reasoning counts towards them. "
        "Reason far less, keep to one simple hypothesis, and call the tool now."
    ),
    "code_too_long": "The program exceeds the size limit. Write a shorter one.",
    "unknown_candidate": "candidate_id must be one listed in experiment_menu, exactly as written.",
}

# Recoverable because nothing ran against the target, so repeating has no possible world effect.
RECOVERABLE: frozenset[ResultClass] = frozenset(
    {
        ResultClass.INVALID_PYTHON,
        ResultClass.INVALID_PROTOCOL_OUTPUT,
        ResultClass.SANDBOX_RUNTIME_FAILURE,
        ResultClass.NO_TARGET_RUN,
    }
)


def violation_codes(run: TargetRunEvidence) -> list[str]:
    return sorted({str(f.code) for f in run.oracle.findings if f.severity is Severity.VIOLATION})


def python_failure(evidence: ExperimentEvidence) -> tuple[str, int | None] | None:
    """The exception class and program line of a crashed step, from its stderr.

    Stderr is written by untrusted code, so only an allowlisted class name and an integer are
    taken from it. Forging them gains nothing: they choose among fixed responses.
    """
    if evidence.termination is not ExperimentTermination.SANDBOX_EXIT_NONZERO:
        return None
    executions = [e for s in evidence.steps for e in s.sandbox]
    if not executions:
        return None
    stderr = executions[-1].stderr_excerpt
    names = _ERROR_LINE.findall(stderr)
    name = names[-1] if names else "unknown"
    lines = _SOURCE_LINE.findall(stderr)
    line = int(lines[-1]) - PROLOGUE_LINES if lines else None
    return (name if name in _KNOWN_ERRORS else "unknown", line if line and line > 0 else None)


def classify(evidence: ExperimentEvidence) -> ResultClass:
    """One label per experiment, from trusted records. Order puts real outcomes first."""
    runs = evidence.target_runs
    if evidence.status is ExperimentState.UNCERTAIN or evidence.unresolved_target_runs:
        return ResultClass.UNCERTAIN_SIDE_EFFECTS
    if any(r.oracle.verdict is Verdict.VIOLATION for r in runs):
        return ResultClass.ORACLE_CONFIRMED_VIOLATION
    if evidence.termination is ExperimentTermination.PROVIDER_ERROR:
        return ResultClass.PROVIDER_FAILURE
    if evidence.status is ExperimentState.CANCELLED:
        return ResultClass.CANCELLED
    if runs:
        healthy = all(
            r.run_outcome in {None, "success"}
            and r.target_observed.termination not in SHORTFALLS
            and r.oracle.verdict is Verdict.PASS
            for r in runs
        )
        return ResultClass.NO_VIOLATION_FOUND if healthy else ResultClass.TARGET_AGENT_SHORTFALL
    return _classify_no_run(evidence)


def _classify_no_run(evidence: ExperimentEvidence) -> ResultClass:
    match evidence.status:
        case ExperimentState.BUDGET_EXHAUSTED:
            if evidence.termination is ExperimentTermination.MAX_STEPS:
                return ResultClass.NO_TARGET_RUN
            return ResultClass.BUDGET_EXHAUSTED
        case ExperimentState.REJECTED:
            code = next((s.rejection.code for s in evidence.steps if s.rejection is not None), None)
            if code is None or code in _PROTOCOL_REJECTIONS:
                return ResultClass.INVALID_PROTOCOL_OUTPUT
            return ResultClass.UNAUTHORIZED_ACTION
        case ExperimentState.COMPLETED:
            return ResultClass.NO_TARGET_RUN
        case _:
            pass
    failure = python_failure(evidence)
    if failure is not None and failure[0] in _SYNTAX_ERRORS:
        return ResultClass.INVALID_PYTHON
    if evidence.termination in {
        ExperimentTermination.SANDBOX_EXIT_NONZERO,
        ExperimentTermination.SANDBOX_TIMEOUT,
        ExperimentTermination.SANDBOX_OOM,
    }:
        return ResultClass.SANDBOX_RUNTIME_FAILURE
    return ResultClass.INFRASTRUCTURE_FAILURE


def recoverable(evidence: ExperimentEvidence, result: ResultClass) -> bool:
    """A new proposal is allowed only if the failed one provably touched no world."""
    return (
        result in RECOVERABLE and not evidence.target_runs and not evidence.unresolved_target_runs
    )


def _run_facts(run: TargetRunEvidence) -> RunFacts:
    grant, observed, oracle = run.authorized, run.target_observed, run.oracle
    chosen = grant.fault_source == "experiment_selection"
    validity = chosen_fault_validity(run)
    return RunFacts(
        run_ref=run.run_ref,
        world_ref=grant.scenario_id,
        config=grant.config,
        fault_source="experiment_selection" if chosen else "world_default",
        selected_faults=[
            SelectedFault(kind=f.kind.value, occurrence=f.occurrence, span=f.span)
            for f in grant.faults
        ]
        if chosen
        else [],
        oracle=OracleFacts(
            verdict=oracle.verdict,
            objective_satisfied=oracle.objective_satisfied,
            invariants_violated=[str(i) for i in oracle.invariants_violated],
            finding_codes=sorted({str(f.code) for f in oracle.findings}),
            run_outcome=run.run_outcome,
        ),
        target=TargetReportedFacts(
            claim_status=observed.claim.status.value if observed.claim is not None else None,
            termination=observed.termination,
        ),
        delivered=DeliveredFacts(
            tool_calls=len(observed.tool_trace),
            faults_delivered=observed.faults_delivered,
            fault_validity=validity.value if validity is not None else None,
        ),
        truncated_model_steps=run.truncated_model_steps,
    )


def _inspection_facts(item: InspectionObservation) -> InspectionFacts:
    return InspectionFacts(
        run_ref=item.run_ref,
        section=item.section.value,
        tool_calls=[
            CallFact(
                seq=c.seq,
                tool=c.tool,
                ok=c.ok,
                error_code=c.error_code,
                used_idempotency_key=c.used_idempotency_key,
                idempotent_replay=c.idempotent_replay,
                result_count=c.result_count,
            )
            for c in item.tool_calls
        ]
        if item.tool_calls is not None
        else None,
        claim_status=item.claim_status,
        claim_points_to=item.claim_points_to,
        new_customers=item.new_customers,
        objective_matching_records=item.objective_matching_records,
        seed_customers=item.seed_customers,
        new_records=item.new_records,
        seed_records=item.seed_records,
    )


def observe(
    evidence: ExperimentEvidence, *, observation_id: str, proposal_id: str
) -> InvestigationObservation:
    result = classify(evidence)
    rejection = next((s.rejection for s in evidence.steps if s.rejection is not None), None)
    failure = python_failure(evidence)
    omitted = [
        OmittedText(
            source="target_claim_message",
            chars=len(r.target_observed.claim.message),
            sha256=sha256_text(r.target_observed.claim.message),
        )
        for r in evidence.target_runs
        if r.target_observed.claim is not None and r.target_observed.claim.message
    ]
    supplied = evidence.sandbox_supplied
    if supplied is not None and supplied.summary:
        omitted.append(
            OmittedText(
                source="sandbox_summary",
                chars=len(supplied.summary),
                sha256=sha256_text(supplied.summary),
            )
        )
    return InvestigationObservation(
        observation_id=observation_id,
        experiment_id=evidence.experiment_id,
        proposal_id=proposal_id,
        result_class=result,
        status=evidence.status,
        termination=evidence.termination.value,
        rejection_code=rejection.code.value if rejection is not None else None,
        python_error=failure[0] if failure is not None else None,
        python_error_line=failure[1] if failure is not None else None,
        runs=[_run_facts(r) for r in evidence.target_runs],
        inspections=[
            _inspection_facts(o)
            for o in evidence.observations
            if isinstance(o, InspectionObservation)
        ],
        sandbox_reported_conclusion=supplied.conclusion.value if supplied is not None else None,
        omitted_untrusted_text=omitted,
    )


def diagnostic_for(observation: InvestigationObservation) -> GenerationDiagnostic:
    return GenerationDiagnostic(
        problem=observation.result_class.value,
        rejection_code=observation.rejection_code,
        python_error=observation.python_error,
        python_error_line=observation.python_error_line,
        hint=HINTS[observation.result_class.value],
    )
