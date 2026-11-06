"""``make external-bench``: what the adapter costs, measured in the real sandbox.

Not a test. Prints JSON, and writes nothing to the repository. Run it alone: anything else running
on the Docker VM moves these numbers.
"""

from __future__ import annotations

import json
import resource
import statistics
import tempfile
import time
from pathlib import Path

from moody_blues.config import Settings
from moody_blues.contracts.adapter import AdapterLimits
from moody_blues.contracts.agent import AgentConfigName
from moody_blues.experiments.target import ReferenceTarget, TargetRequest
from moody_blues.external.bundle import build_bundle
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.investigator.preflight import generated_code_runner, sandbox_limits
from moody_blues.world.scenarios import load_scenario
from tests.external.conftest import EXAMPLES, fixture_manifest

RUNS = 10


def request(root: Path, scenario: str = "phantom-failure") -> TargetRequest:
    return TargetRequest(
        scenario=load_scenario(scenario),
        config=AgentConfigName.BASELINE,
        world_root=root,
        max_wall_seconds=60,
        cancel=None,
    )


def main() -> None:
    settings = Settings()
    runner = generated_code_runner(settings)
    limits = sandbox_limits(settings)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = ExternalAgentTarget(
            runner=runner,
            bundle=build_bundle(EXAMPLES / "careful.agent.toml"),
            sandbox_limits=limits,
        )
        before_containers = len(runner.list_sandbox_containers())
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        startups: list[int] = []
        walls: list[int] = []
        report_bytes: list[int] = []
        for index in range(RUNS):
            world = root / f"w{index}"
            world.mkdir()
            result = target.run(request(world))
            assert result.external is not None
            assert result.external.startup_ms is not None
            startups.append(result.external.startup_ms)
            walls.append(result.wall_ms)
            report_bytes.append(len(json.dumps(result.full_report)))
        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        reference = ReferenceTarget("verify_then_report")
        started = time.perf_counter()
        world = root / "reference"
        world.mkdir()
        reference.run(request(world))
        reference_ms = (time.perf_counter() - started) * 1000

        measures = ExternalAgentTarget(
            runner=runner,
            bundle=build_bundle(fixture_manifest(root, "Measures")),
            sandbox_limits=limits,
            limits=AdapterLimits(max_tool_calls=100, max_rejected_calls=0),
        )
        world = root / "measures"
        world.mkdir()
        inside = measures.run(request(world, "clean-negative-control"))
    print(
        json.dumps(
            {
                "runs": RUNS,
                "agent": "acme-crm-careful, phantom-failure",
                "startup_ms": {
                    "median": statistics.median(startups),
                    "min": min(startups),
                    "max": max(startups),
                },
                "total_run_ms": {
                    "median": statistics.median(walls),
                    "min": min(walls),
                    "max": max(walls),
                },
                "reference_executor_same_scenario_ms": round(reference_ms, 1),
                "report_bytes_median": statistics.median(report_bytes),
                "host_rss_growth_kb_over_runs": (rss_after - rss_before) // 1024,
                "containers_left_behind": len(runner.list_sandbox_containers()) - before_containers,
                "seen_from_inside": inside.claim.message if inside.claim else None,
                "inside_termination": inside.termination,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
