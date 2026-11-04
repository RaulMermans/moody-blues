"""Execution of the frozen plan: ordering, replacement, staging, recovery and budget."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.experiment_evidence import ExperimentState
from moody_blues.contracts.inference import InferenceRequest, InferenceResult
from moody_blues.contracts.investigation import Strategy
from moody_blues.evaluation import commands
from moody_blues.evaluation.journal import Journal, JournalError
from moody_blues.evaluation.manifest import Faults, Manifest, TrialPlan
from moody_blues.evaluation.suites import (
    SuiteStoppedError,
    cell_of,
    run_causal,
    run_strategies,
    stage_two_decision,
)
from moody_blues.evaluation.trials import TrialCategory, summarize
from moody_blues.experiments.budget import (
    PriceCeiling,
    ScopedSpend,
    SpendLedger,
    worst_case_run_tokens,
)
from tests.agent.conftest import ScriptedModel, claim
from tests.evaluation.conftest import StubCausalExecutor, trial
from tests.experiment.conftest import SANDBOX_LIMITS, finish_action
from tests.investigator.conftest import ApprovedSandbox


def weak_under_lag(_: str, config: AgentConfigName, faults: Faults) -> str:
    """A script standing in for an agent: fails under long lag at baseline, only there."""
    long_lag = any(f.get("span") == 6 for f in faults)
    return (
        "verify_then_report"
        if long_lag and config is AgentConfigName.BASELINE
        else "idempotent_retry"
    )


def robust(_: str, __: AgentConfigName, ___: Faults) -> str:
    return "busy_but_correct"


def _run(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan, executor: StubCausalExecutor
) -> Journal:
    journal = Journal(tmp_path / "journal.jsonl")
    run_causal(manifest, plan, executor=executor, journal=journal)
    return journal


def test_the_plan_order_is_followed(tmp_path: Path, manifest: Manifest, plan: TrialPlan) -> None:
    executor = StubCausalExecutor(tmp_path / "e", weak_under_lag)
    _run(tmp_path, manifest, plan, executor)
    assert executor.calls[: len(plan.causal_stage_one)] == [
        t.trial_id for t in plan.causal_stage_one
    ]


def test_each_trial_gets_a_fresh_world(tmp_path: Path, manifest: Manifest, plan: TrialPlan) -> None:
    journal = _run(tmp_path, manifest, plan, StubCausalExecutor(tmp_path / "e", weak_under_lag))
    trials = journal.trials()
    assert len({t.experiment_id for t in trials}) == len(trials)
    clean = [t for t in trials if t.condition_id == "clean"]
    assert len({t.world_sha256 for t in clean}) == 1  # equivalent initial state


def test_a_decisive_first_stage_does_not_extend(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    journal = _run(tmp_path, manifest, plan, StubCausalExecutor(tmp_path / "e", weak_under_lag))
    assert journal.payloads("stage_decision")[0]["reason"] == "stage_one_conclusive"
    assert len(journal.trials()) == len(plan.causal_stage_one)


def test_an_inconclusive_stage_extends_every_cell_alike(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    journal = _run(tmp_path, manifest, plan, StubCausalExecutor(tmp_path / "e", robust))
    assert journal.payloads("stage_decision")[0]["extend"] is True
    per_cell = {cell_of(t) for t in journal.trials()}
    for cell in per_cell:
        assert sum(1 for t in journal.trials() if cell_of(t) == cell) == 5


def test_no_extension_past_the_budget(tmp_path: Path, manifest: Manifest, plan: TrialPlan) -> None:
    executor = StubCausalExecutor(tmp_path / "e", robust, remaining=0.1)
    journal = _run(tmp_path, manifest, plan, executor)
    assert journal.payloads("stage_decision")[0]["reason"] == "inconclusive_but_over_budget"
    assert len(journal.trials()) == len(plan.causal_stage_one)


def test_extension_cost_includes_a_safety_margin(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    runs = [
        trial(tmp_path / "e", condition_id="clean").model_copy(update={"estimated_cost_usd": 0.1})
    ]
    decision = stage_two_decision(manifest, plan, runs, remaining_usd=3.0, reservation_usd=0.4)
    assert decision["needed_usd"] == pytest.approx(1.5 * 0.1 * 12 + 0.4)
    assert decision["extend"] is True


def test_an_impaired_attempt_is_replaced_and_stays_on_the_record(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    executor = StubCausalExecutor(
        tmp_path / "e",
        weak_under_lag,
        truncate=lambda trial_id: 1 if trial_id == "c1-stale-6-baseline" else 0,
    )
    journal = _run(tmp_path, manifest, plan, executor)
    cell = [t for t in journal.trials() if cell_of(t) == "stale-6/baseline"]
    summary = summarize("c", cell)
    assert (summary.attempted, summary.eligible, summary.impaired_by_limits) == (4, 3, 1)
    assert summary.duplicates_all == 4
    assert summary.duplicates_eligible == 3


def test_replacement_is_bounded(tmp_path: Path, manifest: Manifest, plan: TrialPlan) -> None:
    executor = StubCausalExecutor(tmp_path / "e", robust, truncate=lambda _: 1, remaining=0.0)
    journal = _run(tmp_path, manifest, plan, executor)
    cell = [t for t in journal.trials() if cell_of(t) == "stale-6/baseline"]
    assert len(cell) == manifest.causal.max_attempts_per_cell
    assert not any(t.eligible for t in cell)


def test_a_finished_suite_repeats_nothing(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    executor = StubCausalExecutor(tmp_path / "e", weak_under_lag)
    journal = _run(tmp_path, manifest, plan, executor)
    done = len(executor.calls)
    run_causal(manifest, plan, executor=executor, journal=journal)
    assert len(executor.calls) == done


def test_budget_refusal_stops_the_suite_and_keeps_what_ran(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    executor = StubCausalExecutor(tmp_path / "e", weak_under_lag, refuse_after=4)
    journal = Journal(tmp_path / "journal.jsonl")
    with pytest.raises(SuiteStoppedError, match="budget refused"):
        run_causal(manifest, plan, executor=executor, journal=journal)
    assert len(journal.trials()) == 4
    assert journal.unfinished() == []


def test_a_crashed_trial_stays_on_the_record_as_attempted(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    path = tmp_path / "journal.jsonl"
    first = plan.causal_stage_one[0]
    Journal(path).append(
        "started",
        {"id": first.trial_id, "condition_id": first.condition_id, "config": first.config.value},
    )
    executor = StubCausalExecutor(tmp_path / "e", weak_under_lag)
    journal = Journal(path)
    run_causal(manifest, plan, executor=executor, journal=journal)
    assert first.trial_id not in executor.calls  # never silently retried under the same id
    lost = next(t for t in journal.trials() if t.trial_id == first.trial_id)
    assert lost.category is TrialCategory.PROVIDER_OR_INFRASTRUCTURE
    cell = summarize("c", [t for t in journal.trials() if cell_of(t) == cell_of(lost)])
    assert cell.attempted == 4
    assert cell.eligible == 3


def test_a_tampered_journal_refuses_to_load(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    journal.append("a", {"x": 1})
    journal.append("b", {"x": 2})
    path.write_text(path.read_text("utf-8").replace('"x": 1', '"x": 9'), "utf-8")
    with pytest.raises(JournalError, match="chain broken"):
        Journal(path)


def test_a_removed_entry_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    for n in range(3):
        journal.append("a", {"n": n})
    lines = path.read_text("utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", "utf-8")
    with pytest.raises(JournalError, match="chain broken"):
        Journal(path)


def test_a_truncated_journal_line_refuses_to_load(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    Journal(path).append("a", {"x": 1})
    with path.open("a", encoding="utf-8") as f:
        f.write('{"kind": "tr')
    with pytest.raises(JournalError, match="unreadable"):
        Journal(path)


# --- the live wiring, with a scripted provider ---------------------------------------------------


def _returns(value: object) -> Callable[..., object]:
    def inner(*_: object) -> object:
        return value

    return inner


def _claiming_model() -> ScriptedModel:
    """TEST DOUBLE for the target's provider: reads nothing, then claims not_completed."""
    return ScriptedModel([claim("not_completed", message="fixture")])


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[SpendLedger, Path]:
    ledger = SpendLedger(
        tmp_path / "ledger.jsonl",
        limit_usd=5.0,
        prices=PriceCeiling(input_per_million_usd=1.4, output_per_million_usd=4.4),
    )
    monkeypatch.setattr(commands, "target_client", _returns(_claiming_model()))
    monkeypatch.setattr(commands, "sandbox_limits", _returns(SANDBOX_LIMITS))
    return ledger, tmp_path / "experiments"


