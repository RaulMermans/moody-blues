"""Seeds real runs from both worlds for the browser test. Run by frontend/e2e-worlds, not pytest.

Every record is produced by the real pipeline, with no hand-written evidence. By default agents run
under the labeled local test double; with ``MOODY_E2E_EXTERNAL_DOCKER=1``, in the real sandbox.
Agents are scripts, and the Investigator is a labeled fixture: nothing here is a model.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from moody_blues.config import Settings
from moody_blues.contracts.investigation import InvestigationLimits
from moody_blues.external.bundle import build_bundle
from moody_blues.external.commands import (
    EXAMPLES,
    QUEUE_EXAMPLES,
    external_workflow,
    fixture_investigator,
    publish_run,
)
from tests.external.test_cross_world import _investigate  # pyright: ignore[reportPrivateUsage]
from tests.external.test_pipeline import _investigation  # pyright: ignore[reportPrivateUsage]

NEVER_FIRES = [[{"kind": "phantom_failure", "occurrence": 3, "error_code": "timeout"}]]


def main() -> None:
    artifacts = Path(sys.argv[1]).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None, artifacts_dir=artifacts)  # type: ignore[call-arg]
    docker = os.environ.get("MOODY_E2E_EXTERNAL_DOCKER") == "1"
    ids: dict[str, str] = {}
    for name in ("careful", "unsafe"):
        if docker:
            bundle = build_bundle(QUEUE_EXAMPLES / f"{name}.agent.toml")
            report = external_workflow(
                settings, bundle, artifacts=artifacts, world="jq-normal"
            ).run()
        else:
            report = _investigate(artifacts, name, "jq-normal")
        publish_run(report, artifacts, settings)
        ids[name] = report.investigation_id
    limits = InvestigationLimits(max_experiments=1, max_model_calls=2, max_wall_seconds=120)
    if docker:
        report = external_workflow(
            settings,
            build_bundle(QUEUE_EXAMPLES / "careful.agent.toml"),
            artifacts=artifacts,
            world="jq-normal",
            investigator=fixture_investigator("jq-normal", limits, NEVER_FIRES),
            limits=limits,
        ).run()
    else:
        report = _investigate(artifacts, "careful", "jq-normal", NEVER_FIRES)
    publish_run(report, artifacts, settings)
    ids["not_exercised"] = report.investigation_id
    if docker:
        crm = external_workflow(
            settings, build_bundle(EXAMPLES / "unsafe.agent.toml"), artifacts=artifacts
        ).run()
    else:
        crm, _ = _investigation(artifacts, "unsafe")
    publish_run(crm, artifacts, settings)
    ids["crm"] = crm.investigation_id
    (artifacts / "world-ids.json").write_text(json.dumps(ids), encoding="utf-8")


if __name__ == "__main__":
    main()
