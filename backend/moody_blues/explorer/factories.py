"""Builds the workflow a mission runs. The only place a job touches providers or Docker.

Every check here runs on the worker thread before the investigation starts. A failure raises
``MissionBlockedError`` with a fixed code, and nothing chargeable has happened at that point.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event

from moody_blues.config import Settings
from moody_blues.contracts.common import MoodyBluesError
from moody_blues.contracts.explorer import ExecutionMode
from moody_blues.contracts.investigation import InvestigationRequest
from moody_blues.experiments.budget import PriceCeiling, SpendLedger
from moody_blues.experiments.target import ReferenceTarget
from moody_blues.explorer.jobs import MissionBlockedError, WorkflowFactory
from moody_blues.explorer.missions import Mission
from moody_blues.inference.vultr import VultrInferenceClient
from moody_blues.investigator.commands import DEFAULT_OBJECTIVE, LiveContext, live_workflow
from moody_blues.investigator.fixtures import FIXTURE_MODEL, ObservationDrivenFixture
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.preflight import (
    generated_code_runner,
    run_preflight,
    sandbox_limits,
)
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow

# The same sequence the `investigator-demo` command uses. It is a script, and says so everywhere.
_REHEARSAL_SEQUENCE = [
    [{"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}],
    [{"kind": "phantom_success", "occurrence": 1}],
]


def ledger_for(settings: Settings, artifacts: Path) -> SpendLedger:
    return SpendLedger(
        artifacts / "live-spend" / "ledger.jsonl",
        limit_usd=settings.live_spend_limit_usd,
        prices=PriceCeiling.from_settings(settings),
    )


def _preflight(settings: Settings) -> None:
    if run_preflight(settings).status != "PASS":
        raise MissionBlockedError("sandbox_preflight_failed")


def _rehearsal(
    settings: Settings, mission: Mission, artifacts: Path, investigation_id: str, cancel: Event
) -> InvestigationWorkflow:
    if mission.reference_executor is None:  # pragma: no cover - a catalog error
        raise MissionBlockedError("mission_misconfigured")
    _preflight(settings)
    limits = mission.limits
    return InvestigationWorkflow(
        request=InvestigationRequest(
            objective=DEFAULT_OBJECTIVE,
            strategy=mission.strategy,
            tier=mission.tier,
            world_ids=mission.worlds,
            investigator_model=FIXTURE_MODEL,
            target_model=f"reference:{mission.reference_executor}",
            limits=limits,
        ),
        runner=ExperimentRunner(
            sandbox=generated_code_runner(settings),
            target=ReferenceTarget(mission.reference_executor),
            root=artifacts / "experiments",
            sandbox_limits=sandbox_limits(settings),
        ),
        root=artifacts / "investigations",
        model=InvestigatorModel(
            inference=ObservationDrivenFixture(mission.worlds[0], _REHEARSAL_SEQUENCE),
            evidence="offline_fixture",
            model=FIXTURE_MODEL,
            provider=None,
            spend=None,
            max_completion_tokens=limits.max_completion_tokens,
            temperature=limits.temperature,
        ),
        investigation_id=investigation_id,
        cancel=cancel,
    )


def _live(
    settings: Settings, mission: Mission, artifacts: Path, investigation_id: str, cancel: Event
) -> InvestigationWorkflow:
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    if not key:
        raise MissionBlockedError("provider_not_configured")
    _preflight(settings)
    ledger = ledger_for(settings, artifacts)
    try:
        ledger.status()  # refuses a corrupt ledger before anything is spent
        client = VultrInferenceClient(
            api_key=key,
            model=settings.investigator_model,
            base_url=settings.vultr_base_url,
            timeout_seconds=settings.investigator_timeout_seconds,
            max_retries=settings.investigator_max_retries,
        )
        catalog = client.list_models()  # not chargeable
    except MoodyBluesError as exc:
        raise MissionBlockedError(exc.detail.category.value) from exc
    if {settings.investigator_model, settings.investigator_target_model} - set(catalog):
        raise MissionBlockedError("model_not_in_catalog")
    return live_workflow(
        settings,
        LiveContext(ledger, client),
        strategy=mission.strategy,
        tier=mission.tier,
        worlds=mission.worlds,
        limits=mission.limits,
        investigation_id=investigation_id,
        cancel=cancel,
        artifacts=artifacts,
    )


def default_factory(settings: Settings, artifacts: Path) -> WorkflowFactory:
    def build(mission: Mission, investigation_id: str, cancel: Event) -> InvestigationWorkflow:
        if mission.mode is ExecutionMode.REHEARSAL:
            return _rehearsal(settings, mission, artifacts, investigation_id, cancel)
        return _live(settings, mission, artifacts, investigation_id, cancel)

    return build
