"""The opt-in model path, with a labeled fixture. Nothing here reaches a provider.

Scripted model output is ``offline_fixture`` and never describes real model behavior. What these
tests show is that the host alone decides whether a run is an LLM run, and that it stays in budget.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from moody_blues.contracts.agent import AgentConfigName, AgentRunReport, TokenTotals
from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.inference import (
    InferenceRequest,
    InferenceResult,
    TokenUsage,
    ToolCall,
)
from moody_blues.contracts.oracle import Verdict
from moody_blues.experiments.budget import BudgetExceededError
from moody_blues.experiments.target import TargetRequest, TargetResult
from moody_blues.external.bundle import build_bundle
from moody_blues.external.driver import InferenceBroker
from moody_blues.external.target import ExternalAgentTarget, LiveInference
from moody_blues.world.scenarios import load_scenario
from tests.external.conftest import (
    EXAMPLES,
    LIMITS,
    LocalProcessRunner,
    fixture_manifest,
    run_agent,
)

Run = Callable[..., TargetResult]
MODEL_CAPABILITIES = ("tools", "cancellation", "model")
MODEL_AGENT = {"capabilities": MODEL_CAPABILITIES}


class ScriptedModel:
    """TEST DOUBLE. Plays canned replies; says nothing about any real model."""

    def __init__(self, replies: list[InferenceResult]) -> None:
        self._replies = replies
        self.requests: list[InferenceRequest] = []

    def complete(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        return self._replies.pop(0)


def _reply(content: str | None = None, calls: list[ToolCall] | None = None) -> InferenceResult:
    return InferenceResult(
        provider="fixture",
        requested_model="fixture-model",
        reported_model="fixture-model",
        response_id="r",
        content=content,
        tool_calls=calls or [],
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        latency_ms=1,
    )


def _create_call(customer_id: str = "c1") -> ToolCall:
    arguments = {"name": "Ada Lovelace", "email": "ada@example.com"}
    return ToolCall(id=customer_id, name="create_customer", arguments_json=json.dumps(arguments))


def _live(model: ScriptedModel, *, calls: int = 4, ledger: object = None) -> LiveInference:
    return LiveInference(
        broker=InferenceBroker(
            inference=model,
            evidence="offline_fixture",
            provider="fixture",
            model="fixture-model",
            max_model_calls=calls,
            max_total_tokens=1_000,
            max_completion_tokens=64,
        ),
        ledger=ledger,  # pyright: ignore[reportArgumentType]
    )


def test_a_run_is_an_llm_run_only_if_the_host_brokered_a_model(fixture_run: Run) -> None:
    model = ScriptedModel([_reply(calls=[_create_call()])])
    result = fixture_run("AsksForModel", live=_live(model), **MODEL_AGENT)
    assert result.evidence_source == "offline_fixture"
    assert result.external is not None
    assert result.external.model_calls == 1
    assert result.reported_models == ["fixture-model"]
    assert result.tokens is not None
    assert result.tokens.total_tokens == 15


def test_saying_llm_does_not_make_a_run_an_llm_run(tmp_path: Path) -> None:
    result = run_agent(
        tmp_path,
        build_bundle(
            fixture_manifest(tmp_path, "ClaimsLlm", target_type="llm", capabilities=("tools",))
        ),
    )
    assert result.evidence_source == "external_scripted"
    assert result.external is not None
    assert result.external.declared_target_type.value == "llm"
    assert result.external.model_calls == 0
    assert result.provider is None


def test_no_model_is_granted_unless_the_operator_enables_one(fixture_run: Run) -> None:
    result = fixture_run("AsksForModel", **MODEL_AGENT)
    assert result.external is not None
    assert result.external.final is not None
    assert result.external.final.error_class == "model_not_granted"
    assert result.evidence_source == "external_scripted"


def test_model_call_budget_is_enforced_by_the_host(tmp_path: Path) -> None:
    model = ScriptedModel([_reply(calls=[_create_call()]), _reply(content="never reached")])
    llm = EXAMPLES / "llm.agent.toml"
    result = run_agent(tmp_path, build_bundle(llm), live=_live(model, calls=1))
    assert len(model.requests) == 1
    assert result.external is not None
    assert result.external.final is not None
    assert result.external.final.error_class == "model_unavailable"


def test_the_example_llm_agent_stops_at_once_with_no_model(tmp_path: Path) -> None:
    result = run_agent(tmp_path, build_bundle(EXAMPLES / "llm.agent.toml"))
    assert result.evidence_source == "external_scripted"
    assert result.world_trace == []
    assert result.oracle.verdict is Verdict.INCONCLUSIVE


def test_the_example_llm_agent_runs_a_real_loop_against_a_fixture(tmp_path: Path) -> None:
    customer = load_scenario("normal-success").objective.customer
    call = ToolCall(
        id="c1",
        name="create_customer",
        arguments_json=json.dumps(
            {"name": customer.name, "email": customer.email, "metadata": customer.metadata}
        ),
    )
    created = "cus_"  # the fixture cannot know the id; it reports without one
    final = json.dumps({"status": "completed", "message": f"created a {created} record"})
    model = ScriptedModel([_reply(calls=[call]), _reply(content=final)])
    result = run_agent(tmp_path, build_bundle(EXAMPLES / "llm.agent.toml"), live=_live(model))
    assert result.evidence_source == "offline_fixture"
    assert result.external is not None
    assert result.external.model_calls == 2
    assert len(result.world_trace) == 1
    # The model's turn reached the host exactly as a provider would need it.
    assert len(model.requests[1].messages) == 4
    assert {t.name for t in model.requests[0].tools} == {
        "create_customer",
        "get_customer",
        "search_customers",
    }
    report = AgentRunReport.model_validate(result.full_report)
    assert report.agent.steps[0].provider == "fixture"


class Raising:
    def complete(self, request: InferenceRequest) -> InferenceResult:
        raise MoodyBluesError(ErrorCategory.PROVIDER_TIMEOUT, "the provider timed out")


def test_a_provider_failure_reaches_the_agent_as_a_refusal_and_keeps_usage_incomplete(
    tmp_path: Path,
) -> None:
    live = LiveInference(
        broker=InferenceBroker(
            inference=Raising(),
            evidence="offline_fixture",
            provider="fixture",
            model="m",
            max_model_calls=2,
            max_total_tokens=100,
            max_completion_tokens=64,
        ),
        ledger=None,
    )
    result = run_agent(tmp_path, build_bundle(EXAMPLES / "llm.agent.toml"), live=live)
    report = AgentRunReport.model_validate(result.full_report)
    assert report.agent.tokens.complete is False
    assert result.external is not None
    assert result.external.final is not None
    assert result.external.final.error_class == "model_unavailable"
    # No call returned, so nothing shows a model was used.
    assert result.evidence_source == "external_scripted"


class Ledger:
    """TEST DOUBLE for the spend port."""

    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.reserved: list[int] = []
        self.settled: list[TokenTotals | None] = []

    def reserve(self, label: str, *, worst_case_tokens: int) -> str:
        if self.refuse:
            raise BudgetExceededError("no budget left")
        self.reserved.append(worst_case_tokens)
        return "entry"

    def settle(self, entry_id: str, tokens: TokenTotals | None) -> float:
        self.settled.append(tokens)
        return 0.01


def test_a_paid_run_reserves_first_and_settles_after(fixture_run: Run) -> None:
    ledger = Ledger()
    model = ScriptedModel([_reply(calls=[_create_call()])])
    result = fixture_run("AsksForModel", live=_live(model, ledger=ledger), **MODEL_AGENT)
    assert len(ledger.reserved) == 1
    assert ledger.settled[0] is not None
    assert ledger.settled[0].total_tokens == 15
    assert result.estimated_cost_usd == 0.01


def test_no_budget_means_nothing_starts(tmp_path: Path) -> None:
    runner = LocalProcessRunner(tmp_path / "p")
    target = ExternalAgentTarget(
        runner=runner,
        bundle=build_bundle(
            fixture_manifest(tmp_path, "AsksForModel", capabilities=MODEL_CAPABILITIES)
        ),
        sandbox_limits=LIMITS,
        live=_live(ScriptedModel([]), ledger=Ledger(refuse=True)),
    )
    world_root = tmp_path / "worlds"
    world_root.mkdir()
    with pytest.raises(BudgetExceededError):
        target.run(
            TargetRequest(
                scenario=load_scenario("normal-success"),
                config=AgentConfigName.BASELINE,
                world_root=world_root,
                max_wall_seconds=5,
                cancel=None,
            )
        )
    assert runner.sessions == []
    assert list(world_root.iterdir()) == []


def test_a_live_model_needs_a_ledger(tmp_path: Path) -> None:
    live = LiveInference(
        broker=InferenceBroker(
            inference=ScriptedModel([]),
            evidence="live_provider",
            provider="p",
            model="m",
            max_model_calls=1,
            max_total_tokens=1,
            max_completion_tokens=1,
        ),
        ledger=None,
    )
    with pytest.raises(ValueError, match="ledger"):
        ExternalAgentTarget(
            runner=LocalProcessRunner(tmp_path),
            bundle=build_bundle(fixture_manifest(tmp_path, "Succeeds")),
            sandbox_limits=LIMITS,
            live=live,
        )
