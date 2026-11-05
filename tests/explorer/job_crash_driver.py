"""Run as a child process by the restart test, which SIGKILLs it mid-run.

Not a test module. It starts a real job whose target commits a real row through the gateway and
then blocks, as a run would between two model calls.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from moody_blues.contracts.world import ToolName
from moody_blues.experiments.target import TargetRequest, TargetResult
from moody_blues.explorer.jobs import JobManager, JobStore
from moody_blues.explorer.missions import find_mission
from moody_blues.investigator.fixtures import conclude, propose
from moody_blues.world.engine import World
from tests.explorer.conftest import scripted_factory
from tests.investigator.conftest import CODE, PF, experiment


class CommitThenHang:
    def run(self, request: TargetRequest) -> TargetResult:
        world = World(request.scenario, root_dir=request.world_root)
        customer = request.scenario.objective.customer
        world.gateway.call(
            ToolName.CREATE_CUSTOMER, {"name": customer.name, "email": customer.email}
        )
        print("COMMITTED", flush=True)
        time.sleep(300)
        raise AssertionError("unreachable: the parent kills this process")


def main() -> None:
    root = Path(sys.argv[1])
    factory = scripted_factory(
        root,
        replies=[propose(1, CODE), conclude()],
        steps=experiment(faults=[PF]),
        target=CommitThenHang(),
    )
    jobs = JobManager(JobStore(root / "live-jobs"), artifacts=root, factory=factory)
    mission = find_mission("rehearsal-recovery")
    assert mission is not None
    jobs.start(mission)
    jobs.wait(300)


if __name__ == "__main__":
    main()
