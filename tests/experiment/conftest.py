"""OFFLINE fixtures for the experiment runtime.

``ScriptedSandbox`` is a TEST DOUBLE: it returns pre-written stdout without running anything.
Tests built on it cover parsing, authorization, lifecycle and evidence logic. They are NOT
evidence of containment, which comes only from the real Docker tests in tests/integration and
tests/security. Worlds, gateway and Oracle are real.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Event
from typing import Any

from moody_blues.contracts.common import ExecutionStatus, MoodyBluesError
from moody_blues.contracts.experiment_evidence import ExperimentLimits
from moody_blues.contracts.sandbox import SandboxLimits, SandboxRequest, SandboxResult
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.experiments.target import TargetPort

SANDBOX_LIMITS = SandboxLimits(wall_timeout_seconds=5, memory_mb=64, cpus=0.5, pids_limit=32)
P = "mb-exp/1"


def sandbox_result(stdout: str = "", **overrides: Any) -> SandboxResult:
    base: dict[str, Any] = {
        "run_id": "sbx_fixture",
        "status": ExecutionStatus.SUCCEEDED,
        "exit_code": 0,
        "stdout": stdout,
        "stderr": "",
        "stdout_bytes": len(stdout.encode()),
        "duration_ms": 1,
        "image": "fixture",
        "limits": SANDBOX_LIMITS,
        "cleaned_up": True,
    }
    return SandboxResult.model_validate(base | overrides)


def run_action(scenario_id: str = "normal-success", **extra: Any) -> str:
    return json.dumps(
        {
            "protocol": P,
            "action": "run_target_agent",
            "scenario_id": scenario_id,
            "config": "baseline",
        }
        | extra
    )


def inspect_action(section: str = "tool_trace", run_ref: str = "trun_1") -> str:
    return json.dumps(
        {"protocol": P, "action": "inspect_observation", "run_ref": run_ref, "section": section}
    )


def finish_action(conclusion: str = "inconclusive", summary: str = "", **extra: Any) -> str:
    return json.dumps(
        {"protocol": P, "action": "finish_experiment", "conclusion": conclusion, "summary": summary}
        | extra
    )


Step = str | SandboxResult | MoodyBluesError | Callable[[SandboxRequest], SandboxResult]


class ScriptedSandbox:
    """TEST DOUBLE. Plays ``steps`` in order and records each request."""

    def __init__(self, steps: Sequence[Step]) -> None:
        self._steps = list(steps)
        self.requests: list[SandboxRequest] = []

    def ping(self) -> None:
        return None

    def run(self, request: SandboxRequest, *, cancel: Event | None = None) -> SandboxResult:
        self.requests.append(request)
        if not self._steps:
            raise AssertionError("ScriptedSandbox ran out of steps")
        step = self._steps.pop(0)
        if isinstance(step, MoodyBluesError):
            raise step
        if isinstance(step, SandboxResult):
            return step
        if isinstance(step, str):
            return sandbox_result(step)
        return step(request)


def coordinator(
    sandbox: ScriptedSandbox,
    target: TargetPort,
    root: Path,
    limits: ExperimentLimits | None = None,
) -> ExperimentCoordinator:
    return ExperimentCoordinator(
        sandbox=sandbox,
        target=target,
        root=root,
        sandbox_limits=SANDBOX_LIMITS,
        limits=limits,
    )
