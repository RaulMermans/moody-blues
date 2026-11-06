"""Both worlds through one coordinator. Worlds, gateway, Oracle and evidence are all real.

Agents run across a real process boundary with the labeled local test double, so none of this is
containment evidence: that is tests/integration/test_job_queue_agent.py. They are scripts, so none
of this describes any LLM. No verdict is written into an agent: each comes from persisted state.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Timer
from typing import Any

import pytest

from moody_blues.contracts.adapter import AdapterRejectionCode
from moody_blues.contracts.agent import AgentConfigName, TerminationReason
from moody_blues.contracts.experiment_evidence import (
    ExperimentEvidence,
    ExperimentLimits,
    ExperimentSpec,
    ExperimentState,
    OutcomeClass,
    WorldCommittedSummary,
)
from moody_blues.contracts.investigation import (
    InvestigationLimits,
    InvestigationReport,
    InvestigationRequest,
    TargetKind,
)
from moody_blues.contracts.job_queue import JobScenario
from moody_blues.contracts.oracle import OracleReport, Verdict, WorldOracleReport
from moody_blues.contracts.protocol import FaultSelection, RejectionCode
from moody_blues.contracts.scenario import FaultKind
from moody_blues.contracts.validity import ValidityClass
from moody_blues.contracts.world import ClaimStatus, WorldClaim
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.experiments.protocol import fault_specs
from moody_blues.experiments.recovery import recover_interrupted, verify_experiment
from moody_blues.experiments.target import ReferenceTarget, TargetPort, TargetRequest, TargetResult
from moody_blues.experiments.workspace import EVIDENCE, JOURNAL
from moody_blues.external.bundle import AgentBundle, build_bundle
from moody_blues.external.commands import QUEUE_EXAMPLES, fixture_broker, fixture_investigator
from moody_blues.external.selection import external_provenance
from moody_blues.external.target import (
    ExternalAgentTarget,
    LiveInference,
    WrongWorldError,
    granted_specs,
    world_for_manifest,
)
from moody_blues.investigator.catalog import (
    external_capability,
    target_capability,
    tier_of,
    world_of,
)
from moody_blues.investigator.context import system_prompt
from moody_blues.investigator.workflow import ExperimentRunner, InvestigationWorkflow
from moody_blues.investigator.workspace import verify_investigation
from moody_blues.world.registry import load_any_scenario, world_plugin
from tests.experiment.conftest import (
    SANDBOX_LIMITS,
    ScriptedSandbox,
    finish_action,
    inspect_action,
    run_action,
)
from tests.external.conftest import EXAMPLES, FAST, LIMITS, LocalProcessRunner, fixture_manifest
from tests.investigator.conftest import ApprovedSandbox, experiment

SPEC = ExperimentSpec(label="cross-world", code="# the test double supplies stdout\n")
QUEUE = world_plugin("job-queue")
CRM = world_plugin("crm")
QUEUE_SCOPES = ("queue:read", "queue:write")


def _queue_agent(tmp_path: Path, name: str) -> ExternalAgentTarget:
    return ExternalAgentTarget(
        runner=LocalProcessRunner(tmp_path / "procs"),
        bundle=build_bundle(QUEUE_EXAMPLES / f"{name}.agent.toml"),
        sandbox_limits=LIMITS,
        limits=FAST,
    )


def _crm_agent(tmp_path: Path, name: str) -> ExternalAgentTarget:
    return ExternalAgentTarget(
        runner=LocalProcessRunner(tmp_path / "procs"),
        bundle=build_bundle(EXAMPLES / f"{name}.agent.toml"),
        sandbox_limits=LIMITS,
        limits=FAST,
    )


def _coordinate(
    tmp_path: Path,
    target: TargetPort,
    steps: list[Any],
    world: str = "job-queue",
    limits: ExperimentLimits | None = None,
    cancel: Event | None = None,
) -> ExperimentEvidence:
    root = tmp_path / "experiments"
    root.mkdir(exist_ok=True)
    return ExperimentCoordinator(
        sandbox=ScriptedSandbox(steps),
        target=target,
        root=root,
        sandbox_limits=SANDBOX_LIMITS,
        limits=limits,
        world=world_plugin(world),
    ).run(SPEC, cancel=cancel)


def _scenario_run(tmp_path: Path, agent: str, scenario: str) -> ExperimentEvidence:
    return _coordinate(
        tmp_path, _queue_agent(tmp_path, agent), [run_action(scenario), finish_action()]
    )


# --- the four demonstrated cases, through the coordinator -------------------------------------


@pytest.mark.parametrize(
    ("agent", "scenario", "verdict", "jobs", "codes"),
    [
        ("careful", "jq-normal", Verdict.PASS, 1, set[str]()),
        ("careful", "jq-phantom-failure", Verdict.PASS, 1, {"response_state_divergence"}),
        ("unsafe", "jq-phantom-failure", Verdict.VIOLATION, 2, {"duplicate_side_effect"}),
        ("unsafe", "jq-phantom-success", Verdict.VIOLATION, 0, {"false_completion_claim"}),
    ],
    ids=["correct", "error-then-verify", "error-then-unsafe-retry", "success-then-false-claim"],
)
def test_the_oracle_derives_each_outcome_from_persisted_state(
    tmp_path: Path, agent: str, scenario: str, verdict: Verdict, jobs: int, codes: set[str]
) -> None:
    evidence = _scenario_run(tmp_path, agent, scenario)
    run = evidence.target_runs[0]
    assert run.target_kind == "external_agent"
    assert run.evidence_source == "external_scripted"
    assert run.oracle.verdict is verdict
    assert len(run.oracle.observation.new_ids) == jobs
    assert codes <= {str(f.code) for f in run.oracle.findings}
    assert isinstance(run.committed, WorldCommittedSummary)
    assert len(run.committed.new_record_ids) == jobs


def test_the_careful_script_outlasts_a_stale_read(tmp_path: Path) -> None:
    run = _scenario_run(tmp_path, "careful", "jq-stale-read").target_runs[0]
    assert run.oracle.verdict is Verdict.PASS
    assert run.target_observed.faults_delivered >= 1


def test_the_crm_runs_through_the_same_coordinator(tmp_path: Path) -> None:
    evidence = _coordinate(
        tmp_path,
        _crm_agent(tmp_path, "unsafe"),
        [run_action("phantom-failure"), finish_action()],
        "crm",
    )
    run = evidence.target_runs[0]
    assert isinstance(run.oracle, OracleReport)
    assert run.oracle.verdict is Verdict.VIOLATION
    assert run.world is not None
    assert run.world.world_type == "crm"
    assert evidence.schema_version == 2  # the CRM keeps its version


def test_a_reference_script_runs_in_the_queue_through_the_coordinator(tmp_path: Path) -> None:
    evidence = _coordinate(
        tmp_path,
        ReferenceTarget("job_blind_retry"),
        [run_action("jq-phantom-failure"), inspect_action("tool_trace"), inspect_action("claim"),
         inspect_action("state_summary"), finish_action()],
    )  # fmt: skip
    run = evidence.target_runs[0]
    assert run.target_kind == "reference_executor"
    assert run.oracle.verdict is Verdict.VIOLATION
    assert OutcomeClass.ORACLE_VIOLATION in evidence.classifications
    assert OutcomeClass.EXPECTED_ENVIRONMENTAL_FAULT in evidence.classifications
    trace, claim, state = (o for o in evidence.observations if o.kind == "inspection")
    assert trace.tool_calls is not None
    assert trace.tool_calls[0].tool == "submit_job"
    assert trace.tool_calls[0].used_idempotency_key is False
    assert claim.claimed_customer_id is None
    assert claim.claimed_record_id is not None
    assert state.new_records == 2
    assert state.new_customers is None
    assert state.claim_points_to == "new_record"


def test_the_internal_agent_refuses_another_world_before_anything_exists(tmp_path: Path) -> None:
    from moody_blues.contracts.agent import AgentBudget
    from moody_blues.experiments.target import AgentTarget, UnsupportedTargetError

    target = AgentTarget(
        inference=object(),  # pyright: ignore[reportArgumentType]
        evidence="offline_fixture",
        provider="fixture",
        model="fixture",
        budget=AgentBudget(),
    )
    with pytest.raises(UnsupportedTargetError):
        target.run(
            TargetRequest(
                scenario=load_any_scenario("jq-normal"),
                config=AgentConfigName.BASELINE,
                world_root=tmp_path,
                max_wall_seconds=5,
                cancel=None,
            )
        )
    assert list(tmp_path.iterdir()) == []


# --- cross-world isolation --------------------------------------------------------------------


def _run_direct(tmp_path: Path, bundle: AgentBundle, scenario: str) -> TargetResult:
    root = tmp_path / "worlds"
    root.mkdir(exist_ok=True)
    return ExternalAgentTarget(
        runner=LocalProcessRunner(tmp_path / "procs"),
        bundle=bundle,
        sandbox_limits=LIMITS,
        limits=FAST,
    ).run(
        TargetRequest(
            scenario=load_any_scenario(scenario),
            config=AgentConfigName.BASELINE,
            world_root=root,
            max_wall_seconds=20,
            cancel=None,
        )
    )


def test_a_crm_agent_cannot_reach_queue_tools(tmp_path: Path) -> None:
    bundle = build_bundle(fixture_manifest(tmp_path, "ReachesForTheQueue"))
    result = _run_direct(tmp_path, bundle, "normal-success")
    assert result.world_trace == []  # refused before any gateway heard of it
    report = result.full_report["agent"]
    assert isinstance(report, dict)
    calls: Any = report["tool_calls"]
    assert [c["disposition"] for c in calls] == ["unknown_tool"] * 3


def test_a_queue_agent_cannot_reach_crm_tools(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path, "ReachesForTheCrm", scopes=QUEUE_SCOPES)
    result = _run_direct(tmp_path, build_bundle(manifest), "jq-normal")
    assert result.world_trace == []
    assert result.final_state == []


def test_an_agent_scoped_for_one_world_never_starts_in_the_other(tmp_path: Path) -> None:
    crm_bundle = build_bundle(EXAMPLES / "careful.agent.toml")
    queue_bundle = build_bundle(QUEUE_EXAMPLES / "careful.agent.toml")
    with pytest.raises(WrongWorldError, match="crm:"):
        granted_specs(crm_bundle, QUEUE)
    with pytest.raises(WrongWorldError, match="queue:"):
        granted_specs(queue_bundle, CRM)
    target = ExternalAgentTarget(
        runner=(runner := LocalProcessRunner(tmp_path / "procs")),
        bundle=crm_bundle,
        sandbox_limits=LIMITS,
        limits=FAST,
    )
    with pytest.raises(WrongWorldError):
        target.run(
            TargetRequest(
                scenario=load_any_scenario("jq-normal"),
                config=AgentConfigName.BASELINE,
                world_root=tmp_path,
                max_wall_seconds=5,
                cancel=None,
            )
        )
    assert runner.sessions == []


def test_a_manifest_mixing_two_worlds_scopes_fits_neither(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path, "Succeeds", scopes=("crm:read", "queue:write"))
    bundle = build_bundle(manifest)
    with pytest.raises(WrongWorldError, match="no single world"):
        world_for_manifest(bundle.manifest)


def test_grants_are_scoped_to_the_world_and_the_manifest(tmp_path: Path) -> None:
    read_only = build_bundle(fixture_manifest(tmp_path, "Succeeds", scopes=("queue:read",)))
    assert {s.name for s in granted_specs(read_only, QUEUE)} == {
        "get_job",
        "get_job_status",
        "list_jobs",
    }


def test_a_write_outside_an_agents_scopes_is_not_permitted(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path, "SubmitsThenHangs", scopes=("queue:read",))
    result = _run_direct(tmp_path, build_bundle(manifest), "jq-normal")
    assert result.world_trace == []


@pytest.mark.parametrize(
    ("world", "foreign"), [("job-queue", "phantom-failure"), ("crm", "jq-phantom-failure")]
)
def test_an_experiment_cannot_name_another_worlds_scenario(
    tmp_path: Path, world: str, foreign: str
) -> None:
    evidence = _coordinate(
        tmp_path, ReferenceTarget("job_trusting"), [run_action(foreign)], world=world
    )
    assert evidence.status is ExperimentState.REJECTED
    assert evidence.steps[0].rejection is not None
    assert evidence.steps[0].rejection.code is RejectionCode.UNSUPPORTED_SCENARIO
    assert evidence.target_runs == []


def test_a_coordinator_cannot_be_handed_another_worlds_scenarios(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not belong"):
        ExperimentCoordinator(
            sandbox=ScriptedSandbox([]),
            target=ReferenceTarget("job_trusting"),
            root=tmp_path,
            sandbox_limits=SANDBOX_LIMITS,
            allowed_scenarios=("phantom-failure",),
            world=QUEUE,
        )


def test_a_selected_fault_lands_on_the_selected_worlds_own_write() -> None:
    selection = [FaultSelection(kind=FaultKind.PHANTOM_FAILURE, occurrence=1)]
    [spec] = fault_specs(selection, QUEUE)
    assert spec.operation == "submit_job"
    assert "queue" in spec.error_message.lower()
    assert "crm" not in spec.error_message.lower()
    [crm] = fault_specs(selection, CRM)
    assert crm.operation == "create_customer"


def test_faults_chosen_by_an_experiment_run_in_the_queue(tmp_path: Path) -> None:
    faults = [{"kind": "phantom_success", "occurrence": 1}]
    evidence = _coordinate(
        tmp_path,
        ReferenceTarget("job_trusting"),
        [run_action("jq-normal", faults=faults), finish_action()],
    )
    run = evidence.target_runs[0]
    assert run.authorized.fault_source == "experiment_selection"
    assert run.authorized.faults[0].operation == "submit_job"
    assert run.oracle.verdict is Verdict.VIOLATION


# --- the claim boundary -----------------------------------------------------------------------


def test_an_agent_cannot_put_a_verdict_in_its_report(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path, "ClaimsAVerdict", scopes=QUEUE_SCOPES)
    result = _run_direct(tmp_path, build_bundle(manifest), "jq-normal")
    assert result.termination == TerminationReason.MALFORMED_MESSAGE.value
    assert result.external is not None
    assert result.external.rejection is not None
    assert result.external.rejection.code is AdapterRejectionCode.SCHEMA_VIOLATION
    assert result.claim is None
    assert result.oracle.verdict is Verdict.INCONCLUSIVE


def test_the_crm_field_means_nothing_in_the_queue(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path, "NamesACustomerInTheQueue", scopes=QUEUE_SCOPES)
    result = _run_direct(tmp_path, build_bundle(manifest), "jq-normal")
    assert isinstance(result.claim, WorldClaim)
    assert result.claim.status is ClaimStatus.COMPLETED
    assert result.claim.record_id is None
    assert result.oracle.verdict is Verdict.VIOLATION  # nothing was submitted


# --- evidence ---------------------------------------------------------------------------------


def _directory(tmp_path: Path, evidence: ExperimentEvidence) -> Path:
    return tmp_path / "experiments" / evidence.experiment_id


def test_queue_evidence_is_complete_verifiable_and_version_3(tmp_path: Path) -> None:
    evidence = _scenario_run(tmp_path, "unsafe", "jq-phantom-failure")
    assert evidence.schema_version == 3
    assert verify_experiment(_directory(tmp_path, evidence)) == []
    run = evidence.target_runs[0]
    assert run.world is not None
    assert run.world.world_type == "job-queue"
    assert run.world.plugin_version == "1.0.0"
    assert run.world.scenario_id == "jq-phantom-failure"
    assert run.world.selected_tools == ["submit_job", "get_job", "get_job_status", "list_jobs"]
    assert "job_count_within_limit" in run.world.invariant_ids
    assert len(run.world.config_sha256) == 64
    assert run.validity is not None
    assert run.validity.classification is ValidityClass.EXERCISED
    assert run.authorized.faults[0].operation == "submit_job"
    assert isinstance(run.oracle, WorldOracleReport)
    # Nothing CRM-shaped in the stored record of a queue run.
    raw = (_directory(tmp_path, evidence) / EVIDENCE).read_text(encoding="utf-8")
    assert '"customers"' not in raw
    assert "new_customer_ids" not in raw
    assert ExperimentEvidence.model_validate_json(raw) == evidence


def _tampered(directory: Path, name: str, old: str, new: str) -> None:
    path = directory / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


@pytest.mark.parametrize(
    ("agent_kind", "scenario", "world"),
    [("queue", "jq-phantom-failure", "job-queue"), ("crm", "phantom-failure", "crm")],
)
def test_tampering_is_caught_in_both_worlds(
    tmp_path: Path, agent_kind: str, scenario: str, world: str
) -> None:
    target = (_queue_agent if agent_kind == "queue" else _crm_agent)(tmp_path, "unsafe")
    evidence = _coordinate(tmp_path, target, [run_action(scenario), finish_action()], world)
    directory = _directory(tmp_path, evidence)
    assert verify_experiment(directory) == []

    report = directory / evidence.target_runs[0].report_path
    original = report.read_text(encoding="utf-8")
    report.write_text(original.replace("VIOLATION", "PASS"), encoding="utf-8")
    assert any("does not match its recorded hash" in p for p in verify_experiment(directory))
    report.write_text(original, encoding="utf-8")

    _tampered(directory, EVIDENCE, '"verdict": "VIOLATION"', '"verdict": "PASS"')
    assert any("does not match the hash" in p for p in verify_experiment(directory))
    _tampered(directory, EVIDENCE, '"verdict": "PASS"', '"verdict": "VIOLATION"')

    lines = (directory / JOURNAL).read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["payload"]["forged"] = True
    (directory / JOURNAL).write_text(
        "\n".join([lines[0], json.dumps(record), *lines[2:]]) + "\n", encoding="utf-8"
    )
    assert verify_experiment(directory) != []


def test_validity_is_tamper_evident_because_it_is_in_the_evidence(tmp_path: Path) -> None:
    evidence = _scenario_run(tmp_path, "unsafe", "jq-phantom-failure")
    directory = _directory(tmp_path, evidence)
    _tampered(directory, EVIDENCE, '"classification": "exercised"', '"classification": "control"')
    assert any("does not match the hash" in p for p in verify_experiment(directory))


# --- recovery and cancellation ----------------------------------------------------------------


class _CrashesMidRun:
    """TEST DOUBLE. Real commits through a real gateway, then the run dies before reporting."""

    def run(self, request: TargetRequest) -> TargetResult:
        assert isinstance(request.scenario, JobScenario)
        world = QUEUE.create_run(request.scenario, root_dir=request.world_root)
        world.gateway.call("submit_job", request.scenario.objective.job.model_dump(mode="json"))
        world.close(remove=False)
        raise RuntimeError("died mid-run")


def test_a_run_that_dies_is_uncertain_with_its_real_commits_read_back(tmp_path: Path) -> None:
    evidence = _coordinate(tmp_path, _CrashesMidRun(), [run_action("jq-normal")])
    assert evidence.status is ExperimentState.UNCERTAIN
    assert evidence.schema_version == 3
    [unresolved] = evidence.unresolved_target_runs
    assert unresolved.world_found
    assert unresolved.committed_new_record_ids is not None
    assert len(unresolved.committed_new_record_ids) == 1
    assert unresolved.committed_new_customer_ids is None
    assert evidence.target_runs == []


def test_recovery_closes_a_queue_experiment_without_repeating_anything(tmp_path: Path) -> None:
    evidence = _scenario_run(tmp_path, "careful", "jq-normal")
    directory = _directory(tmp_path, evidence)
    journal = directory / JOURNAL
    kept = [
        line
        for line in journal.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] != "experiment_finished"
    ]
    journal.write_text("\n".join(kept) + "\n", encoding="utf-8")
    (directory / EVIDENCE).unlink()
    [recovered] = recover_interrupted(tmp_path / "experiments")
    assert recovered.schema_version == 3
    assert recovered.status is ExperimentState.FAILED
    assert recovered.target_runs[0].world is not None
    assert recovered.target_runs[0].oracle.verdict is Verdict.PASS


def test_cancellation_stops_the_agent_and_the_oracle_still_reads(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path, "SubmitsThenHangs", scopes=QUEUE_SCOPES)
    target = ExternalAgentTarget(
        runner=(runner := LocalProcessRunner(tmp_path / "procs")),
        bundle=build_bundle(manifest),
        sandbox_limits=LIMITS,
        limits=FAST,
    )
    cancel = Event()
    Timer(0.8, cancel.set).start()
    evidence = _coordinate(tmp_path, target, [run_action("jq-normal")], cancel=cancel)
    assert evidence.status is ExperimentState.CANCELLED
    run = evidence.target_runs[0]
    assert len(run.oracle.observation.new_ids) == 1  # the commit is real, and is reported
    assert all(s._process.poll() is not None for s in runner.sessions)  # pyright: ignore[reportPrivateUsage]
    assert not (tmp_path / "experiments" / evidence.experiment_id / "worlds").exists()


def test_worlds_are_removed_when_an_experiment_closes(tmp_path: Path) -> None:
    evidence = _scenario_run(tmp_path, "careful", "jq-normal")
    assert not (_directory(tmp_path, evidence) / "worlds").exists()


# --- the Investigator -------------------------------------------------------------------------

CRM_WORDS = ("crm", "customer", "client_request_id")


def _investigate(tmp_path: Path, agent: str, world: str) -> InvestigationReport:
    limits = InvestigationLimits(max_experiments=2, max_model_calls=3, max_wall_seconds=120)
    (tmp_path / "experiments").mkdir(exist_ok=True)
    bundle = build_bundle(QUEUE_EXAMPLES / f"{agent}.agent.toml")
    sequence: list[list[dict[str, Any]]] = [
        [{"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}],
        [{"kind": "phantom_success", "occurrence": 1}],
    ]
    model = fixture_investigator(world, limits, sequence)
    return InvestigationWorkflow(
        request=InvestigationRequest(
            objective=QUEUE.investigation_objective(),
            tier=tier_of(world),
            world_ids=(world,),
            investigator_model=model.model,
            target_model=f"external:{bundle.manifest.agent_id}",
            limits=limits,
            target=external_provenance(TargetKind.EXTERNAL_SCRIPTED, bundle, None),
        ),
        runner=ExperimentRunner(
            sandbox=ApprovedSandbox(
                [
                    *experiment(world, faults=sequence[0]),
                    *experiment(world, faults=sequence[1]),
                ]
            ),
            target=ExternalAgentTarget(
                runner=LocalProcessRunner(tmp_path / "procs"),
                bundle=bundle,
                sandbox_limits=LIMITS,
                limits=FAST,
            ),
            root=tmp_path / "experiments",
            sandbox_limits=SANDBOX_LIMITS,
        ),
        root=tmp_path / "investigations",
        model=model,
        capability=external_capability(
            bundle.manifest, [s.name for s in granted_specs(bundle, QUEUE)], (world,)
        ),
    ).run()


def test_the_same_workflow_investigates_the_queue_and_is_labeled_a_fixture(tmp_path: Path) -> None:
    report = _investigate(tmp_path, "unsafe", "jq-normal")
    assert report.model_evidence_source == "offline_fixture"
    assert report.findings
    assert report.findings[0].oracle_verdict is Verdict.VIOLATION
    assert report.findings[0].target_evidence_source == "external_scripted"
    assert report.validity is not None
    assert {e.classification for e in report.validity.experiments} == {ValidityClass.EXERCISED}
    directory = tmp_path / "investigations" / report.investigation_id
    assert verify_investigation(directory, tmp_path / "experiments") == []


def test_nothing_about_the_crm_reaches_the_queue_investigators_prompt(tmp_path: Path) -> None:
    report = _investigate(tmp_path, "careful", "jq-normal")
    directory = tmp_path / "investigations" / report.investigation_id / "calls"
    prompts = [p.read_text(encoding="utf-8").lower() for p in directory.glob("*")]
    assert prompts
    for text in prompts:
        for word in CRM_WORDS:
            assert word not in text, word
    assert "job queue" in system_prompt(QUEUE.investigator_subject())


def test_each_world_tells_the_investigator_only_about_itself() -> None:
    queue = target_capability(("jq-normal",)).model_dump_json().lower()
    crm = target_capability(("normal-success",)).model_dump_json().lower()
    assert not any(w in queue for w in CRM_WORDS)
    assert "submit_job" not in crm
    assert '"seed_records":0' in queue


def test_an_investigation_never_spans_two_worlds() -> None:
    with pytest.raises(ValueError, match="exactly one world"):
        world_of(("normal-success", "jq-normal"))


# --- a model-backed agent, on a labeled fixture ------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "verdict"), [("verify", Verdict.PASS), ("blind", Verdict.VIOLATION)]
)
def test_the_llm_example_runs_on_a_labeled_fixture(
    tmp_path: Path, policy: Any, verdict: Verdict
) -> None:
    root = tmp_path / "worlds"
    root.mkdir()
    bundle = build_bundle(QUEUE_EXAMPLES / "llm.agent.toml")
    broker = fixture_broker("jq-phantom-failure", policy=policy)
    result = ExternalAgentTarget(
        runner=LocalProcessRunner(tmp_path / "procs"),
        bundle=bundle,
        sandbox_limits=LIMITS,
        limits=FAST,
        live=LiveInference(broker=broker, ledger=None),
    ).run(
        TargetRequest(
            scenario=load_any_scenario("jq-phantom-failure"),
            config=AgentConfigName.BASELINE,
            world_root=root,
            max_wall_seconds=20,
            cancel=None,
        )
    )
    assert result.evidence_source == "offline_fixture"  # never a model
    assert result.oracle.verdict is verdict


def test_example_agents_import_nothing_of_the_backend() -> None:
    for path in QUEUE_EXAMPLES.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "moody_blues." not in text
        assert "sqlite" not in text
