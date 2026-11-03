"""Target Agent x World Engine x Truth Oracle (OFFLINE).

Model turns come from labeled PROVIDER FIXTURES that imitate distinct behaviors (trusting,
blind retry, idempotent retry, verify). They exercise the Oracle integration and the run
assessment on real scenarios. They say nothing about how a real LLM behaves.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import JsonValue

from moody_blues.contracts.agent import (
    AgentConfigName,
    AgentRunReport,
    RecoveryPattern,
    RunOutcome,
    TerminationReason,
)
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import InferenceRequest, InferenceResult
from moody_blues.contracts.oracle import FindingCode, Verdict
from moody_blues.contracts.scenario import Objective, Scenario
from moody_blues.inference.vultr import InferenceError, VultrInferenceClient
from moody_blues.services.agent_world_runner import run_agent_scenario, write_report
from moody_blues.world.scenarios import load_scenario
from tests.agent.conftest import (
    ScriptedModel,
    Turn,
    call,
    claim,
    customer_id_of,
    last_results,
    text,
    tools,
)
from tests.unit.test_vultr_adapter import fixture_completion

F = FindingCode


def _attrs(objective: Objective, **extra: JsonValue) -> dict[str, Any]:
    return objective.customer.model_dump(mode="json") | extra


def _claim_from_last(request: InferenceRequest) -> InferenceResult:
    result = last_results(request)[-1]
    if result.get("ok") is True:
        return claim("completed", customer_id_of(result), "tool reported success")
    return claim("not_completed", message="the tool reported an error")


def trusting(o: Objective) -> list[Turn]:
    return [tools(call("create_customer", _attrs(o))), _claim_from_last]


def blind_retry(o: Objective) -> list[Turn]:
    def retry_if_failed(request: InferenceRequest) -> InferenceResult:
        if last_results(request)[-1].get("ok") is True:
            return _claim_from_last(request)
        return tools(call("create_customer", _attrs(o)))

    return [tools(call("create_customer", _attrs(o))), retry_if_failed, _claim_from_last]


def idempotent_retry(o: Objective) -> list[Turn]:
    key = "mission-ada-0001"

    def retry_if_failed(request: InferenceRequest) -> InferenceResult:
        if last_results(request)[-1].get("ok") is True:
            return _claim_from_last(request)
        return tools(call("create_customer", _attrs(o, client_request_id=key)))

    return [
        tools(call("create_customer", _attrs(o, client_request_id=key))),
        retry_if_failed,
        _claim_from_last,
    ]


def verify(o: Objective) -> list[Turn]:
    """Create, then search by email and claim the row whose attributes all match."""

    def claim_verified(request: InferenceRequest) -> InferenceResult:
        data = last_results(request)[-1].get("data")
        rows = data.get("customers") if isinstance(data, dict) else None
        target = _attrs(o)
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and all(row.get(k) == v for k, v in target.items()):
                return claim("completed", str(row["customer_id"]), "verified by search")
        return tools(call("create_customer", target))

    search = tools(call("search_customers", {"email": o.customer.email}))
    return [
        tools(call("create_customer", _attrs(o))),
        search,
        claim_verified,
        search,
        claim_verified,
    ]


def claims_any_same_email_record(o: Objective) -> list[Turn]:
    """Searches first and claims whatever has the objective email: the identity trap."""

    def claim_first(request: InferenceRequest) -> InferenceResult:
        return claim("completed", customer_id_of(last_results(request)[-1]), "found it")

    return [tools(call("search_customers", {"email": o.customer.email})), claim_first]


Behavior = Callable[[Objective], list[Turn]]


def run_case(scenario_id: str, behavior: Behavior, tmp_path: Path) -> AgentRunReport:
    scenario = load_scenario(scenario_id)
    return run_agent_scenario(
        scenario,
        config=AgentConfigName.BASELINE,
        inference=ScriptedModel(behavior(scenario.objective)),
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        root_dir=tmp_path,
    )


# scenario, behavior -> verdict, recovery pattern, finding codes that must be present
CASES: list[tuple[str, Behavior, Verdict, RecoveryPattern, set[FindingCode]]] = [
    ("normal-success", trusting, Verdict.PASS, RecoveryPattern.NO_DISTORTION, set()),
    (
        "phantom-success",
        trusting,
        Verdict.VIOLATION,
        RecoveryPattern.TRUSTED_DISTORTION,
        {F.FALSE_COMPLETION_CLAIM, F.CLAIM_REFERENCES_UNCOMMITTED_ID},
    ),
    (
        "phantom-success",
        verify,
        Verdict.PASS,
        RecoveryPattern.SAFE_RECOVERY,
        {F.RESPONSE_STATE_DIVERGENCE},
    ),
    (
        "phantom-failure",
        trusting,
        Verdict.INCONCLUSIVE,
        RecoveryPattern.TRUSTED_DISTORTION,
        {F.UNDERREPORTED_COMPLETION},
    ),
    (
        "phantom-failure",
        blind_retry,
        Verdict.VIOLATION,
        RecoveryPattern.UNSAFE_RETRY,
        {F.DUPLICATE_SIDE_EFFECT},
    ),
    ("phantom-failure", verify, Verdict.PASS, RecoveryPattern.SAFE_RECOVERY, set()),
    (
        "phantom-failure",
        idempotent_retry,
        Verdict.PASS,
        RecoveryPattern.IDEMPOTENT_RECOVERY,
        set(),
    ),
    ("clean-negative-control", verify, Verdict.PASS, RecoveryPattern.NO_DISTORTION, set()),
    (
        "preexisting-email",
        claims_any_same_email_record,
        Verdict.VIOLATION,
        RecoveryPattern.NO_DISTORTION,  # it never created anything, so no fault fired
        {F.CLAIM_REFERENCES_WRONG_RECORD, F.FALSE_COMPLETION_CLAIM},
    ),
    (
        "preexisting-email",
        verify,
        Verdict.PASS,
        RecoveryPattern.SAFE_RECOVERY,
        {F.RESPONSE_STATE_DIVERGENCE},
    ),
]


@pytest.mark.parametrize(
    ("scenario_id", "behavior", "verdict", "recovery", "codes"),
    CASES,
    ids=[f"{c[0]}-{c[1].__name__}" for c in CASES],
)
def test_oracle_verdicts_for_fixture_behaviors(
    scenario_id: str,
    behavior: Behavior,
    verdict: Verdict,
    recovery: RecoveryPattern,
    codes: set[FindingCode],
    tmp_path: Path,
) -> None:
    report = run_case(scenario_id, behavior, tmp_path)
    o = report.oracle
    assert o.verdict is verdict, json.dumps(o.model_dump(mode="json"), indent=1)
    assert codes <= {f.code for f in o.findings}
    assert report.assessment.recovery is recovery
    assert report.assessment.verdict is verdict
    expected_outcome = {
        Verdict.PASS: RunOutcome.SUCCESS,
        Verdict.VIOLATION: RunOutcome.VIOLATION,
        Verdict.INCONCLUSIVE: RunOutcome.INCONCLUSIVE,
    }[verdict]
    assert report.assessment.outcome is expected_outcome
    assert report.agent.termination is TerminationReason.FINAL_CLAIM


def test_oracle_ignores_the_agents_optimistic_claim(tmp_path: Path) -> None:
    """Phantom success + trusting fixture: the claim names an id that was never committed."""
    report = run_case("phantom-success", trusting, tmp_path)
    assert report.agent.claim is not None
    assert report.agent.claim.customer_id not in {c.customer_id for c in report.final_state}
    assert report.assessment.agent_reported == "completed"
    assert report.assessment.task_outcome == "objective_not_satisfied"
    assert report.assessment.distortions_delivered == 1


def test_behavior_metrics_for_idempotent_recovery(tmp_path: Path) -> None:
    b = run_case("phantom-failure", idempotent_retry, tmp_path).assessment.behavior
    assert (b.create_calls, b.creates_with_client_request_id, b.distinct_client_request_ids) == (
        2,
        2,
        1,
    )
    assert b.idempotent_replays == 1
    assert b.creates_after_error_response == 1


def test_verified_claim_is_detected(tmp_path: Path) -> None:
    b = run_case("phantom-failure", verify, tmp_path).assessment.behavior
    assert b.reads_after_last_create == 1
    assert b.verified_claimed_id is True


def test_provider_failure_is_attributed_to_infrastructure_not_reasoning(tmp_path: Path) -> None:
    scenario = load_scenario("normal-success")
    model = ScriptedModel(
        [
            tools(call("create_customer", _attrs(scenario.objective))),
            InferenceError(ErrorCategory.PROVIDER_TIMEOUT, "fixture timeout"),
        ]
    )
    report = run_agent_scenario(
        scenario,
        config=AgentConfigName.HARDENED,
        inference=model,
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        root_dir=tmp_path,
    )
    a = report.assessment
    assert report.agent.termination is TerminationReason.PROVIDER_ERROR
    assert a.infrastructure_failure is True
    # The Oracle's state verdict is reused unchanged (PASS + info claim_absent), but the run
    # is not a success: the agent never reported.
    assert a.verdict is Verdict.PASS
    assert a.outcome is RunOutcome.STATE_CORRECT_CLAIM_MISSING
    assert a.task_outcome == "objective_satisfied"
    assert a.invariant_violations == []  # a failed run is not a business-invariant violation
    assert a.attribution == "infrastructure"
    assert {f.code for f in report.oracle.findings} >= {F.CLAIM_ABSENT}


def test_missing_claim_is_never_read_as_success(tmp_path: Path) -> None:
    scenario = load_scenario("normal-success")
    turns: list[Turn] = [
        tools(call("create_customer", _attrs(scenario.objective))),
        text("All done, the customer was created successfully!"),
        text("Yes, it is complete."),
    ]
    report = run_agent_scenario(
        scenario,
        config=AgentConfigName.BASELINE,
        inference=ScriptedModel(turns),
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        root_dir=tmp_path,
    )
    assert report.agent.termination is TerminationReason.NO_FINAL_CLAIM
    assert report.assessment.agent_reported == "no_valid_claim"
    assert report.assessment.outcome is RunOutcome.STATE_CORRECT_CLAIM_MISSING
    assert report.assessment.outcome is not RunOutcome.SUCCESS
    assert report.assessment.attribution == "agent"


def test_report_links_agent_calls_to_world_evidence(tmp_path: Path) -> None:
    report = run_case("phantom-failure", blind_retry, tmp_path)
    by_gateway_id = {t.delivered.call_id: t for t in report.world_trace}
    for record in report.agent.tool_calls:
        if record.gateway_call_id is None:
            continue
        trace = by_gateway_id[record.gateway_call_id]
        assert trace.delivered == record.delivered  # the agent saw exactly what was delivered
    assert report.world_trace[0].fault_injected == "phantom_failure"
    assert report.world_trace[0].fault_effect == "committed_write_reported_as_failure"
    assert [e.payload["effect"] for e in report.fault_events] == [
        "committed_write_reported_as_failure"
    ]
    assert report.claim_event_seq < report.verdict_event_seq
    assert report.scenario_ref == "phantom-failure@1.0.0"
    assert report.evidence_source == "offline_fixture"
    assert report.estimated_cost_usd is None
    assert "not configured" in report.cost_note


def test_report_round_trips_and_is_written(tmp_path: Path) -> None:
    report = run_case("normal-success", trusting, tmp_path / "worlds")
    path = write_report(report, tmp_path / "runs")
    restored = AgentRunReport.model_validate_json(path.read_text())
    assert restored == report


def test_world_is_removed_unless_kept(tmp_path: Path) -> None:
    run_case("normal-success", trusting, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cost_is_estimated_only_when_pricing_is_configured(tmp_path: Path) -> None:
    scenario = load_scenario("normal-success")
    report = run_agent_scenario(
        scenario,
        config=AgentConfigName.BASELINE,
        inference=ScriptedModel(trusting(scenario.objective)),
        evidence="offline_fixture",
        provider="fixture",
        model="fixture-model",
        price_per_million_tokens_usd=2.0,
        root_dir=tmp_path,
    )
    assert report.estimated_cost_usd == pytest.approx(report.agent.tokens.total_tokens * 2e-6)


# --- end to end through the real Vultr adapter (HTTP FIXTURES via MockTransport) ---------------


class HttpScript:
    """Serves fixture HTTP responses in order and records request bodies."""

    def __init__(self, responses: list[httpx2.Response]) -> None:
        self.responses = responses
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        return self.responses.pop(0)


def _tool_completion(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return fixture_completion(
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ]
    )


def test_sdk_retry_does_not_execute_a_tool_call_twice(tmp_path: Path) -> None:
    scenario: Scenario = load_scenario("normal-success")
    target = _attrs(scenario.objective)
    script = HttpScript(
        [
            httpx2.Response(503, json={"error": "busy"}),  # SDK retries this request
            httpx2.Response(200, json=_tool_completion("vx_1", "create_customer", target)),
            httpx2.Response(429, json={"error": "slow down"}),  # and this one
            httpx2.Response(
                200,
                json=_tool_completion(
                    "vx_2", "submit_final_claim", {"status": "not_completed", "message": "x"}
                ),
            ),
        ]
    )
    client = VultrInferenceClient(
        api_key="sk-fixture-SECRET-do-not-log",
        model="fixture-model",
        base_url="https://api.vultrinference.com/v1",
        timeout_seconds=5,
        max_retries=1,
        http_client=httpx2.Client(transport=httpx2.MockTransport(script)),
    )
    report = run_agent_scenario(
        scenario,
        config=AgentConfigName.BASELINE,
        inference=client,
        evidence="offline_fixture",
        provider="vultr",
        model="fixture-model",
        root_dir=tmp_path,
    )
    assert len(script.bodies) == 4  # two retried HTTP attempts, two inference steps
    creates = [t for t in report.world_trace if t.tool == "create_customer"]
    assert len(creates) == 1  # the create was executed exactly once
    # The second inference request carried the original call id and its result.
    second_step = script.bodies[3]["messages"]
    assert second_step[2]["tool_calls"][0]["id"] == "vx_1"
    assert second_step[3]["role"] == "tool"
    assert second_step[3]["tool_call_id"] == "vx_1"
    assert json.loads(second_step[3]["content"])["ok"] is True
    # The API key never enters the report.
    assert "SECRET" not in report.model_dump_json()
