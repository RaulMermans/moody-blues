"""Run as a child process by the crash tests, which SIGKILL it mid-flight.

Not a test module. ``sandbox`` mode leaves a real container running; ``target`` mode commits a
real row through the gateway and then blocks, as a run would between two model calls.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from moody_blues.contracts.experiment_evidence import ExperimentLimits, ExperimentSpec
from moody_blues.contracts.scenario import Scenario
from moody_blues.contracts.world import ToolName
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.experiments.target import ReferenceTarget, TargetRequest, TargetResult
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from moody_blues.world.engine import World
from tests.conftest import limits, make_settings

RUN_TARGET = (
    'emit({"protocol": "mb-exp/1", "action": "run_target_agent",'
    ' "scenario_id": "normal-success", "config": "baseline"})\n'
)
SLEEP = "import time\ntime.sleep(300)\n"


class CommitThenHang:
    def run(self, request: TargetRequest) -> TargetResult:
        assert isinstance(request.scenario, Scenario)
        world = World(request.scenario, root_dir=request.world_root)
        customer = request.scenario.objective.customer
        world.gateway.call(
            ToolName.CREATE_CUSTOMER, {"name": customer.name, "email": customer.email}
        )
        print("COMMITTED", flush=True)
        time.sleep(300)
        raise AssertionError("unreachable: the parent kills this process")


def main() -> None:
    root, mode = Path(sys.argv[1]), sys.argv[2]
    coordinator = ExperimentCoordinator(
        sandbox=DockerSandboxRunner.from_settings(make_settings()),
        target=CommitThenHang() if mode == "target" else ReferenceTarget("trusting"),
        root=root,
        sandbox_limits=limits(),
        limits=ExperimentLimits(step_timeout_seconds=1 if mode == "sandbox" else 10),
    )
    coordinator.run(ExperimentSpec(label=mode, code=SLEEP if mode == "sandbox" else RUN_TARGET))


if __name__ == "__main__":
    main()
