"""The loop: limits, refinement, termination, adaptation plumbing and evidence linkage."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.experiment_evidence import ExperimentAuthorship, ExperimentState
from moody_blues.contracts.inference import InferenceRequest, InferenceResult
from moody_blues.contracts.investigation import (
    DecisionKind,
    FindingClass,
    InvestigationState,
    ProposalStatus,
    ResultClass,
    Strategy,
)
from moody_blues.experiments.target import ReferenceTarget, TargetRequest, TargetResult
from moody_blues.experiments.workspace import sha256_text
from moody_blues.inference.vultr import InferenceError
from moody_blues.investigator import commands
from moody_blues.investigator.fixtures import conclude, propose, tool_result
from moody_blues.investigator.model import CONCLUDE_TOOL, PROPOSE_TOOL, tool_spec
from moody_blues.investigator.workspace import (
    InvestigationBusyError,
    exclusive,
    recover_investigations,
    verify_investigation,
)
from tests.experiment.conftest import finish_action, sandbox_result
from tests.investigator.conftest import CODE, PF, PS, Harness, experiment, run_step


def test_a_stringified_nested_object_is_refused_not_decoded(tmp_path: Path) -> None:
    """Regression (KI-28): a live model encoded objects as strings. Output is never repaired."""
    arguments = json.loads(propose(1, CODE).tool_calls[0].arguments_json)
    arguments["motivated_by"] = "[]"
    h = Harness(tmp_path, replies=[tool_result(PROPOSE_TOOL, arguments), conclude()], steps=[])
    report = h.run()
    assert report.proposals[0].rejection is not None
    assert report.proposals[0].rejection.invalid_fields == ["motivated_by"]


def test_tool_schemas_stay_flat(tmp_path: Path) -> None:
    """Regression (KI-28): nested schema objects did not survive the provider's tool calling."""
    for name in (PROPOSE_TOOL, CONCLUDE_TOOL):
        schema = tool_spec(name).parameters
        assert "$defs" not in schema
        for field in schema["properties"].values():
            assert field.get("type") != "object"
            assert field.get("items", {}).get("type", "string") == "string"


def test_an_adaptive_investigation_feeds_observations_into_the_next_decision(
    tmp_path: Path,
) -> None:
    h = Harness(
        tmp_path,
        replies=[
            propose(1, CODE),
            propose(2, CODE, motivated_by=["obs_1"], revises="h1"),
            conclude(),
        ],
        steps=[*experiment(faults=[PF]), *experiment(faults=[PS])],
    )
    report = h.run()
    assert report.state is InvestigationState.COMPLETED
    assert h.prompt(0)["observations"] == []
    [first] = h.prompt(1)["observations"]
    assert first["runs"][0]["selected_faults"][0]["kind"] == "phantom_failure"
    assert first["runs"][0]["oracle"]["provenance"] == "oracle"
    assert report.proposals[1].motivated_by == ["obs_1"]
    assert report.hypotheses[1].hypothesis.revises == "h1"
    assert len(report.findings) == 2
    assert all(f.finding_class is FindingClass.CORRECT_RECOVERY for f in report.findings)
    assert report.statement.startswith("No verified violation")


def test_every_later_experiment_must_cite_a_real_observation(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(2, CODE, motivated_by=[]), conclude()],
        steps=experiment(),
        max_refinements=1,
    )
    report = h.run()
    assert len(report.experiments) == 1
    [rejected] = [p for p in report.proposals if p.rejection is not None]
    assert rejected.rejection is not None
    assert "motivated_by" in rejected.rejection.invalid_fields


def test_citing_an_observation_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE, motivated_by=["obs_9"]), conclude()],
        steps=[],
    )
    report = h.run()
    assert not report.experiments
    assert report.state is InvestigationState.INCONCLUSIVE


def test_experiment_count_is_enforced_by_offering_only_conclude(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[
            propose(1, CODE),
            propose(2, CODE, motivated_by=["obs_1"]),
            propose(3, CODE, motivated_by=["obs_2"]),
            conclude(),
        ],
        steps=[*experiment(), *experiment(), *experiment()],
    )
    report = h.run()
    assert len(report.experiments) == 3
    assert h.offered(2) == [PROPOSE_TOOL, CONCLUDE_TOOL]
    assert h.offered(3) == [CONCLUDE_TOOL]


def test_a_proposal_past_the_limit_is_not_executed(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(2, CODE, motivated_by=["obs_1"])],
        steps=experiment(),
        max_experiments=1,
        max_refinements=0,
    )
    report = h.run()
    assert len(report.experiments) == 1
    assert report.state is InvestigationState.INCONCLUSIVE
    assert report.termination == "generation_failed"


