"""``external-preflight``, ``external-run`` and ``external-demo``.

An external run is a rehearsal with a different target: the same labeled fixture chooses the
experiments, in the same sandboxes, against the same worlds and Oracle. Nothing here is chargeable
unless ``--live-inference`` is passed, and that needs the operator's key and ledger as well.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from moody_blues.config import Settings
from moody_blues.contracts.adapter import AdapterLimits
from moody_blues.contracts.agent import TerminationReason
from moody_blues.contracts.common import MoodyBluesError
from moody_blues.contracts.experiment_evidence import ExperimentEvidence
from moody_blues.contracts.explorer import ExecutionMode, JobRecord
from moody_blues.contracts.investigation import (
    InvestigationLimits,
    InvestigationReport,
    InvestigationRequest,
    Strategy,
    TargetKind,
    TargetProvenance,
    WorldTier,
)
from moody_blues.experiments.budget import ScopedSpend, SpendLedger, SpendPort, ledger_path
from moody_blues.experiments.protocol import APPROVED_SCENARIOS
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
from moody_blues.external.fixtures import CrmModelFixture, Policy
from moody_blues.external.selection import (
    TargetSelectionError,
    check_model_allowed,
    external_provenance,
)
from moody_blues.external.target import ExternalAgentTarget, LiveInference, granted_specs
from moody_blues.inference.vultr import PROVIDER, VultrInferenceClient
from moody_blues.investigator.catalog import external_capability
from moody_blues.investigator.commands import DEFAULT_OBJECTIVE, LIVE_TARGET_BUDGET
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
from moody_blues.world.scenarios import load_scenario

EXAMPLES = REPO_ROOT / "examples" / "external-agent"
DEFAULT_WORLD = "normal-success"
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


def fixture_investigator(world: str, limits: InvestigationLimits) -> InvestigatorModel:
    return InvestigatorModel(
        inference=ObservationDrivenFixture(world, REHEARSAL_SEQUENCE),
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
            objective=DEFAULT_OBJECTIVE,
            strategy=Strategy.ADAPTIVE,
            tier=WorldTier.DEVELOPMENT,
            world_ids=(world,),
            investigator_model=model.model,
            target_model=f"external:{bundle.manifest.agent_id}",
            limits=limits,
            target=provenance,
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
            bundle.manifest, [s.name for s in granted_specs(bundle)], (world,)
        ),
        cancel=cancel,
        investigation_id=investigation_id,
        spend=spend,
    )


def publish_run(report: InvestigationReport, artifacts: Path, settings: Settings) -> str:
    """Put a finished run where the existing pages look for it, as an operator job."""
    directory = artifacts / "investigations" / report.investigation_id
    bundle = build_investigation_bundle(
        directory, artifacts / "experiments", mode=ExecutionMode.REHEARSAL
    )
    text = render(bundle)
    key = settings.vultr_api_key.get_secret_value() if settings.vultr_api_key else ""
    require_clean(text, secrets=(key,) if key else ())
    store = JobStore(artifacts / "live-jobs")
    now = datetime.now(UTC)
    status, code = terminal_status(report, bundle.summary.outcome)
    record = JobRecord(
        job_id=f"job_{uuid4().hex[:12]}",
        mission_id=report.request.target_model,
        mode=ExecutionMode.REHEARSAL,
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
            print(f"    agent reported:   {claim.status.value if claim else 'no valid report'}")
            print(f"    committed new:    {len(run.committed.new_customer_ids)} record(s)")
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
        outcome = target.check_handshake(load_scenario(DEFAULT_WORLD))
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
) -> int:
    if world not in APPROVED_SCENARIOS:
        # Evaluation and reserved worlds have registered meaning, and are never run from here.
        print(json.dumps({"status": "FAIL", "reason": f"choose: {APPROVED_SCENARIOS}"}, indent=2))
        return 1
    try:
        bundle = build_bundle(manifest)
    except ManifestError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, indent=2))
        return 1
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
        inference=CrmModelFixture(load_scenario(world).objective, policy),
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
        inference=CrmModelFixture(load_scenario(world).objective),
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
            objective=DEFAULT_OBJECTIVE,
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

    @property
    def any(self) -> bool:
        return self.target or self.investigator


def _print_summary(report: InvestigationReport) -> None:
    target = report.request.target
    print(f"  target selected:    {target.kind.value if target else 'unrecorded'}")
    print(
        f"  investigator model: {report.model_evidence_source} ({report.request.investigator_model})"
    )
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
    if world not in APPROVED_SCENARIOS:
        print(json.dumps({"status": "FAIL", "reason": f"choose: {APPROVED_SCENARIOS}"}, indent=2))
        return 1
    if kind is TargetKind.INTERNAL_LLM:
        if live.any or manifest is not None:
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
    if live.target and kind is not TargetKind.EXTERNAL_LLM:
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
    broker = None
    if kind is TargetKind.EXTERNAL_LLM:
        broker = opened[0].broker if opened and live.target else fixture_broker(world)
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
    # Discovery: the agent's real hello, in its sandbox, before anything can cost money.
    hello = ExternalAgentTarget(
        runner=generated_code_runner(settings),
        bundle=bundle,
        sandbox_limits=sandbox_limits(settings),
        live=lent,
    ).check_handshake(load_scenario(world))
    if hello.startup_ms is None:
        code = hello.rejection.code.value if hello.rejection else hello.termination.value
        print(json.dumps({"status": "FAIL", "reason": f"handshake: {code}"}, indent=2))
        return 1
    artifacts = artifacts_dir(settings)
    print(f"TARGET: {kind.value} {bundle.manifest.agent_id} (bundle {bundle.sha256[:12]})")
    report = external_workflow(
        settings,
        bundle,
        artifacts=artifacts,
        world=world,
        live=lent,
        provenance=provenance,
        investigator=_investigator_live(settings, opened[1], limits)
        if opened and live.investigator
        else None,
        limits=limits,
        adapter_limits=adapter_limits,
        investigation_id=investigation_id,
        spend=opened[1] if opened else None,
    ).run()
    job_id = publish_run(report, artifacts, settings)
    _print_summary(report)
    _print_run(report, artifacts, job_id)
    if not live.any:
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
    rows: list[_DemoRow] = []
    for name in ("careful", "unsafe"):
        bundle = build_bundle(EXAMPLES / f"{name}.agent.toml")
        print(f"--- {bundle.manifest.name} ---")
        report, artifacts = _run_one(settings, bundle, DEFAULT_WORLD, None)
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
    sys.stdout.flush()
    return 0 if separated else 1
