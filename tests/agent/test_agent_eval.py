"""Evaluation harness and live-command preflight (OFFLINE; PROVIDER FIXTURES only)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from moody_blues import cli
from moody_blues.contracts.agent import AgentConfigName, RunOutcome
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import InferenceRequest, InferenceResult
from moody_blues.contracts.oracle import FindingCode, Severity
from moody_blues.inference.vultr import InferenceError
from moody_blues.services.agent_eval import EvalStatus, cross_check, run_eval
from moody_blues.services.agent_render import render_agent_report
from moody_blues.world.scenarios import load_scenario
from tests.agent.conftest import call, claim, customer_id_of, last_results, tools


class TrustingFixtureModel:
    """PROVIDER FIXTURE that plays a fresh 'create then trust the response' run each time
    it sees a new conversation (two messages = a new run)."""

    def __init__(self, usage: int = 100) -> None:
        self.usage = usage
        self.runs = 0

    def complete(self, request: InferenceRequest) -> InferenceResult:
        if len(request.messages) == 2:
            self.runs += 1
            mission = request.messages[1].content or ""
            attrs = json.loads(mission.split("Customer attributes:\n", 1)[1].split("\n\n")[0])
            return tools(call("create_customer", attrs), usage=self.usage)
        result = last_results(request)[-1]
        if result.get("ok") is True:
            return claim("completed", customer_id_of(result))
        return claim("not_completed", message="error")


def test_eval_runs_every_cell_and_writes_evidence(tmp_path: Path) -> None:
    summary, reports = run_eval(
        inference=TrustingFixtureModel(),
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        out_dir=tmp_path,
        scenarios=["normal-success", "phantom-success"],
        trials=2,
    )
    assert summary.status is EvalStatus.COMPLETED
    assert summary.runs_planned == summary.runs_completed == 8
    assert len(list((tmp_path / "runs").glob("run_*.json"))) == 8
    assert (tmp_path / "summary.json").is_file()
    md = (tmp_path / "summary.md").read_text()
    assert "offline_fixture" in md
    cells = {(c.scenario_id, c.config): c for c in summary.cells}
    assert cells[("normal-success", AgentConfigName.BASELINE)].success_rate == 1.0
    phantom = cells[("phantom-success", AgentConfigName.HARDENED)]
    assert phantom.violations == 2
    assert all(c.oracle_cross_check_disagreements == 0 for c in summary.cells)
    # Interleaved: configs alternate within each scenario/trial.
    assert [r.agent.config for r in reports[:2]] == [
        AgentConfigName.BASELINE,
        AgentConfigName.HARDENED,
    ]


def test_eval_stops_at_the_token_budget_for_both_configs_equally(tmp_path: Path) -> None:
    summary, reports = run_eval(
        inference=TrustingFixtureModel(usage=3_000),
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        out_dir=tmp_path,
        scenarios=["normal-success"],
        trials=5,
        max_eval_tokens=8_000,  # each run is ~3,100 tokens
    )
    assert summary.status is EvalStatus.PARTIAL_BUDGET
    # The budget is crossed during trial 2's baseline run, but its hardened run still happens.
    assert summary.runs_completed == 4
    counts = Counter(r.agent.config for r in reports)
    assert counts[AgentConfigName.BASELINE] == counts[AgentConfigName.HARDENED] == 2


def test_eval_stops_on_rejected_credentials(tmp_path: Path) -> None:
    class Rejecting:
        def complete(self, request: InferenceRequest) -> InferenceResult:
            raise InferenceError(ErrorCategory.PROVIDER_AUTH, "401 Invalid API key (fixture)")

    summary, reports = run_eval(
        inference=Rejecting(),
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        out_dir=tmp_path,
        trials=3,
    )
    assert summary.status is EvalStatus.BLOCKED_BY_CREDENTIALS
    assert len(reports) == 1
    assert reports[0].assessment.attribution == "infrastructure"
    assert reports[0].assessment.outcome is RunOutcome.INCONCLUSIVE


def test_cross_check_detects_an_oracle_false_positive(tmp_path: Path) -> None:
    _, reports = run_eval(
        inference=TrustingFixtureModel(),
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        out_dir=tmp_path,
        scenarios=["normal-success"],
        configs=[AgentConfigName.BASELINE],
    )
    report = reports[0]
    scenario = load_scenario("normal-success")
    assert cross_check(report, scenario) == []
    # Simulate an Oracle that wrongly reports a duplicate.
    from moody_blues.contracts.oracle import Finding

    bogus = report.oracle.model_copy(
        update={
            "findings": [
                Finding(
                    code=FindingCode.DUPLICATE_SIDE_EFFECT,
                    severity=Severity.VIOLATION,
                    invariant=None,
                    message="bogus",
                )
            ]
        }
    )
    tampered = report.model_copy(update={"oracle": bogus})
    assert cross_check(tampered, scenario) == ["oracle flagged duplicate_side_effect"]


def test_render_shows_trajectory_state_and_verdict(tmp_path: Path) -> None:
    _, reports = run_eval(
        inference=TrustingFixtureModel(),
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        out_dir=tmp_path,
        scenarios=["phantom-failure"],
        configs=[AgentConfigName.BASELINE],
    )
    text = render_agent_report(reports[0])
    for expected in (
        "evidence: offline_fixture",
        "create_customer",
        "ERROR timeout",
        "<fault: phantom_failure / committed_write_reported_as_failure>",
        "Truth Oracle: INCONCLUSIVE",
        "underreported_completion",
        "outcome=inconclusive",
    ):
        assert expected in text, expected


# --- live-command preflight never makes a chargeable call without credentials ---------------


@pytest.mark.parametrize(
    "argv",
    [
        ["agent-run", "--scenario", "normal-success", "--config", "baseline"],
        ["agent-eval", "--trials", "1"],
    ],
)
def test_agent_commands_are_blocked_without_credentials(
    argv: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "ARTIFACTS", tmp_path)
    from tests.conftest import make_settings

    monkeypatch.setattr(cli, "Settings", make_settings)
    assert cli.main(argv) == 2
    assert "BLOCKED_BY_CREDENTIALS" in capsys.readouterr().out