def test_model_call_limit_ends_the_investigation(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(2, CODE, motivated_by=["obs_1"])],
        steps=[*experiment(), *experiment()],
        max_model_calls=2,
    )
    report = h.run()
    assert report.state is InvestigationState.BUDGET_EXHAUSTED
    assert report.termination == "max_model_calls"
    assert report.usage.model_calls == 2
    assert len(report.findings) == 2  # evidence collected so far is still reported


def test_invalid_output_gets_one_refinement_and_both_are_kept(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[tool_result(PROPOSE_TOOL, "{not json"), propose(1, CODE), conclude()],
        steps=experiment(),
    )
    report = h.run()
    assert report.state is InvestigationState.COMPLETED
    original, replacement = report.proposals
    assert original.status is ProposalStatus.REJECTED_BEFORE_EXECUTION
    assert replacement.replaces_proposal_id == original.proposal_id
    assert h.prompt(1)["previous_proposal_rejected"]["problem"] == "invalid_decision"
    assert [d.kind for d in report.decisions].count(DecisionKind.REFINE) == 1


def test_refinement_is_bounded(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[tool_result(PROPOSE_TOOL, "{"), tool_result(PROPOSE_TOOL, "{")],
        steps=[],
    )
    report = h.run()
    assert report.state is InvestigationState.INCONCLUSIVE
    assert report.termination == "generation_failed"
    assert report.usage.model_calls == 2


def test_a_truncated_response_is_not_repaired(tmp_path: Path) -> None:
    cut = tool_result(PROPOSE_TOOL, '{"assess', finish_reason="length")
    h = Harness(tmp_path, replies=[cut, propose(1, CODE), conclude()], steps=experiment())
    report = h.run()
    assert report.proposals[0].rejection is not None
    assert report.proposals[0].rejection.problem == "truncated_response"


def test_oversized_code_is_refused_before_any_sandbox(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[propose(1, "x" * 16_001), conclude()], steps=[])
    report = h.run()
    assert not h.sandbox.requests
    assert report.proposals[0].rejection is not None
    assert report.proposals[0].rejection.problem == "code_too_long"


def test_a_syntax_error_is_classified_apart_from_target_failure_and_can_be_refined(
    tmp_path: Path,
) -> None:
    syntax = sandbox_result(
        status="failed",
        exit_code=1,
        stderr='  File "<string>", line 7\n    def (\nSyntaxError: invalid syntax\n',
    )
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(2, CODE, motivated_by=["obs_1"]), conclude()],
        steps=[syntax, *experiment()],
    )
    report = h.run()
    assert report.state is InvestigationState.COMPLETED
    first, second = report.experiments
    assert first.result_class is ResultClass.INVALID_PYTHON
    assert second.result_class is ResultClass.NO_VIOLATION_FOUND
    diagnostic = h.prompt(1)["previous_proposal_rejected"]
    assert (diagnostic["python_error"], diagnostic["python_error_line"]) == ("SyntaxError", 3)
    assert report.proposals[1].replaces_proposal_id == report.proposals[0].proposal_id
    assert not [f for f in report.findings if f.experiment_id == first.experiment_id]


def test_a_runtime_error_is_not_a_syntax_error(tmp_path: Path) -> None:
    crash = sandbox_result(status="failed", exit_code=1, stderr="KeyError: 'x'\n")
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=[crash])
    report = h.run()
    assert report.experiments[0].result_class is ResultClass.SANDBOX_RUNTIME_FAILURE


def test_protocol_rejection_stays_terminal_for_the_experiment(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(2, CODE, motivated_by=["obs_1"]), conclude()],
        steps=["not json", *experiment()],
    )
    report = h.run()
    first, second = report.experiments
    assert first.status is ExperimentState.REJECTED
    assert first.result_class is ResultClass.INVALID_PROTOCOL_OUTPUT
    assert first.experiment_id != second.experiment_id  # a new experiment, not a resumed one


def test_a_replacement_program_may_keep_its_hypothesis(tmp_path: Path) -> None:
    """Regression: a live refinement reused its hypothesis id and was refused as a duplicate."""
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(1, CODE, motivated_by=["obs_1"]), conclude()],
        steps=["not json", *experiment()],
    )
    report = h.run()
    assert report.state is InvestigationState.COMPLETED
    assert report.proposals[1].hypothesis_id == report.proposals[0].hypothesis_id
    assert report.proposals[1].replaces_proposal_id == report.proposals[0].proposal_id


