"""Parse and authorize untrusted sandbox output. Pure functions; nothing here has effects.

Two stages, in order:

1. ``parse_action``: is this one complete, well-formed, versioned protocol document?
2. ``authorize_action``: is this specific proposal allowed right now?

Anything short of a clear yes is a ``ProtocolRejection``. Output is never repaired, trimmed or
partly accepted: a truncated stream is refused even if what survived happens to be valid JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, NoReturn, cast

from pydantic import TypeAdapter, ValidationError

from moody_blues.contracts.common import ExecutionStatus
from moody_blues.contracts.protocol import (
    ALLOWED_ACTIONS,
    APPROVED_FAULT_MESSAGES,
    MAX_ACTION_BYTES,
    PROTOCOL_VERSION,
    ExperimentAction,
    FaultSelection,
    FinishExperiment,
    InspectObservation,
    ProtocolRejection,
    RejectionCode,
    RunTargetAgent,
)
from moody_blues.contracts.sandbox import SandboxResult
from moody_blues.contracts.scenario import READ_OPERATION, FaultKind, FaultSpec, ScenarioBase
from moody_blues.contracts.world import ToolErrorCode
from moody_blues.world.crm_plugin import APPROVED_SCENARIOS as APPROVED_SCENARIOS
from moody_blues.world.plugin import WorldPlugin
from moody_blues.world.registry import plugin_for

_ACTION_ADAPTER: TypeAdapter[RunTargetAgent | InspectObservation | FinishExperiment] = TypeAdapter(
    ExperimentAction
)


class _DuplicateKeyError(ValueError):
    pass


def _reject(code: RejectionCode, detail: str) -> ProtocolRejection:
    return ProtocolRejection(code=code, detail=detail[:500])


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise _DuplicateKeyError("duplicate object key")
    return dict(pairs)


def _no_constants(name: str) -> NoReturn:
    raise ValueError(f"non-standard JSON constant {name}")


def strict_loads(text: str) -> Any:
    """One standard JSON document. Duplicate keys and NaN-style constants raise ``ValueError``."""
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constants)


def parse_action(
    result: SandboxResult,
) -> RunTargetAgent | InspectObservation | FinishExperiment | ProtocolRejection:
    """Turn a *successful* step's stdout into exactly one action, or reject it."""
    if result.status is not ExecutionStatus.SUCCEEDED:
        raise ValueError("parse_action requires a successful sandbox result")
    if not result.output_complete:
        return _reject(RejectionCode.OUTPUT_INCOMPLETE, "output stream ended abnormally")
    if result.stdout_truncated:
        return _reject(
            RejectionCode.OUTPUT_TRUNCATED, f"stdout was truncated ({result.stdout_bytes} bytes)"
        )
    if result.stdout_bytes > MAX_ACTION_BYTES or len(result.stdout.encode()) > MAX_ACTION_BYTES:
        return _reject(
            RejectionCode.OUTPUT_OVERSIZED,
            f"stdout is {result.stdout_bytes} bytes; the limit is {MAX_ACTION_BYTES}",
        )
    if "�" in result.stdout:  # the runner decoded with errors="replace"
        return _reject(RejectionCode.INVALID_ENCODING, "stdout is not valid UTF-8")
    text = result.stdout.strip()
    if not text:
        return _reject(RejectionCode.OUTPUT_EMPTY, "the step produced no action")
    try:
        document = strict_loads(text)
    except (ValueError, RecursionError) as exc:  # includes JSONDecodeError and duplicates
        return _reject(RejectionCode.MALFORMED_JSON, f"not one JSON document: {exc}")
    if not isinstance(document, dict):
        return _reject(RejectionCode.MALFORMED_JSON, "the action must be a JSON object")
    fields = cast(dict[str, Any], document)

    if fields.get("protocol") != PROTOCOL_VERSION:
        return _reject(RejectionCode.UNSUPPORTED_VERSION, f"expected {PROTOCOL_VERSION}")
    name = fields.get("action")
    if not isinstance(name, str) or name not in ALLOWED_ACTIONS:
        return _reject(RejectionCode.UNAUTHORIZED_ACTION, "action is not on the allowlist")
    try:
        # JSON mode: strict models then accept enum values as strings, and nothing else.
        return _ACTION_ADAPTER.validate_json(text)
    except ValidationError as exc:
        # Field locations only: pydantic's messages can echo the untrusted input.
        bad = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        return _reject(RejectionCode.SCHEMA_VIOLATION, f"invalid fields: {', '.join(bad)}")


def fault_specs(
    selections: list[FaultSelection], world: WorldPlugin | None = None
) -> list[FaultSpec]:
    """Approved selections -> trusted specs. Messages come from the world's approved table only.

    The selection carries no operation: a fault lands on the selected world's own write.
    """
    messages = world.fault_messages() if world is not None else APPROVED_FAULT_MESSAGES
    operation = world.descriptor.shape.write_tool if world is not None else None
    specs: list[FaultSpec] = []
    for selection in selections:
        code = ToolErrorCode(selection.error_code)
        if selection.kind is FaultKind.STALE_READ:
            specs.append(
                FaultSpec(
                    kind=selection.kind,
                    operation=READ_OPERATION,
                    occurrence=selection.occurrence,
                    span=selection.span,
                )
            )
            continue
        specs.append(
            FaultSpec.model_validate(
                {
                    "kind": selection.kind,
                    "occurrence": selection.occurrence,
                    "error_code": code,
                    "error_message": messages[code],
                }
                | ({"operation": operation} if operation is not None else {})
            )
        )
    return specs


@dataclass(frozen=True, slots=True)
class AuthorizedTargetRun:
    scenario: ScenarioBase
    config: str
    fault_source: str


def authorize_run(
    action: RunTargetAgent, *, scenario: ScenarioBase, runs_done: int, max_runs: int
) -> AuthorizedTargetRun | ProtocolRejection:
    if runs_done >= max_runs:
        return _reject(RejectionCode.TARGET_RUN_LIMIT, f"limit of {max_runs} target run(s) reached")
    if action.faults is None:
        return AuthorizedTargetRun(scenario, action.config, "scenario")
    if any(f.span > 1 and f.kind is not FaultKind.STALE_READ for f in action.faults):
        return _reject(RejectionCode.INVALID_FAULT, "only stale_read may span several calls")
    targets = [
        (f.kind is FaultKind.STALE_READ, f.occurrence + i)
        for f in action.faults
        for i in range(f.span)
    ]
    if len(targets) != len(set(targets)):
        return _reject(RejectionCode.INVALID_FAULT, "two faults target the same occurrence")
    if any(
        f.kind is not FaultKind.PHANTOM_FAILURE and f.error_code != ToolErrorCode.TIMEOUT.value
        for f in action.faults
    ):
        return _reject(RejectionCode.INVALID_FAULT, "only phantom_failure takes an error_code")
    # Rebuilt through the validator: the scenario's own rules still apply to the result.
    data = scenario.model_dump(mode="json")
    selected = fault_specs(action.faults, plugin_for(scenario))
    data["faults"] = [f.model_dump(mode="json") for f in selected]
    return AuthorizedTargetRun(
        type(scenario).model_validate(data), action.config, "experiment_selection"
    )
