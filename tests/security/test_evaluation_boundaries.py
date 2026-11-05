"""REAL Docker. The registered evaluation runs through the same pinned sandbox and coordinator.

Reference scripts stand in for the agent, so these say nothing about any model. What they show is
that the evaluation added no new way out: developer probes and hostile generated programs both
run contained, on the digest-pinned image, and a registered seed really produces its outcome.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.experiment_evidence import (
    ExperimentAuthorship,
    ExperimentSpec,
    GenerationRecord,
)
from moody_blues.evaluation.adaptation import run_seed
from moody_blues.evaluation.manifest import Manifest, build_manifest
from moody_blues.evaluation.trials import behavior_of
from moody_blues.experiments.programs import probe_program
from moody_blues.experiments.target import ReferenceTarget
from moody_blues.investigator.preflight import generated_code_runner, sandbox_limits
from moody_blues.investigator.workflow import ExperimentRunner

pytestmark = pytest.mark.docker


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def manifest(settings: Settings) -> Manifest:
    return build_manifest(settings, settled_usd=0.0)


def _runner(settings: Settings, root: Path, executor: str) -> ExperimentRunner:
    return ExperimentRunner(
        sandbox=generated_code_runner(settings),
        target=ReferenceTarget(executor),
        root=root,
        sandbox_limits=sandbox_limits(settings),
    )


def test_the_causal_probe_runs_in_the_pinned_sandbox(
    settings: Settings, manifest: Manifest, tmp_path: Path
) -> None:
    faults = next(c for c in manifest.causal.conditions if c.condition_id == "stale-6").faults
    evidence = _runner(settings, tmp_path, "verify_then_report").run(
        ExperimentSpec(
            label="probe",
            code=probe_program(
                scenario_id=manifest.causal.world,
                config="baseline",
                looking_for="duplicate_side_effect",
                faults=faults,
            ),
        ),
        worlds=(manifest.causal.world,),
        max_runtime_seconds=120.0,
        cancel=None,
    )
    [run] = evidence.target_runs
    assert run.evidence_source == "reference_executor"
    assert behavior_of(run).stale_reads_delivered >= 1
    executions = [e for step in evidence.steps for e in step.sandbox]
    assert all(not e.network_enabled for e in executions)
    assert all("sha256:" in e.image for e in executions)


def test_registered_seeds_produce_their_outcomes_in_real_containers(
    settings: Settings, manifest: Manifest, tmp_path: Path
) -> None:
    suite = manifest.adaptation
    for case in suite.cases:
        for branch in case.branches:
            seed = run_seed(
                case,
                branch,
                runner=_runner(settings, tmp_path, branch.executor),
                worlds=suite.worlds,
            )
            assert seed.branch == branch.outcome


HOSTILE = """\
import os, socket, pathlib
seen = {
    "socket": pathlib.Path("/var/run/docker.sock").exists(),
    "secrets": [k for k in os.environ if "VULTR" in k or "MOODY" in k],
    "world": list(pathlib.Path("/").glob("**/*.sqlite"))[:1],
}
try:
    socket.create_connection(("1.1.1.1", 53), timeout=1)
    seen["network"] = True
except OSError:
    seen["network"] = False
emit({"protocol": "mb-exp/1", "action": "finish_experiment", "conclusion": "inconclusive",
      "summary": repr(seen)})
"""


def test_a_generated_program_in_a_reserved_world_sees_nothing(
    settings: Settings, manifest: Manifest, tmp_path: Path
) -> None:
    evidence = _runner(settings, tmp_path, "verify_then_report").run(
        ExperimentSpec(
            label="hostile",
            code=HOSTILE,
            authorship=ExperimentAuthorship.MODEL_GENERATED,
            generation=GenerationRecord(
                proposal_id="prop_1", model="fixture", evidence_source="offline_fixture"
            ),
        ),
        worlds=manifest.adaptation.worlds,
        max_runtime_seconds=60.0,
        cancel=None,
    )
    assert evidence.sandbox_supplied is not None
    summary = evidence.sandbox_supplied.summary
    assert "'socket': False" in summary
    assert "'secrets': []" in summary
    assert "'world': []" in summary
    assert "'network': False" in summary
