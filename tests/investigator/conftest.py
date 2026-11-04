"""OFFLINE fixtures. The sandbox here is a test double that plays canned stdout, so these tests
cover workflow logic only. The model is scripted. Worlds, gateway and Oracle are real. Generated
code really running in Docker is covered by tests/security/test_generated_code.py.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from threading import Event
from typing import Any

from moody_blues.contracts.investigation import (
    InvestigationLimits,
    InvestigationReport,
    InvestigationRequest,
    Strategy,
    WorldTier,
)
from moody_blues.experiments.budget import ScopedSpend
from moody_blues.experiments.target import ReferenceTarget, TargetPort
from moody_blues.investigator.fixtures import FIXTURE_MODEL, Reply, ScriptedInvestigatorModel
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow
from tests.experiment.conftest import SANDBOX_LIMITS, ScriptedSandbox, Step, finish_action

P = "mb-exp/1"
PF = {"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}
PS = {"kind": "phantom_success", "occurrence": 1}
CODE = "emit({'fixture': True})  # never run: the test double supplies stdout\n"


class ApprovedSandbox(ScriptedSandbox):
    """TEST DOUBLE. Claims the approval only a pinned Docker runner has in production."""

    approved_for_generated_code = True


def run_step(world: str = "normal-success", faults: list[dict[str, Any]] | None = None) -> str:
    action: dict[str, Any] = {
        "protocol": P,
        "action": "run_target_agent",
        "scenario_id": world,
        "config": "baseline",
    }
    if faults is not None:
        action["faults"] = faults
    return json.dumps(action)


def experiment(
    world: str = "normal-success", faults: list[dict[str, Any]] | None = None
) -> list[Step]:
    """The stdout of one well-behaved experiment: run the target, then finish."""
    return [run_step(world, faults), finish_action()]


def request(
    strategy: Strategy = Strategy.ADAPTIVE,
    worlds: tuple[str, ...] = ("normal-success",),
    tier: WorldTier = WorldTier.DEVELOPMENT,
    **limits: Any,
) -> InvestigationRequest:
    return InvestigationRequest(
        objective="test objective",
        strategy=strategy,
        tier=tier,
        world_ids=worlds,
        investigator_model=FIXTURE_MODEL,
        target_model="reference",
        limits=InvestigationLimits(**limits),
    )


class Harness:
    def __init__(
        self,
        root: Path,
        *,
        replies: Sequence[Reply],
        steps: Sequence[Step],
        target: TargetPort | None = None,
        spend: ScopedSpend | None = None,
        cancel: Event | None = None,
        **request_args: Any,
    ) -> None:
        self.request = request(**request_args)
        self.sandbox = ApprovedSandbox(steps)
        self.inference = ScriptedInvestigatorModel(replies)
        self.experiments = root / "experiments"
        self.investigations = root / "investigations"
        self.experiments.mkdir(exist_ok=True)
        self.workflow = InvestigationWorkflow(
            request=self.request,
            runner=ExperimentRunner(
                sandbox=self.sandbox,
                target=target or ReferenceTarget("verify_then_report"),
                root=self.experiments,
                sandbox_limits=SANDBOX_LIMITS,
            ),
            root=self.investigations,
            model=InvestigatorModel(
                inference=self.inference,
                evidence="live_provider" if spend is not None else "offline_fixture",
                model=FIXTURE_MODEL,
                provider=None,
                spend=spend,
                max_completion_tokens=self.request.limits.max_completion_tokens,
                temperature=0,
            ),
            spend=spend,
            cancel=cancel,
            investigation_id=spend.scope if spend is not None else None,
        )

    def run(self) -> InvestigationReport:
        return self.workflow.run()

    def prompt(self, index: int) -> dict[str, Any]:
        return json.loads(str(self.inference.requests[index].messages[-1].content))

    def all_prompts(self) -> str:
        return "\n".join(r.model_dump_json() for r in self.inference.requests)

    def offered(self, index: int) -> list[str]:
        return [t.name for t in self.inference.requests[index].tools]