def test_an_unrelated_proposal_may_not_reuse_a_hypothesis_id(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(1, CODE, motivated_by=["obs_1"]), conclude()],
        steps=experiment(),
    )
    report = h.run()
    assert report.proposals[1].rejection is not None
    assert report.proposals[1].rejection.invalid_fields == ["hypothesis_id"]


def test_an_unauthorized_action_is_never_answered_with_a_refinement(tmp_path: Path) -> None:
    bad = json.dumps({"protocol": "mb-exp/1", "action": "execute_sql", "sql": "x"})
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=[bad])
    report = h.run()
    assert report.experiments[0].result_class is ResultClass.UNAUTHORIZED_ACTION
    assert "previous_proposal_rejected" not in h.prompt(1)
    assert DecisionKind.REFINE not in [d.kind for d in report.decisions]


def test_no_refinement_after_a_target_run_happened(tmp_path: Path) -> None:
    """The program broke after a real run: repeating it could repeat real effects."""
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=[run_step(), "garbage"],
    )
    report = h.run()
    assert DecisionKind.REFINE not in [d.kind for d in report.decisions]
    assert len(report.experiments) == 1
    assert len(report.findings) == 1  # the run itself is still real evidence


class ExplodingTarget:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: TargetRequest) -> TargetResult:
        self.calls += 1
        raise RuntimeError("died after possible effects")


def test_uncertain_side_effects_end_the_investigation_and_nothing_is_repeated(
    tmp_path: Path,
) -> None:
    target = ExplodingTarget()
    h = Harness(tmp_path, replies=[propose(1, CODE)], steps=[run_step()], target=target)
    report = h.run()
    assert report.state is InvestigationState.FAILED
    assert report.termination == "uncertain_side_effects"
    assert report.experiments[0].result_class is ResultClass.UNCERTAIN_SIDE_EFFECTS
    assert target.calls == 1
    assert not report.findings


def test_cancellation_stops_at_the_next_boundary(tmp_path: Path) -> None:
    cancel = Event()

    def proposal_then_cancel(_: InferenceRequest) -> InferenceResult:
        cancel.set()
        return propose(1, CODE)

    h = Harness(tmp_path, replies=[proposal_then_cancel], steps=[run_step()], cancel=cancel)
    report = h.run()
    assert report.state is InvestigationState.CANCELLED


def test_a_cumulative_timeout_ends_the_investigation(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[], steps=[], max_wall_seconds=0.000001)
    report = h.run()
    assert report.state is InvestigationState.BUDGET_EXHAUSTED
    assert report.termination == "max_wall_seconds"


def test_a_provider_failure_is_failed_not_a_finding(tmp_path: Path) -> None:
    def fail(_: InferenceRequest) -> InferenceResult:
        raise InferenceError(ErrorCategory.PROVIDER_TIMEOUT, "timeout")

    h = Harness(tmp_path, replies=[fail], steps=[])
    report = h.run()
    assert report.state is InvestigationState.FAILED
    assert report.termination == "investigator_provider_error"
    assert report.model_calls[0].outcome == "provider_error"
    assert not report.findings


def test_only_one_investigation_runs_at_a_time(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[conclude()], steps=[])
    with exclusive(h.investigations), pytest.raises(InvestigationBusyError):
        h.run()


def test_a_finished_investigation_links_to_its_real_evidence(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=experiment())
    report = h.run()
    directory = h.investigations / report.investigation_id
    assert verify_investigation(directory, h.experiments) == []
    [ref] = report.experiments
    evidence = json.loads((h.experiments / ref.experiment_id / "evidence.json").read_text())
    assert evidence["authorship"] == "model_generated"
    assert evidence["parent_investigation_id"] == report.investigation_id
    assert evidence["generation"]["evidence_source"] == "offline_fixture"
    assert evidence["code_sha256"] == sha256_text(CODE) == report.proposals[0].source_sha256
    assert (directory / "sources" / "prop_1.py").read_text() == CODE
    assert (h.experiments / ref.experiment_id / "source.py").read_text() == CODE
    assert json.loads((directory / "calls" / "call-01.json").read_text())["request"]


@pytest.mark.parametrize("victim", ["sources/prop_1.py", "report.json"])
def test_tampering_with_the_record_is_detected(tmp_path: Path, victim: str) -> None:
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=experiment())
    report = h.run()
    directory = h.investigations / report.investigation_id
    path = directory / victim
    path.write_text(path.read_text().replace("prop_1", "prop_x", 1) + "#", encoding="utf-8")
    assert verify_investigation(directory, h.experiments)


