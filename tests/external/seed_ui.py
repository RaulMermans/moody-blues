"""Seeds real external runs for the browser test. Run by frontend/e2e-external, not by pytest.

By default the agents run under the labeled local test double, so that the browser test needs no
Docker. With ``MOODY_E2E_EXTERNAL_DOCKER=1`` they run in the real sandbox, end to end.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from moody_blues.config import Settings
from moody_blues.contracts.investigation import TargetKind
from moody_blues.external.bundle import build_bundle
from moody_blues.external.commands import EXAMPLES, external_workflow, publish_run
from tests.external.test_investigator_target import (
    _investigate,  # pyright: ignore[reportPrivateUsage]
)
from tests.external.test_pipeline import _investigation  # pyright: ignore[reportPrivateUsage]


def main() -> None:
    artifacts = Path(sys.argv[1]).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None, artifacts_dir=artifacts)  # type: ignore[call-arg]
    docker = os.environ.get("MOODY_E2E_EXTERNAL_DOCKER") == "1"
    ids: dict[str, str] = {}
    for name in ("careful", "unsafe"):
        if docker:
            bundle = build_bundle(EXAMPLES / f"{name}.agent.toml")
            report = external_workflow(settings, bundle, artifacts=artifacts).run()
        else:
            report, _ = _investigation(artifacts, name)
        publish_run(report, artifacts, settings)
        ids[name] = report.investigation_id
    # Docker or not, the agent's model here is a labeled fixture.
    bundle = build_bundle(EXAMPLES / "llm.agent.toml")
    report, _ = _investigate(artifacts, bundle, TargetKind.EXTERNAL_LLM, policy="verify")
    publish_run(report, artifacts, settings)
    ids["llm"] = report.investigation_id
    (artifacts / "external-ids.json").write_text(json.dumps(ids), encoding="utf-8")


if __name__ == "__main__":
    main()
