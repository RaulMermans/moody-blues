"""Run as a child process by the crash test, which SIGKILLs it mid-run.

Not a test module. A real external agent in a real container commits a row through the gateway and
then hangs, and this process, its coordinator, is killed while that run is open.
"""

from __future__ import annotations

import sys
from pathlib import Path

from moody_blues.contracts.experiment_evidence import ExperimentLimits, ExperimentSpec
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.external.bundle import build_bundle
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.investigator.preflight import generated_code_runner
from tests.conftest import limits, make_settings

RUN_TARGET = (
    'emit({"protocol": "mb-exp/1", "action": "run_target_agent",'
    ' "scenario_id": "normal-success", "config": "baseline"})\n'
)


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
    ).run(ExperimentSpec(label="crash", code=RUN_TARGET))


if __name__ == "__main__":
    main()
