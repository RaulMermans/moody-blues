"""The adaptation test itself, with labeled fixtures. These prove the measurement can tell the
difference. Whether a real model adapts is a live result, recorded in docs/evaluations."""

from __future__ import annotations

import json
from pathlib import Path

from moody_blues.agents.target import InferencePort
from moody_blues.contracts.inference import InferenceRequest, InferenceResult
from moody_blues.contracts.investigation import InvestigationLimits, Strategy
from moody_blues.experiments.target import ReferenceTarget
from moody_blues.investigator.catalog import target_capability
from moody_blues.investigator.evaluation import (
    FollowUp,
    PairCase,
    PairResult,
    hardened_rates,
    render_comparison,
    render_pairs,
    run_pair,
    strategy_row,
)
from moody_blues.investigator.fixtures import (
    FIXTURE_MODEL,
    conclude,
    experiment_program,
    propose,
)
from moody_blues.investigator.model import InvestigatorModel
from moody_blues.investigator.workflow import ExperimentRunner
from tests.experiment.conftest import SANDBOX_LIMITS, finish_action
from tests.investigator.conftest import CODE, PF, ApprovedSandbox, Harness, experiment, run_step

WORLDS = ("w-v1", "w-v2", "w-v3")
CASE = PairCase("case", "w-v1", [PF], "verify_then_report", "blind_retry")


def _steps_for_pair() -> list[str]:
    return [run_step("w-v1", [PF]), finish_action()]


class ReactiveModel:
    """TEST DOUBLE: follows the verdict in the prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, request: InferenceRequest) -> InferenceResult:
        text = str(request.messages[-1].content)
        self.prompts.append(text)
        verdict = json.loads(text)["observations"][0]["runs"][0]["oracle"]["verdict"]
        if verdict == "VIOLATION":
            return conclude("violation_found")
        return propose(2, experiment_program("w-v2"), motivated_by=["obs_1"])


class IgnorantModel:
    """TEST DOUBLE: the same answer whatever it is shown."""

    def complete(self, request: InferenceRequest) -> InferenceResult:
        return propose(2, experiment_program("w-v2"), motivated_by=["obs_1"])


class CoinFlipModel:
    """TEST DOUBLE: answers vary within a branch, which is noise, not adaptation."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: InferenceRequest) -> InferenceResult:
        self.calls += 1
        if self.calls % 2:
            return conclude()
        return propose(2, experiment_program("w-v2"), motivated_by=["obs_1"])


def _pair(tmp_path: Path, inference: InferencePort, follow_up_steps: int) -> PairResult:
    """Each branch: a seed experiment, then its follow-up programs, all on canned stdout."""

    def runner_for(executor: str) -> ExperimentRunner:
        return ExperimentRunner(
            sandbox=sandbox,
            target=ReferenceTarget(executor),
            root=tmp_path / "experiments",
            sandbox_limits=SANDBOX_LIMITS,
        )

    (tmp_path / "experiments").mkdir()
    follow_up = [run_step("w-v2", []), finish_action()]
    sandbox = ApprovedSandbox(
        [*_steps_for_pair(), *_steps_for_pair(), *(follow_up * follow_up_steps)]
    )
    return run_pair(
        CASE,
        model=InvestigatorModel(
            inference=inference,
            evidence="offline_fixture",
            model=FIXTURE_MODEL,
            provider=None,
            spend=None,
            max_completion_tokens=256,
            temperature=0,
        ),
        runner_for=runner_for,
        capability=target_capability(WORLDS),
        worlds=WORLDS,
        objective="o",
        limits=InvestigationLimits(),
        artifacts=tmp_path / "pair",
    )


def test_a_reactive_model_shows_adaptation(tmp_path: Path) -> None:
    model = ReactiveModel()
    result = _pair(tmp_path, model, 2)
    assert result.verdict_a == "PASS"
    assert result.verdict_b == "VIOLATION"
    assert result.adaptation_shown
    assert result.context_identical_except_observation
    assert "| case |" in render_pairs([result])


def test_a_model_that_ignores_observations_shows_none(tmp_path: Path) -> None:
    result = _pair(tmp_path, IgnorantModel(), 4)
    assert result.observations_differ
    assert not result.across_differs
    assert not result.adaptation_shown


def test_noise_within_a_branch_is_not_counted_as_adaptation(tmp_path: Path) -> None:
    result = _pair(tmp_path, CoinFlipModel(), 2)
    assert not result.within_a_stable
    assert not result.adaptation_shown


def test_prompts_in_a_pair_differ_only_in_the_observation(tmp_path: Path) -> None:
    model = ReactiveModel()
    _pair(tmp_path, model, 2)
    first, last = json.loads(model.prompts[0]), json.loads(model.prompts[-1])
    assert first["observations"] != last["observations"]
    first.pop("observations")
    last.pop("observations")
    assert first == last


def test_hardened_rates_group_answers_by_the_seed_verdict(tmp_path: Path) -> None:
    result = _pair(tmp_path, ReactiveModel(), 2)
    hardened = FollowUp(
        decision="propose",
        selection="w-v2|hardened|experiment_selection|",
        source_sha256=None,
        experiment_id=None,
        cited_observation=True,
        hypothesis_status=None,
        prompt_sha256="x",
    )
    changed = result.model_copy(update={"b": [hardened, *result.b[1:]]})
    assert hardened_rates([changed]) == (0, 2, 1, 2)


def test_rows_count_generated_adaptive_and_discovered_separately(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[
            propose(1, CODE),
            propose(2, CODE, motivated_by=["obs_1"], revises="h1"),
            conclude(),
        ],
        steps=[*experiment(), *experiment(faults=[PF])],
    )
    row = strategy_row(h.run(), 1)
    assert row.strategy is Strategy.ADAPTIVE
    assert (row.programs_generated, row.adaptively_selected, row.hypothesis_revisions) == (2, 1, 1)
    assert row.live_confirmed_violations == 0  # generating programs discovers nothing
    assert row.distinct_conditions == 2
    assert "adaptive" in render_comparison([row])


def test_reference_violations_do_not_count_as_live_discoveries(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=[*experiment(faults=[PF]), *experiment(faults=[PF])],
        target=ReferenceTarget("blind_retry"),
    )
    assert strategy_row(h.run(), 1).live_confirmed_violations == 0
