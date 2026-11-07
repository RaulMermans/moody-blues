"""Run as a child process by the queue crash tests.

Not a test module. A real agent in a real container commits a job through the gateway and hangs.
The parent then SIGKILLs this process, or the agent's container, while that run is open.
"""

from __future__ import annotations

import sys
from pathlib import Path

from moody_blues.contracts.experiment_evidence import ExperimentLimits, ExperimentSpec
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.external.bundle import build_bundle
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.investigator.preflight import generated_code_runner
from moody_blues.world.registry import world_plugin
from tests.conftest import limits, make_settings

RUN_TARGET = """\
if EXPERIMENT_INPUT["observations"]:
    emit({"protocol": "mb-exp/1", "action": "finish_experiment",
          "conclusion": "inconclusive", "summary": "done"})
else:
    emit({"protocol": "mb-exp/1", "action": "run_target_agent",
          "scenario_id": "jq-normal", "config": "baseline"})
"""


def main() -> None:
    root, manifest = Path(sys.argv[1]), Path(sys.argv[2])
    runner = generated_code_runner(make_settings())
    ExperimentCoordinator(
        sandbox=runner,
        target=ExternalAgentTarget(
            runner=runner, bundle=build_bundle(manifest), sandbox_limits=limits()
        ),
        root=root,
        sandbox_limits=limits(),
        limits=ExperimentLimits(step_timeout_seconds=10),
        allowed_scenarios=("jq-normal",),
        world=world_plugin("job-queue"),
    ).run(ExperimentSpec(label="queue-crash", code=RUN_TARGET))


if __name__ == "__main__":
    main()