def test_a_causal_trial_runs_the_registered_condition_through_the_ledger(
    monkeypatch: pytest.MonkeyPatch,
    wired: tuple[SpendLedger, Path],
    manifest: Manifest,
    plan: TrialPlan,
) -> None:
    ledger, root = wired
    root.mkdir()
    faults = next(c for c in manifest.causal.conditions if c.condition_id == "stale-6").faults
    action = {
        "protocol": "mb-exp/1",
        "action": "run_target_agent",
        "scenario_id": "w-e3",
        "config": "hardened",
        "faults": faults,
    }
    monkeypatch.setattr(
        commands,
        "generated_code_runner",
        _returns(ApprovedSandbox([json.dumps(action), finish_action()])),
    )
    spend = ScopedSpend(ledger, "s6-causal", manifest.budget.causal_cap_usd)
    executor = commands._CausalExecutor(  # pyright: ignore[reportPrivateUsage]
        Settings(_env_file=None),  # type: ignore[call-arg]
        manifest,
        spend,
        ledger.prices,
        root,
    )
    evidence = executor.run(
        trial_id="c1", world="w-e3", config=AgentConfigName.HARDENED, faults=faults
    )
    [run] = evidence.target_runs
    assert run.authorized.config is AgentConfigName.HARDENED
    assert run.authorized.faults[0].span == 6
    assert run.policy_version == "hardened-v1"
    assert ledger.status().settled_entries == 1
    assert spend.status().settled_entries == 1
    assert executor.reservation_usd == pytest.approx(
        ledger.prices.worst_case(worst_case_run_tokens(manifest.target_budget))
    )
    assert executor.remaining_usd() < manifest.budget.causal_cap_usd


