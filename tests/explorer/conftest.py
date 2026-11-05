"""OFFLINE fixtures for the Explorer.

API tests read the real committed recorded bundles. Job tests drive the real ``JobManager``,
worlds, gateway and Oracle with the labeled scripted model and sandbox from the Investigator tests.
They cover the job lifecycle; they say nothing about model behavior or about containment.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moody_blues.api.app import create_app
from moody_blues.contracts.investigation import InvestigationLimits, InvestigationRequest
from moody_blues.experiments.target import ReferenceTarget, TargetPort
from moody_blues.explorer.jobs import WorkflowFactory
from moody_blues.explorer.missions import Mission
from moody_blues.explorer.paths import REPO_ROOT
from moody_blues.investigator.fixtures import FIXTURE_MODEL, Reply, ScriptedInvestigatorModel
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow
from tests.conftest import FakeSandboxRunner, make_settings
from tests.experiment.conftest import SANDBOX_LIMITS, Step
from tests.investigator.conftest import ApprovedSandbox

TOKEN = "operator-test-token-not-a-real-secret-000"
AUTH = {"authorization": f"Bearer {TOKEN}"}
RECORDED = REPO_ROOT / "evidence" / "recorded"
VIOLATION = "inv_d0bc87de6010"
HONEST = "inv_4e32358d2ff9"
RECOVERY = "inv_8058b370bc59"
NEGATIVE = "inv_c803b47c336a"
INCONCLUSIVE = "inv_5c9f95de6c09"
PRIMARY_RUN = "run_cc34d7a6e314"


def scripted_factory(
    artifacts: Path,
    *,
    replies: Sequence[Reply],
    steps: Sequence[Step],
    target: TargetPort | None = None,
) -> WorkflowFactory:
    def build(mission: Mission, investigation_id: str, cancel: Event) -> InvestigationWorkflow:
        limits = InvestigationLimits(max_experiments=2, max_model_calls=3)
        return InvestigationWorkflow(
            request=InvestigationRequest(
                objective="test objective",
                strategy=mission.strategy,
                tier=mission.tier,
                world_ids=mission.worlds,
                investigator_model=FIXTURE_MODEL,
                target_model="reference",
                limits=limits,
            ),
            runner=ExperimentRunner(
                sandbox=ApprovedSandbox(steps),
                target=target or ReferenceTarget("verify_then_report"),
                root=artifacts / "experiments",
                sandbox_limits=SANDBOX_LIMITS,
            ),
            root=artifacts / "investigations",
            model=InvestigatorModel(
                inference=ScriptedInvestigatorModel(replies),
                evidence="offline_fixture",
                model=FIXTURE_MODEL,
                provider=None,
                spend=None,
                max_completion_tokens=limits.max_completion_tokens,
                temperature=0,
            ),
            investigation_id=investigation_id,
            cancel=cancel,
        )

    return build


def explorer_app(
    tmp: Path,
    *,
    recorded: Path = RECORDED,
    factory: WorkflowFactory | None = None,
    **settings: object,
) -> FastAPI:
    return create_app(
        make_settings(artifacts_dir=tmp, recorded_evidence_dir=recorded, **settings),
        sandbox_runner=FakeSandboxRunner(),
        workflow_factory=factory,
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(explorer_app(tmp_path), raise_server_exceptions=False)


@pytest.fixture
def recorded_copy(tmp_path: Path) -> Path:
    """A private copy of the real export, for tests that damage it."""
    target = tmp_path / "recorded"
    shutil.copytree(RECORDED, target)
    return target
