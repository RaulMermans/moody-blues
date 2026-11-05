"""OFFLINE fixtures. Worlds, gateway, Oracle and evidence are real; the sandbox is a test double
that replays one experiment, and targets are reference scripts. Nothing here describes a model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, ExperimentSpec
from moody_blues.evaluation.manifest import (
    Faults,
    Manifest,
    TrialPlan,
    build_manifest,
    expand_plan,
)
from moody_blues.evaluation.trials import TrialRecord, trial_from_run
from moody_blues.experiments.target import ReferenceTarget
from moody_blues.investigator.workflow import ExperimentRunner
from tests.experiment.conftest import SANDBOX_LIMITS, finish_action
from tests.investigator.conftest import ApprovedSandbox


def manifest_for_tests() -> Manifest:
    return build_manifest(Settings(_env_file=None), settled_usd=2.5)  # type: ignore[call-arg]


@pytest.fixture
def manifest() -> Manifest:
    return manifest_for_tests()


@pytest.fixture
def plan(manifest: Manifest) -> TrialPlan:
    return expand_plan(manifest)


def run_experiment(
    root: Path,
    *,
    executor: str,
    world: str = "w-e3",
    faults: Faults | None = None,
    config: str = "baseline",
) -> ExperimentEvidence:
    root.mkdir(exist_ok=True)
    action: dict[str, Any] = {
        "protocol": "mb-exp/1",
        "action": "run_target_agent",
        "scenario_id": world,
        "config": config,
        "faults": faults or [],
    }
    runner = ExperimentRunner(
        sandbox=ApprovedSandbox([json.dumps(action), finish_action()]),
        target=ReferenceTarget(executor),
        root=root,
        sandbox_limits=SANDBOX_LIMITS,
    )
    return runner.run(
        ExperimentSpec(label="fixture", code="emit({})"),
        worlds=(world,),
        max_runtime_seconds=30.0,
        cancel=None,
    )


STALE_6: Faults = [{"kind": "stale_read", "occurrence": 1, "span": 6}]
STALE_2: Faults = [{"kind": "stale_read", "occurrence": 1, "span": 2}]


def trial(
    root: Path,
    *,
    executor: str = "idempotent_retry",
    faults: Faults | None = None,
    condition_id: str = "stale-6",
    config: str = "baseline",
    trial_id: str = "t",
    truncated: int = 0,
) -> TrialRecord:
    evidence = run_experiment(root, executor=executor, faults=faults, config=config)
    run = evidence.target_runs[0].model_copy(update={"truncated_model_steps": truncated})
    return trial_from_run(
        evidence,
        run,
        root=root,
        suite="causal",
        trial_id=trial_id,
        unit_id=trial_id,
        block=1,
        evidence_intact=True,
        condition_id=condition_id,
    )


class StubCausalExecutor:
    """TEST DOUBLE for the live executor. ``behavior`` chooses the reference script per cell."""

    def __init__(
        self,
        root: Path,
        behavior: Callable[[str, AgentConfigName, Faults], str],
        *,
        remaining: float = 10.0,
        truncate: Callable[[str], int] = lambda _: 0,
        refuse_after: int | None = None,
    ) -> None:
        self.root = root
        self.behavior = behavior
        self.remaining = remaining
        self.truncate = truncate
        self.refuse_after = refuse_after
        self.calls: list[str] = []

    def run(
        self, *, trial_id: str, world: str, config: AgentConfigName, faults: Faults
    ) -> ExperimentEvidence:
        self.calls.append(trial_id)
        evidence = run_experiment(
            self.root,
            executor=self.behavior(trial_id, config, faults),
            world=world,
            faults=faults,
            config=config.value,
        )
        if self.refuse_after is not None and len(self.calls) > self.refuse_after:
            from moody_blues.contracts.experiment_evidence import ExperimentState

            return evidence.model_copy(
                update={"status": ExperimentState.BUDGET_EXHAUSTED, "target_runs": []}
            )
        steps = self.truncate(trial_id)
        if not steps:
            return evidence
        run = evidence.target_runs[0].model_copy(update={"truncated_model_steps": steps})
        return evidence.model_copy(update={"target_runs": [run]})

    def remaining_usd(self) -> float:
        return self.remaining

    @property
    def reservation_usd(self) -> float:
        return 0.39