def test_the_shared_cap_refuses_a_run_before_it_starts(
    monkeypatch: pytest.MonkeyPatch, wired: tuple[SpendLedger, Path], manifest: Manifest
) -> None:
    ledger, root = wired
    root.mkdir()
    action = {
        "protocol": "mb-exp/1",
        "action": "run_target_agent",
        "scenario_id": "w-e3",
        "config": "baseline",
        "faults": [],
    }
    monkeypatch.setattr(
        commands,
        "generated_code_runner",
        _returns(ApprovedSandbox([json.dumps(action), finish_action()])),
    )
    executor = commands._CausalExecutor(  # pyright: ignore[reportPrivateUsage]
        Settings(_env_file=None),  # type: ignore[call-arg]
        manifest,
        ScopedSpend(ledger, "s6-causal", 0.05),
        ledger.prices,
        root,
    )
    evidence = executor.run(trial_id="c1", world="w-e3", config=AgentConfigName.BASELINE, faults=[])
    assert evidence.status is ExperimentState.BUDGET_EXHAUSTED
    assert not evidence.target_runs
    assert ledger.status().settled_entries == 0


def test_the_fixed_unit_runs_its_schedule_with_no_model_call(
    monkeypatch: pytest.MonkeyPatch,
    wired: tuple[SpendLedger, Path],
    manifest: Manifest,
    plan: TrialPlan,
    tmp_path: Path,
) -> None:
    ledger, root = wired
    root.mkdir()
    unit = next(u for u in plan.strategies if u.strategy is Strategy.FIXED)
    steps: list[str] = []
    for _, world, condition in unit.fixed_schedule:
        steps += [
            json.dumps(
                {
                    "protocol": "mb-exp/1",
                    "action": "run_target_agent",
                    "scenario_id": world,
                    "config": "baseline",
                    "faults": condition.faults,
                }
            ),
            finish_action(),
        ]
    sandbox = ApprovedSandbox(steps)
    monkeypatch.setattr(commands, "generated_code_runner", _returns(sandbox))
    monkeypatch.setattr(commands, "INVESTIGATIONS", tmp_path / "investigations")
    monkeypatch.setattr(commands, "target_client", _returns(_ManyClaims()))
    executor = commands._InvestigationExecutor(  # pyright: ignore[reportPrivateUsage]
        Settings(_env_file=None),  # type: ignore[call-arg]
        manifest,
        cast("commands.LiveContext", SimpleNamespace(ledger=ledger, client=None)),
        ScopedSpend(ledger, "s6-strategies", manifest.budget.strategies_cap_usd),
        root,
    )
    journal = Journal(tmp_path / "journal.jsonl")
    single = plan.model_copy(update={"strategies": (unit,)})
    trials = run_strategies(manifest, single, executor=executor, journal=journal)
    assert len(trials) == manifest.strategies.limits.max_experiments
    assert {t.strategy for t in trials} == {"fixed"}
    assert {t.experiment_source for t in trials} == {"developer_script"}
    assert [t.condition_key.split("|")[0] for t in trials if t.condition_key] == [
        world for _, world, _ in unit.fixed_schedule
    ]
    [summary] = journal.payloads("unit")
    assert summary["model_calls"] == 0
    assert journal.unfinished() == []
    run_strategies(manifest, single, executor=executor, journal=journal)
    assert len(journal.trials()) == len(trials)  # a finished unit never runs twice


class _ManyClaims:
    """TEST DOUBLE. Every call claims not_completed, for any number of runs."""

    def complete(self, request: InferenceRequest) -> InferenceResult:
        return _claiming_model().complete(request)