def test_tampering_with_linked_evidence_is_detected(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=experiment())
    report = h.run()
    path = h.experiments / report.experiments[0].experiment_id / "evidence.json"
    path.write_text(path.read_text().replace('"PASS"', '"VIOLATION"'), encoding="utf-8")
    assert verify_investigation(h.investigations / report.investigation_id, h.experiments)


def test_a_dead_investigation_is_marked_and_never_resumed(tmp_path: Path) -> None:
    h = Harness(tmp_path, replies=[propose(1, CODE), conclude()], steps=experiment())
    report = h.run()
    directory = h.investigations / report.investigation_id
    (directory / "report.json").unlink()
    state = json.loads((directory / "state.json").read_text())
    state["state"] = "experimenting"
    (directory / "state.json").write_text(json.dumps(state))
    assert recover_investigations(h.investigations) == [report.investigation_id]
    assert "investigation_interrupted" in (directory / "journal.jsonl").read_text()


def test_the_one_shot_strategy_writes_everything_before_any_result_exists(
    tmp_path: Path,
) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(2, CODE), propose(3, CODE)],
        steps=[*experiment(faults=[PF]), *experiment(), *experiment()],
        strategy=Strategy.ONE_SHOT,
    )
    report = h.run()
    assert report.state is InvestigationState.COMPLETED
    assert report.usage.model_calls == 3
    assert len(report.experiments) == 3
    assert h.offered(0) == [PROPOSE_TOOL]
    assert all(h.prompt(i)["observations"] == [] for i in range(3))
    assert "planning_note" in h.prompt(0)
    assert len(h.prompt(2)["hypotheses_so_far"]) == 2
    assert not any(p.motivated_by for p in report.proposals)


def test_trusted_code_states_the_next_hypothesis_id(tmp_path: Path) -> None:
    """Regression: a live one-shot plan lost two of three proposals by reusing h1."""
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), propose(2, CODE)],
        steps=[*experiment(), *experiment()],
        strategy=Strategy.ONE_SHOT,
        max_experiments=2,
    )
    h.run()
    assert [h.prompt(i)["next_hypothesis_id"] for i in range(2)] == ["h1", "h2"]


def test_the_one_shot_strategy_gets_no_refinement_from_results(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE)],
        steps=["garbage"],
        strategy=Strategy.ONE_SHOT,
        max_experiments=1,
    )
    report = h.run()
    assert report.usage.model_calls == 1
    assert report.state is InvestigationState.INCONCLUSIVE


def test_the_fixed_strategy_uses_no_model_and_is_labeled_a_script(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[],
        steps=[
            *experiment("normal-success"),
            *experiment("phantom-failure"),
        ],
        strategy=Strategy.FIXED,
        worlds=("normal-success", "phantom-failure"),
    )
    report = h.run()
    assert report.usage.model_calls == 0
    assert report.state is InvestigationState.COMPLETED
    assert {p.authorship for p in report.proposals} == {ExperimentAuthorship.DEVELOPER_SCRIPT}
    evidence = json.loads(
        (h.experiments / report.experiments[0].experiment_id / "evidence.json").read_text()
    )
    assert evidence["authorship"] == "developer_script"
    assert evidence["source_path"] is None


def test_a_world_outside_the_request_is_refused_by_the_coordinator(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=[run_step("phantom-failure")],
        worlds=("normal-success",),
    )
    report = h.run()
    assert report.experiments[0].status is ExperimentState.REJECTED
    assert not report.findings


def test_reference_targets_are_never_model_behavior(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=[*experiment(faults=[PF]), *experiment(faults=[PF])],
        target=ReferenceTarget("blind_retry"),
    )
    report = h.run()
    [finding] = report.findings
    assert finding.finding_class is FindingClass.ORACLE_CONFIRMED_VIOLATION
    assert not finding.is_model_behavior
    assert "non-model target" in report.statement


def test_finish_action_summary_is_recorded_only_as_a_hash(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=[run_step(), finish_action(summary="hello")],
    )
    report = h.run()
    [omitted] = [
        o for o in report.observations[0].omitted_untrusted_text if o.source == "sandbox_summary"
    ]
    assert omitted.sha256 == sha256_text("hello")


def test_reruns_refuse_without_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    code = commands.reproduce(Settings(_env_file=None), confirmed=False, experiment_id="x", runs=6)  # type: ignore[call-arg]
    assert code == 2
    assert "NOT_RUN" in capsys.readouterr().out


def test_reruns_are_bounded(capsys: pytest.CaptureFixture[str]) -> None:
    code = commands.reproduce(Settings(_env_file=None), confirmed=True, experiment_id="x", runs=99)  # type: ignore[call-arg]
    assert code == 2
    assert "runs must be" in capsys.readouterr().out
