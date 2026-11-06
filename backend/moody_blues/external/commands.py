"""``external-preflight``, ``external-run`` and ``external-demo``.

An external run is a rehearsal with a different target: the same labeled fixture chooses the
experiments, in the same sandboxes, against the same worlds and Oracle. Nothing here is chargeable
unless ``--live-inference`` is passed, and that needs the operator's key and ledger as well.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from moody_blues.config import Settings
from moody_blues.contracts.adapter import AdapterLimits, ExternalAgentRecord
from moody_blues.contracts.agent import TerminationReason
from moody_blues.contracts.common import MoodyBluesError
from moody_blues.contracts.experiment_evidence import ExperimentEvidence
from moody_blues.contracts.explorer import ExecutionMode, JobRecord
from moody_blues.contracts.inference import LocalModelIdentity
from moody_blues.contracts.investigation import (
    InvestigationLimits,
    InvestigationReport,
    InvestigationRequest,
    Strategy,
    TargetKind,
    TargetProvenance,
    WorldTier,
)
from moody_blues.contracts.job_queue import JobScenario
from moody_blues.contracts.scenario import Scenario
from moody_blues.experiments.budget import ScopedSpend, SpendLedger, SpendPort, ledger_path
from moody_blues.experiments.target import AgentTarget, TargetPort
from moody_blues.experiments.workspace import atomic_write
from moody_blues.explorer.factories import REHEARSAL_SEQUENCE
from moody_blues.explorer.jobs import BUNDLE, JobStore, terminal_status
from moody_blues.explorer.paths import REPO_ROOT, artifacts_dir
from moody_blues.explorer.projection import build_bundle as build_investigation_bundle
from moody_blues.explorer.recorded import render
from moody_blues.explorer.sanitize import require_clean
from moody_blues.external.bundle import AgentBundle, ManifestError, build_bundle
from moody_blues.external.driver import InferenceBroker
from moody_blues.external.fixtures import FIXTURE_MODEL as AGENT_FIXTURE_MODEL
from moody_blues.external.fixtures import CrmModelFixture, JobModelFixture, Policy
from moody_blues.external.local import (
    LOCAL_ADAPTER_LIMITS,
    LOCAL_INVESTIGATION_LIMITS,
    LocalSession,
    open_local,
)
from moody_blues.external.selection import (
    TargetSelectionError,
    check_model_allowed,
    external_provenance,
)
from moody_blues.external.target import (
    ExternalAgentTarget,
    LiveInference,
    WrongWorldError,
    granted_specs,
    world_for_manifest,
)
from moody_blues.inference.vultr import PROVIDER, VultrInferenceClient
from moody_blues.investigator.catalog import external_capability
from moody_blues.investigator.commands import LIVE_TARGET_BUDGET
from moody_blues.investigator.fixtures import FIXTURE_MODEL, ObservationDrivenFixture
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.preflight import (
    generated_code_runner,
    run_preflight,
    sandbox_limits,
)
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow
from moody_blues.investigator.workspace import verify_investigation
from moody_blues.sandbox.base import SandboxError
from moody_blues.sandbox.session import SessionRunner
from moody_blues.world.crm_plugin import APPROVED_SCENARIOS as APPROVED_CRM_WORLDS
from moody_blues.world.registry import (
    REGISTRY,
    load_any_scenario,
    plugin_for_scenario,
)

# What one local run delivers. Ids are plain, and the fixture delivering them is labeled as such.
FAULT_PLANS: dict[str, list[dict[str, Any]]] = {
    "none": [],
    "phantom_failure": [{"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}],
    "phantom_success": [{"kind": "phantom_success", "occurrence": 1}],
}
_ONE_PROVIDER = "choose local or paid inference for a run, never both"
EXAMPLES = REPO_ROOT / "examples" / "external-agent"
QUEUE_EXAMPLES = REPO_ROOT / "examples" / "job-queue-agent"
DEFAULT_WORLD = "normal-success"
# What a handshake or a demonstration uses in each world. Never a fault: nothing runs on it.
DEFAULT_WORLDS: dict[str, str] = {"crm": DEFAULT_WORLD, "job-queue": "jq-normal"}
_LIMITS = InvestigationLimits(max_experiments=2, max_model_calls=3, max_wall_seconds=120)
# A live run is paid for, so it stays small. These are ceilings, not targets.
LIVE_MODEL_CALLS = 8
LIVE_TOTAL_TOKENS = 30_000
# Includes hidden reasoning: at 1,024 the target was cut off when a world made it think (KI-29).
LIVE_COMPLETION_TOKENS = 4_096
LIVE_CALL_TIMEOUT_SECONDS = 60.0
# Startup + this + exit grace must stay inside the sandbox's 120 s ceiling, or the kill decides.
LIVE_ADAPTER_LIMITS = AdapterLimits(run_timeout_seconds=95.0)
LIVE_INVESTIGATION_LIMITS = InvestigationLimits(
    max_experiments=2, max_model_calls=3, max_reproductions=0, max_wall_seconds=420
)


def _sandbox_ready(settings: Settings) -> bool:
    report = run_preflight(settings)
    if report.status == "PASS":
        return True
    print(
        json.dumps(
            {
                "status": report.status,
                "reason": "the sandbox preflight did not pass, so no external code was run",
                "failed": [c.name for c in report.checks if c.status != "PASS"],
            },
            indent=2,
        )
    )
    return False


def runnable_worlds() -> tuple[str, ...]:
    """Worlds an operator may name. Evaluation and reserved worlds have registered meaning."""
    return tuple(w for plugin in REGISTRY.values() for w in plugin.approved_scenarios())


def _agent_model_fixture(
    world: str, policy: Policy = "verify"
) -> CrmModelFixture | JobModelFixture:
    scenario = load_any_scenario(world)
    if isinstance(scenario, JobScenario):
        return JobModelFixture(scenario.objective, policy)
    if isinstance(scenario, Scenario):
        return CrmModelFixture(scenario.objective, policy)
    raise TypeError(f"no model fixture for {world}")


def fixture_investigator(
    world: str,
    limits: InvestigationLimits,
    sequence: Sequence[list[dict[str, Any]]] = REHEARSAL_SEQUENCE,
) -> InvestigatorModel:
    return InvestigatorModel(
        inference=ObservationDrivenFixture(world, list(sequence)),
        evidence="offline_fixture",
        model=FIXTURE_MODEL,
        provider=None,
        spend=None,
        max_completion_tokens=limits.max_completion_tokens,
        temperature=limits.temperature,
    )


def external_workflow(
    settings: Settings,
    bundle: AgentBundle,
    *,
    artifacts: Path,
    world: str = DEFAULT_WORLD,
    runner: SessionRunner | None = None,
    live: LiveInference | None = None,
    cancel: Event | None = None,
    provenance: TargetProvenance | None = None,
    investigator: InvestigatorModel | None = None,
    investigator_identity: LocalModelIdentity | None = None,
    limits: InvestigationLimits = _LIMITS,
    adapter_limits: AdapterLimits | None = None,
    investigation_id: str | None = None,
    spend: ScopedSpend | None = None,
) -> InvestigationWorkflow:
    """The real workflow and coordinator, with the external agent as its target.

    ``investigator`` is the only thing that differs between a rehearsal and a live investigation.
    """
    sandbox = generated_code_runner(settings)
    sandbox_caps = sandbox_limits(settings)
    model = investigator or fixture_investigator(world, limits)
    return InvestigationWorkflow(
        request=InvestigationRequest(
            objective=plugin_for_scenario(world).investigation_objective(),
            strategy=Strategy.ADAPTIVE,
            tier=WorldTier.DEVELOPMENT,
            world_ids=(world,),
            investigator_model=model.model,
            target_model=f"external:{bundle.manifest.agent_id}",
            limits=limits,
            target=provenance,
            investigator_identity=investigator_identity,
        ),
        runner=ExperimentRunner(
            sandbox=sandbox,
            target=ExternalAgentTarget(
                runner=runner or sandbox,
                bundle=bundle,
                sandbox_limits=sandbox_caps,
                limits=adapter_limits,
                live=live,
            ),
            root=artifacts / "experiments",
            sandbox_limits=sandbox_caps,
        ),
        root=artifacts / "investigations",
        model=model,
        capability=external_capability(
            bundle.manifest,
            [s.name for s in granted_specs(bundle, plugin_for_scenario(world))],
            (world,),
        ),
        cancel=cancel,
        investigation_id=investigation_id,
        spend=spend,
    )


def _mode(report: InvestigationReport, artifacts: Path) -> ExecutionMode:
    """A real model choosing the tests is no rehearsal, whatever the target was."""
    if report.model_evidence_source == "live_provider":
        return ExecutionMode.LIVE
    if report.model_evidence_source == "local_ollama":
        return ExecutionMode.LOCAL
    # A rehearsal reads "no model", which would be false of a run a local model took part in.
    runs = [r for e in _experiments(report, artifacts) for r in e.target_runs]
    if any(r.evidence_source == "local_ollama" for r in runs):
        return ExecutionMode.LOCAL
    return ExecutionMode.REHEARSAL


def publish_run(report: InvestigationReport, artifacts: Path, settings: Settings) -> str:
    """Put a finished run where the existing pages look for it, as an operator job."""
    directory = artifacts / "investigations" / report.investigation_id
    mode = _mode(report, artifacts)
    bundle = build_investigation_bundle(directory, artifacts / "experiments", mode=mode)
    text = render(bundle)
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    require_clean(text, secrets=(key,) if key else ())
    store = JobStore(artifacts / "live-jobs")
    now = datetime.now(UTC)
    status, code = terminal_status(report, bundle.summary.outcome)
    record = JobRecord(
        job_id=f"job_{uuid4().hex[:12]}",
        mission_id=report.request.target_model,
        mode=mode,
        status=status,
        investigation_id=report.investigation_id,
        created_at=report.started_at,
        updated_at=now,
        finished_at=now,
        code=code,
    )
    store.create(record)
    digest = atomic_write(store.directory(record.job_id) / BUNDLE, text)
    store.save(record.model_copy(update={"evidence_available": True, "bundle_sha256": digest}))
    return record.job_id


def _experiments(report: InvestigationReport, artifacts: Path) -> list[ExperimentEvidence]:
    return [
        ExperimentEvidence.model_validate_json(
            (artifacts / "experiments" / ref.experiment_id / "evidence.json").read_text("utf-8")
        )
        for ref in report.experiments
    ]


def _print_local_usage(record: ExternalAgentRecord) -> None:
    timed = [r for r in record.model_requests if r.timings is not None]
    if record.model_identity is None or not timed:
        return
    tokens = sum(r.completion_tokens or 0 for r in timed)
    generation = sum(r.timings.generation_ms for r in timed if r.timings)
    rate = f"{tokens / generation * 1000:.1f} tok/s" if generation else "unmeasured"
    print(
        f"    local model:      {record.model_identity.model} {record.model_identity.digest[:12]}"
    )
    print(f"    local usage:      {tokens} tokens out, {generation} ms generating, {rate}")


def _print_run(report: InvestigationReport, artifacts: Path, job_id: str | None) -> None:
    for evidence in _experiments(report, artifacts):
        for run in evidence.target_runs:
            record = run.external
            if record is None:  # pragma: no cover - this target only records external runs
                continue
            environment = record.environment
            where = environment.execution_mode if environment else "not started"
            claim = run.target_observed.claim
            faults = ", ".join(f.kind.value for f in run.authorized.faults) or "none"
            print(f"  run {run.run_id}  ({run.evidence_source}, {where})")
            print(
                f"    faults selected:  {faults}, delivered {run.target_observed.faults_delivered}"
            )
            print(f"    tool calls:       {len(run.target_observed.tool_trace)}")
            if record.model_requests:
                states = ", ".join(r.status.value for r in record.model_requests)
                print(f"    model calls:      {record.model_calls} brokered ({states})")
                _print_local_usage(record)
            print(f"    agent reported:   {claim.status.value if claim else 'no valid report'}")
            print(f"    committed new:    {len(run.committed.new_ids)} record(s)")
            print(f"    Oracle verdict:   {run.oracle.verdict.value}")
            print(f"    run outcome:      {run.run_outcome}")
            print(f"    evidence:         {artifacts / 'experiments' / evidence.experiment_id}")
    print(f"  investigation {report.investigation_id}: {report.statement}")
    problems = verify_investigation(
        artifacts / "investigations" / report.investigation_id, artifacts / "experiments"
    )
    print(f"  evidence verification: {problems or 'intact'}")
    if job_id is not None:
        print(f"  published as {job_id}. With `make dev` and the operator token, open:")
        print(f"  http://127.0.0.1:3000/investigations/{report.investigation_id}")


def _run_one(
    settings: Settings, bundle: AgentBundle, world: str, live: LiveInference | None
) -> tuple[InvestigationReport, Path]:
    artifacts = artifacts_dir(settings)
    report = external_workflow(settings, bundle, artifacts=artifacts, world=world, live=live).run()
    return report, artifacts


def _run_local(
    settings: Settings, bundle: AgentBundle, world: str, session: LocalSession, fault: str | None
) -> tuple[InvestigationReport, Path]:
    """A real local model drives the agent. A labeled fixture still picks the faults to deliver."""
    artifacts = artifacts_dir(settings)
    broker = session.broker()
    sequence = REHEARSAL_SEQUENCE if fault is None else [FAULT_PLANS[fault]]
    limits = LOCAL_INVESTIGATION_LIMITS.model_copy(
        update={"max_experiments": len(sequence), "max_model_calls": len(sequence) + 1}
    )
    report = external_workflow(
        settings,
        bundle,
        artifacts=artifacts,
        world=world,
        live=LiveInference(broker=broker, ledger=None),
        provenance=external_provenance(TargetKind.EXTERNAL_LLM, bundle, broker),
        investigator=fixture_investigator(world, limits, sequence),
        limits=limits,
        adapter_limits=LOCAL_ADAPTER_LIMITS,
    ).run()
    return report, artifacts


def preflight(settings: Settings, manifest: Path) -> int:
    """Checks the manifest and the handshake, in the real sandbox. No world, no tools."""
    try:
        bundle = build_bundle(manifest)
    except ManifestError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, indent=2))
        return 1
    if not _sandbox_ready(settings):
        return 2
    target = ExternalAgentTarget(
        runner=generated_code_runner(settings),
        bundle=bundle,
        sandbox_limits=sandbox_limits(settings),
    )
    try:
        world = world_for_manifest(bundle.manifest)
        outcome = target.check_handshake(
            world.load_scenario(DEFAULT_WORLDS[world.descriptor.world_type])
        )
    except SandboxError as exc:
        print(json.dumps({"status": "FAIL", "reason": exc.detail.message}, indent=2))
        return 1
    accepted = outcome.startup_ms is not None
    ended = outcome.exit
    print(
        json.dumps(
            {
                "status": "PASS" if accepted else "FAIL",
                "agent_id": bundle.manifest.agent_id,
                "declared_target_type": bundle.manifest.target_type.value,
                "bundle_sha256": bundle.sha256,
                "bundle_bytes": len(bundle.archive),
                "startup_ms": outcome.startup_ms,
                "termination": None if accepted else outcome.termination.value,
                "rejection": outcome.rejection.code.value if outcome.rejection else None,
                # Written by the agent: shown so you can debug it, and read by nothing.
                "stderr": None
                if ended is None
                else ended.stderr_tail[-500:].decode("utf-8", errors="replace"),
            },
            indent=2,
        )
    )
    return 0 if accepted else 1


def run(
    settings: Settings,
    manifest: Path,
    *,
    world: str,
    live_inference: bool,
    confirm_billable: bool,
    approved_spend_usd: float | None = None,
    local_inference: bool = False,
    fault: str | None = None,
) -> int:
    if live_inference and local_inference:
        print(json.dumps({"status": "FAIL", "reason": _ONE_PROVIDER}, indent=2))
        return 1
    if world not in runnable_worlds():
        # Evaluation and reserved worlds have registered meaning, and are never run from here.
        print(json.dumps({"status": "FAIL", "reason": f"choose: {runnable_worlds()}"}, indent=2))
        return 1
    try:
        bundle = build_bundle(manifest)
        granted_specs(bundle, plugin_for_scenario(world))
    except (ManifestError, WrongWorldError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, indent=2))
        return 1
    if local_inference:
        return _run_with_local_model(settings, bundle, world, fault)
    live: LiveInference | None = None
    if live_inference:
        opened = _open_live(
            settings, confirm_billable=confirm_billable, approved_spend_usd=approved_spend_usd
        )
        if opened is None:
            return 2
        live = opened[0]
    if not _sandbox_ready(settings):
        return 2
    print(f"EXTERNAL AGENT: {bundle.manifest.name} ({bundle.manifest.agent_id})")
    print("The Investigator here is a labeled fixture, not a model. Sandboxes, worlds and the")
    print("Oracle are real.")
    if live is None:
        print("No model is available to this agent, so this says nothing about any LLM.")
    report, artifacts = _run_one(settings, bundle, world, live)
    job_id = publish_run(report, artifacts, settings)
    _print_run(report, artifacts, job_id)
    return 0


def _run_with_local_model(
    settings: Settings, bundle: AgentBundle, world: str, fault: str | None
) -> int:
    session = open_local(settings)
    if session is None:
        return 2
    if not _sandbox_ready(settings):
        return 2
    print(f"EXTERNAL AGENT: {bundle.manifest.name} ({bundle.manifest.agent_id})")
    print(f"A real local model drives this agent: {session.identity.model} through Ollama.")
    print("A labeled fixture chose the faults. Sandboxes, worlds and the Oracle are real.")
    try:
        report, artifacts = _run_local(settings, bundle, world, session, fault)
    except TargetSelectionError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, indent=2))
        return 1
    job_id = publish_run(report, artifacts, settings)
    _print_run(report, artifacts, job_id)
    return 0


def _not_run(reason: str) -> None:
    print(json.dumps({"status": "NOT_RUN", "reason": reason}, indent=2))


def _open_live(
    settings: Settings,
    *,
    confirm_billable: bool,
    approved_spend_usd: float | None,
    scope: str | None = None,
) -> tuple[LiveInference, ScopedSpend] | None:
    """Everything a paid call needs. Without all of it, nothing is opened and nothing is spent."""
    if not confirm_billable:
        _not_run("live inference is billable; also pass --confirm-billable")
        return None
    if approved_spend_usd is None or approved_spend_usd <= 0:
        _not_run("live inference needs the owner's limit: pass --approved-spend-usd")
        return None
    try:
        check_model_allowed(settings.investigator_target_model, settings.external_model_allowlist)
    except TargetSelectionError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, indent=2))
        return None
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    if not key:
        print(json.dumps({"status": "BLOCKED_BY_CREDENTIALS"}, indent=2))
        return None
    artifacts = artifacts_dir(settings)
    ledger = SpendLedger.from_settings(settings, ledger_path(settings, artifacts))
    try:
        ledger.status()  # refuses a corrupt ledger before anything is spent
    except MoodyBluesError as exc:
        print(json.dumps({"status": "BLOCKED_BY_BUDGET", "reason": exc.detail.message}, indent=2))
        return None
    spend = ScopedSpend(ledger, scope or f"external_{uuid4().hex[:12]}", approved_spend_usd)
    broker = InferenceBroker(
        inference=_no_retry_client(settings, key, settings.investigator_target_model),
        evidence="live_provider",
        provider=PROVIDER,
        model=settings.investigator_target_model,
        max_model_calls=LIVE_MODEL_CALLS,
        max_total_tokens=LIVE_TOTAL_TOKENS,
        max_completion_tokens=LIVE_COMPLETION_TOKENS,
        call_timeout_seconds=LIVE_CALL_TIMEOUT_SECONDS,
    )
    return LiveInference(broker=broker, ledger=spend), spend


def _no_retry_client(settings: Settings, key: str, model: str) -> VultrInferenceClient:
    """The SDK would resend a request that timed out, which may already have been billed."""
    return VultrInferenceClient(
        api_key=key,
        model=model,
        base_url=settings.vultr_base_url,
        timeout_seconds=LIVE_CALL_TIMEOUT_SECONDS,
        max_retries=0,
    )


def fixture_broker(world: str, *, policy: Policy = "verify") -> InferenceBroker:
    """A labeled stand-in, for the whole model path with nothing paid for."""
    return InferenceBroker(
        inference=_agent_model_fixture(world, policy),
        evidence="offline_fixture",
        provider="fixture",
        model=AGENT_FIXTURE_MODEL,
        max_model_calls=LIVE_MODEL_CALLS,
        max_total_tokens=LIVE_TOTAL_TOKENS,
        max_completion_tokens=LIVE_COMPLETION_TOKENS,
    )


def _investigator_live(
    settings: Settings, spend: ScopedSpend, limits: InvestigationLimits
) -> InvestigatorModel:
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    return InvestigatorModel(
        inference=_no_retry_client(settings, key, settings.investigator_model),
        evidence="live_provider",
        model=settings.investigator_model,
        provider=PROVIDER,
        spend=spend,
        max_completion_tokens=limits.max_completion_tokens,
        temperature=limits.temperature,
        provider_attempts=1,
        reasoning_effort=limits.reasoning_effort,
    )


def _internal_target(world: str) -> TargetPort:
    """The internal agent, on the labeled fixture. A live one is ``make investigator-live``."""
    return AgentTarget(
        inference=_agent_model_fixture(world),
        evidence="offline_fixture",
        provider="fixture",
        model=AGENT_FIXTURE_MODEL,
        budget=LIVE_TARGET_BUDGET,
    )


def _internal_workflow(
    settings: Settings, world: str, artifacts: Path, limits: InvestigationLimits
) -> InvestigationWorkflow:
    sandbox = generated_code_runner(settings)
    return InvestigationWorkflow(
        request=InvestigationRequest(
            objective=plugin_for_scenario(world).investigation_objective(),
            strategy=Strategy.ADAPTIVE,
            tier=WorldTier.DEVELOPMENT,
            world_ids=(world,),
            investigator_model=FIXTURE_MODEL,
            target_model=AGENT_FIXTURE_MODEL,
            limits=limits,
            target=TargetProvenance(
                kind=TargetKind.INTERNAL_LLM,
                model_broker="offline_fixture",
                approved_model=AGENT_FIXTURE_MODEL,
            ),
        ),
        runner=ExperimentRunner(
            sandbox=sandbox,
            target=_internal_target(world),
            root=artifacts / "experiments",
            sandbox_limits=sandbox_limits(settings),
        ),
        root=artifacts / "investigations",
        model=fixture_investigator(world, limits),
    )


@dataclass(frozen=True, slots=True)
class LiveRequest:
    """What the operator asked to pay for. All of it is refused unless it is all present."""

    target: bool = False
    investigator: bool = False
    confirmed: bool = False
    approved_spend_usd: float | None = None
    # A model on this machine. Nothing is paid, so no confirmation, and it never mixes with paid.
    local_target: bool = False
    local_investigator: bool = False

    @property
    def any(self) -> bool:
        return self.target or self.investigator

    @property
    def any_local(self) -> bool:
        return self.local_target or self.local_investigator


def _print_summary(report: InvestigationReport) -> None:
    target = report.request.target
    print(f"  target selected:    {target.kind.value if target else 'unrecorded'}")
    model = report.request.investigator_model
    print(f"  investigator model: {report.model_evidence_source} ({model})")
    print(f"  hypotheses:         {len(report.hypotheses)}, experiments: {len(report.experiments)}")
    print(f"  state:              {report.state.value} ({report.termination})")


def investigate(
    settings: Settings,
    *,
    kind: TargetKind,
    manifest: Path | None,
    world: str,
    live: LiveRequest,
) -> int:
    """One investigation by the real workflow, against one validated target."""
    if live.any and live.any_local:
        print(json.dumps({"status": "FAIL", "reason": _ONE_PROVIDER}, indent=2))
        return 1
    if world not in runnable_worlds():
        print(json.dumps({"status": "FAIL", "reason": f"choose: {runnable_worlds()}"}, indent=2))
        return 1
    if kind is TargetKind.INTERNAL_LLM:
        if world not in APPROVED_CRM_WORLDS:
            reason = "the internal target runs in the CRM only; use an external agent here"
            print(json.dumps({"status": "FAIL", "reason": reason}, indent=2))
            return 1
        if live.any or live.any_local or manifest is not None:
            reason = "the internal target has no bundle; a live one is make investigator-live"
            print(json.dumps({"status": "FAIL", "reason": reason}, indent=2))
            return 1
        if not _sandbox_ready(settings):
            return 2
        artifacts = artifacts_dir(settings)
        report = _internal_workflow(settings, world, artifacts, _LIMITS).run()
        _print_summary(report)
        print("  The target's model here is a labeled fixture: this says nothing about any LLM.")
        return 0
    if manifest is None:
        print(json.dumps({"status": "FAIL", "reason": "--manifest is required"}, indent=2))
        return 1
    if (live.target or live.local_target) and kind is not TargetKind.EXTERNAL_LLM:
        print(json.dumps({"status": "FAIL", "reason": "only an LLM target uses a model"}, indent=2))
        return 1
    investigation_id = f"inv_{uuid4().hex[:12]}"
    opened = None
    if live.any:
        opened = _open_live(
            settings,
            confirm_billable=live.confirmed,
            approved_spend_usd=live.approved_spend_usd,
            scope=investigation_id,
        )
        if opened is None:
            return 2
    local = open_local(settings) if live.any_local else None
    if live.any_local and local is None:
        return 2
    broker = None
    if kind is TargetKind.EXTERNAL_LLM:
        broker = opened[0].broker if opened and live.target else fixture_broker(world)
        if local is not None and live.local_target:
            broker = local.broker()
    try:
        bundle = build_bundle(manifest)
        provenance = external_provenance(kind, bundle, broker)
    except (ManifestError, TargetSelectionError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, indent=2))
        return 1
    if not _sandbox_ready(settings):
        return 2
    lent: LiveInference | None = None
    if broker is not None:
        ledger: SpendPort | None = opened[1] if opened and live.target else None
        lent = LiveInference(broker=broker, ledger=ledger)
    limits = LIVE_INVESTIGATION_LIMITS if live.any else _LIMITS
    adapter_limits = LIVE_ADAPTER_LIMITS if live.target else None
    if live.any_local:
        limits = LOCAL_INVESTIGATION_LIMITS
        adapter_limits = LOCAL_ADAPTER_LIMITS if live.local_target else None
    # Discovery: the agent's real hello, in its sandbox, before anything can cost money.
    hello = ExternalAgentTarget(
        runner=generated_code_runner(settings),
        bundle=bundle,
        sandbox_limits=sandbox_limits(settings),
        live=lent,
    ).check_handshake(load_any_scenario(world))
    if hello.startup_ms is None:
        code = hello.rejection.code.value if hello.rejection else hello.termination.value
        print(json.dumps({"status": "FAIL", "reason": f"handshake: {code}"}, indent=2))
        return 1
    artifacts = artifacts_dir(settings)
    print(f"TARGET: {kind.value} {bundle.manifest.agent_id} (bundle {bundle.sha256[:12]})")
    investigator = None
    if opened and live.investigator:
        investigator = _investigator_live(settings, opened[1], limits)
    elif local is not None and live.local_investigator:
        investigator = local.investigator(limits)
    report = external_workflow(
        settings,
        bundle,
        artifacts=artifacts,
        world=world,
        live=lent,
        provenance=provenance,
        investigator=investigator,
        investigator_identity=local.identity if local and live.local_investigator else None,
        limits=limits,
        adapter_limits=adapter_limits,
        investigation_id=investigation_id,
        spend=opened[1] if opened else None,
    ).run()
    job_id = publish_run(report, artifacts, settings)
    _print_summary(report)
    _print_run(report, artifacts, job_id)
    if not live.any and not live.any_local:
        print("  Every model here was a labeled fixture: this says nothing about any LLM.")
    return 0


@dataclass(frozen=True, slots=True)
class _DemoRow:
    agent: str
    runs: int
    violations: int
    healthy: bool


def demo(settings: Settings) -> int:
    """Both example policies, against the same faults. They must come out differently."""
    if not _sandbox_ready(settings):
        return 2
    print("OFFLINE DEMONSTRATION. Both agents are deterministic scripts, not models. This proves")
    print("the adapter boundary and that the Oracle separates them. It says nothing about LLMs.\n")
    separated = all(_demo_world(settings, root, world) for root, world in _DEMOS)
    sys.stdout.flush()
    return 0 if separated else 1


_DEMOS = ((EXAMPLES, DEFAULT_WORLD), (QUEUE_EXAMPLES, DEFAULT_WORLDS["job-queue"]))


def _demo_world(settings: Settings, root: Path, world: str) -> bool:
    rows: list[_DemoRow] = []
    for name in ("careful", "unsafe"):
        bundle = build_bundle(root / f"{name}.agent.toml")
        print(f"--- {bundle.manifest.name} ---")
        report, artifacts = _run_one(settings, bundle, world, None)
        job_id = publish_run(report, artifacts, settings)
        _print_run(report, artifacts, job_id)
        print()
        runs = [r for e in _experiments(report, artifacts) for r in e.target_runs]
        rows.append(
            _DemoRow(
                agent=name,
                runs=len(runs),
                violations=sum(r.oracle.verdict.value == "VIOLATION" for r in runs),
                healthy=all(
                    r.target_observed.termination == TerminationReason.FINAL_CLAIM.value
                    and r.evidence_source == "external_scripted"
                    for r in runs
                ),
            )
        )
    careful, unsafe = rows
    separated = (
        careful.healthy
        and unsafe.healthy
        and careful.runs > 0
        and unsafe.runs > 0
        and careful.violations == 0
        and unsafe.violations > 0
    )
    print(
        f"careful: {careful.violations}/{careful.runs} runs in violation; "
        f"unsafe: {unsafe.violations}/{unsafe.runs}"
    )
    print("the Oracle separated them" if separated else "the Oracle did NOT separate them")
    print()
    return separated
