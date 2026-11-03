"""Target Agent runtime: protocol, validation, budgets and termination (OFFLINE).

The model is a labeled PROVIDER FIXTURE (``ScriptedModel``); the CRM is a real SQLite world.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from threading import Event

import pytest
from pydantic import JsonValue

from moody_blues.agents.policies import CLAIM_REMINDER, POLICIES, mission_prompt, policy_for
from moody_blues.agents.target import TargetAgent
from moody_blues.agents.tooling import agent_tool_specs
from moody_blues.contracts.agent import (
    AgentBudget,
    AgentConfigName,
    AgentTrajectory,
    ClaimOutcome,
    TerminationReason,
    ToolCallDisposition,
)
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import (
    AssistantToolCallMessage,
    ChatMessage,
    InferenceRequest,
    ToolCall,
    ToolResultMessage,
    validate_tool_protocol,
)
from moody_blues.contracts.world import ClaimStatus, EventKind, ToolResponse
from moody_blues.inference.vultr import InferenceError
from moody_blues.world.engine import World
from moody_blues.world.gateway import derive_customer_id
from tests.agent.conftest import ScriptedModel, Turn, call, claim, text, tools
from tests.world.conftest import ADA, make_scenario

ADA_ID = derive_customer_id(7, 1)  # make_scenario seed 7, first gateway call


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with World(make_scenario(), root_dir=tmp_path) as w:
        yield w


def run(
    world: World,
    turns: list[Turn],
    *,
    config: AgentConfigName = AgentConfigName.BASELINE,
    budget: AgentBudget | None = None,
    cancel: Event | None = None,
) -> tuple[AgentTrajectory, ScriptedModel]:
    model = ScriptedModel(turns)
    agent = TargetAgent(policy=policy_for(config), inference=model, budget=budget)
    return agent.run(world.gateway, world.scenario.objective, cancel=cancel), model


def gateway_calls(world: World) -> int:
    with world.view() as view:
        return sum(1 for e in view.events() if e.kind is EventKind.TOOL_CALL_REQUESTED)


def create_call(**overrides: JsonValue) -> Turn:
    return tools(call("create_customer", ADA | overrides))


# --- happy path and protocol ---------------------------------------------------------------------


def test_create_verify_claim_trajectory(world: World) -> None:
    traj, model = run(
        world,
        [
            create_call(),
            tools(call("get_customer", {"customer_id": ADA_ID})),
            claim("completed", ADA_ID, "created and verified"),
        ],
    )
    assert traj.termination is TerminationReason.FINAL_CLAIM
    assert traj.claim_outcome is ClaimOutcome.VALID
    assert traj.claim is not None
    assert traj.claim.status is ClaimStatus.COMPLETED
    assert traj.claim.customer_id == ADA_ID
    assert [s.index for s in traj.steps] == [1, 2, 3]
    executed = [c for c in traj.tool_calls if c.disposition is ToolCallDisposition.EXECUTED]
    assert [c.gateway_call_id for c in executed] == ["call_0001", "call_0002"]
    assert gateway_calls(world) == 2
    # The model received exactly what the gateway delivered, under its original call id.
    create = executed[0]
    assert create.delivered is not None
    assert ToolResponse.model_validate_json(create.result_content) == create.delivered
    assert model.requests[1].messages[-1] == ToolResultMessage(
        tool_call_id=create.tool_call_id, content=create.result_content
    )


def test_every_request_and_the_final_history_obey_the_tool_protocol(world: World) -> None:
    traj, model = run(
        world,
        [
            tools(call("search_customers", {}), call("create_customer", ADA), content="Working."),
            claim("completed", ADA_ID),
        ],
    )
    for request in model.requests:
        validate_tool_protocol(request.messages)
    validate_tool_protocol(traj.messages)
    roles = [type(m).__name__ for m in traj.messages]
    assert roles == [
        "ChatMessage",
        "ChatMessage",
        "AssistantToolCallMessage",
        "ToolResultMessage",
        "ToolResultMessage",
        "AssistantToolCallMessage",
        "ToolResultMessage",
    ]
    first_turn = traj.messages[2]
    assert isinstance(first_turn, AssistantToolCallMessage)
    assert first_turn.content == "Working."  # assistant text alongside calls is preserved


def test_multiple_tool_calls_execute_sequentially_in_order(world: World) -> None:
    traj, _ = run(
        world,
        [
            tools(
                call("create_customer", ADA),
                call("search_customers", {"email": ADA["email"]}),
                call("get_customer", {"customer_id": ADA_ID}),
            ),
            claim("completed", ADA_ID),
        ],
    )
    executed = [c for c in traj.tool_calls if c.disposition is ToolCallDisposition.EXECUTED]
    assert [(c.name, c.gateway_call_id) for c in executed] == [
        ("create_customer", "call_0001"),
        ("search_customers", "call_0002"),
        ("get_customer", "call_0003"),
    ]
    # The search ran after the create committed, so it saw the new row.
    assert executed[1].delivered is not None
    assert executed[1].delivered.data is not None
    assert executed[1].delivered.data["count"] == 1


# --- validation --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad_call", "disposition"),
    [
        (call("delete_customer", {"customer_id": "x"}), ToolCallDisposition.UNKNOWN_TOOL),
        (call("create_customer", '{"name": "Ada", '), ToolCallDisposition.MALFORMED_JSON),
        (call("create_customer", "[1, 2]"), ToolCallDisposition.INVALID_ARGUMENTS),
        (
            call("create_customer", ADA | {"email": "not-an-email"}),
            ToolCallDisposition.INVALID_ARGUMENTS,
        ),
        (
            call("create_customer", ADA | {"is_admin": True}),
            ToolCallDisposition.INVALID_ARGUMENTS,
        ),
        (call("get_customer", {}), ToolCallDisposition.INVALID_ARGUMENTS),
        (call("search_customers", "x" * 9000), ToolCallDisposition.INVALID_ARGUMENTS),
    ],
)
def test_invalid_calls_are_rejected_before_the_gateway(
    world: World, bad_call: ToolCall, disposition: ToolCallDisposition
) -> None:
    traj, model = run(world, [tools(bad_call), claim("not_completed", message="gave up")])
    rejected = traj.tool_calls[0]
    assert rejected.disposition is disposition
    assert rejected.gateway_call_id is None
    assert gateway_calls(world) == 0  # nothing reached the World Engine
    payload = json.loads(rejected.result_content)
    assert payload["ok"] is False
    assert payload["error"]["code"] == disposition.value
    assert len(payload["error"]["message"]) <= 500
    # The error went back to the model under the original id.
    assert model.requests[1].messages[-1] == ToolResultMessage(
        tool_call_id=rejected.tool_call_id, content=rejected.result_content
    )
    assert traj.termination is TerminationReason.FINAL_CLAIM


def test_empty_arguments_mean_an_empty_object(world: World) -> None:
    traj, _ = run(world, [tools(call("search_customers", "")), claim("not_completed")])
    assert traj.tool_calls[0].disposition is ToolCallDisposition.EXECUTED


def test_invalid_final_claim_is_explicit_and_the_model_may_retry(world: World) -> None:
    traj, _ = run(
        world,
        [
            tools(call("submit_final_claim", {"status": "done"})),
            tools(call("submit_final_claim", "{not json")),
            claim("not_completed", message="ok"),
        ],
    )
    assert [c.disposition for c in traj.tool_calls] == [
        ToolCallDisposition.FINAL_CLAIM_INVALID,
        ToolCallDisposition.FINAL_CLAIM_INVALID,
        ToolCallDisposition.FINAL_CLAIM_ACCEPTED,
    ]
    assert traj.invalid_claim_attempts == 2
    assert traj.claim_outcome is ClaimOutcome.VALID


def test_only_invalid_claims_leave_no_claim(world: World) -> None:
    traj, _ = run(
        world,
        [tools(call("submit_final_claim", {"status": "done"}))] * 2,
        budget=AgentBudget(max_steps=2),
    )
    assert traj.claim is None
    assert traj.claim_outcome is ClaimOutcome.INVALID
    assert traj.termination is TerminationReason.MAX_STEPS


def test_empty_customer_id_in_claim_is_treated_as_absent(world: World) -> None:
    traj, _ = run(world, [claim("not_completed", "", "nothing created")])
    assert traj.claim is not None
    assert traj.claim.customer_id is None


def test_calls_after_the_claim_in_the_same_turn_are_not_executed(world: World) -> None:
    traj, _ = run(
        world,
        [
            tools(
                call("create_customer", ADA),
                call("submit_final_claim", {"status": "completed", "customer_id": ADA_ID}),
                call("create_customer", ADA),
            )
        ],
    )
    assert [c.disposition for c in traj.tool_calls] == [
        ToolCallDisposition.EXECUTED,
        ToolCallDisposition.FINAL_CLAIM_ACCEPTED,
        ToolCallDisposition.SKIPPED_AFTER_FINAL_CLAIM,
    ]
    assert gateway_calls(world) == 1
    validate_tool_protocol(traj.messages)  # the skipped call still got its result message


# --- no tool calls / optimism -------------------------------------------------------------------


def test_text_only_reply_gets_one_reminder_then_a_claim(world: World) -> None:
    traj, model = run(world, [text("Let me think."), claim("not_completed")])
    assert traj.termination is TerminationReason.FINAL_CLAIM
    assert traj.steps[0].claim_reminder_sent is True
    assert model.requests[1].messages[-2:] == [
        ChatMessage(role="assistant", content="Let me think."),
        ChatMessage(role="user", content=CLAIM_REMINDER),
    ]


def test_conversational_optimism_is_not_a_claim(world: World) -> None:
    traj, _ = run(
        world,
        [
            create_call(),
            text("Done! I have successfully created the customer."),
            text("Everything is complete."),
        ],
    )
    assert traj.termination is TerminationReason.NO_FINAL_CLAIM
    assert traj.claim is None
    assert traj.claim_outcome is ClaimOutcome.MISSING


def test_empty_model_reply_is_handled_like_text(world: World) -> None:
    empty = text("").model_copy(update={"content": None})
    traj, _ = run(world, [empty, empty], budget=AgentBudget(max_claim_reminders=1))
    assert traj.termination is TerminationReason.NO_FINAL_CLAIM
    assert len(traj.steps) == 2


# --- provider failures ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        ErrorCategory.PROVIDER_TIMEOUT,
        ErrorCategory.PROVIDER_RATE_LIMITED,
        ErrorCategory.PROVIDER_AUTH,
        ErrorCategory.PROVIDER_SERVER_ERROR,
    ],
)
def test_provider_failure_stops_the_run_with_its_category(
    world: World, category: ErrorCategory
) -> None:
    traj, _ = run(world, [create_call(), InferenceError(category, "fixture failure")])
    assert traj.termination is TerminationReason.PROVIDER_ERROR
    assert traj.error is not None
    assert traj.error.category is category
    assert traj.claim is None
    assert gateway_calls(world) == 1  # the earlier call is never replayed


def test_duplicate_tool_call_ids_in_one_turn_are_an_invalid_model_response(world: World) -> None:
    dup = tools(call("search_customers", {}, id="same"), call("get_customer", {}, id="same"))
    traj, _ = run(world, [dup])
    assert traj.termination is TerminationReason.INVALID_MODEL_RESPONSE
    assert traj.error is not None
    assert traj.error.category is ErrorCategory.PROVIDER_INVALID_RESPONSE
    assert gateway_calls(world) == 0


# --- budgets and cancellation ------------------------------------------------------------------


def test_max_steps(world: World) -> None:
    traj, model = run(
        world, [tools(call("search_customers", {}))] * 3, budget=AgentBudget(max_steps=3)
    )
    assert traj.termination is TerminationReason.MAX_STEPS
    assert len(model.requests) == 3
    assert model.remaining == 0


def test_tool_call_budget(world: World) -> None:
    traj, _ = run(
        world,
        [
            tools(*(call("search_customers", {}) for _ in range(3))),
            claim("not_completed"),
        ],
        budget=AgentBudget(max_tool_calls=2),
    )
    assert [c.disposition for c in traj.tool_calls[:3]] == [
        ToolCallDisposition.EXECUTED,
        ToolCallDisposition.EXECUTED,
        ToolCallDisposition.TOOL_BUDGET_EXHAUSTED,
    ]
    assert gateway_calls(world) == 2
    assert traj.termination is TerminationReason.FINAL_CLAIM  # the claim is not a CRM call


def test_token_budget(world: World) -> None:
    traj, model = run(
        world,
        [tools(call("search_customers", {}), usage=5_000), claim("not_completed")],
        budget=AgentBudget(max_total_tokens=4_000),
    )
    assert traj.termination is TerminationReason.TOKEN_BUDGET
    assert len(model.requests) == 1
    assert traj.tokens.total_tokens == 5_000


def test_missing_usage_is_estimated_and_flagged(world: World) -> None:
    traj, _ = run(world, [claim("not_completed").model_copy(update={"usage": None})])
    assert traj.tokens.complete is False
    assert traj.tokens.total_tokens > 0


def test_wall_clock_deadline(world: World) -> None:
    ticks = iter([0.0, 0.0, 61.0, 61.0])  # start, step-1 check, step-2 check, end
    model = ScriptedModel([tools(call("search_customers", {})), claim("not_completed")])
    agent = TargetAgent(
        policy=policy_for(AgentConfigName.BASELINE),
        inference=model,
        budget=AgentBudget(max_wall_seconds=60),
        monotonic=lambda: next(ticks),
    )
    traj = agent.run(world.gateway, world.scenario.objective)
    assert traj.termination is TerminationReason.WALL_TIMEOUT
    assert len(model.requests) == 1


def test_cancelled_before_start(world: World) -> None:
    cancel = Event()
    cancel.set()
    traj, model = run(world, [claim("not_completed")], cancel=cancel)
    assert traj.termination is TerminationReason.CANCELLED
    assert model.requests == []


def test_cancelled_between_tool_calls_keeps_the_protocol_valid(world: World) -> None:
    cancel = Event()

    class CancellingPort:
        def call(self, tool: str, arguments: Mapping[str, JsonValue]) -> ToolResponse:
            cancel.set()  # e.g. an operator cancels while the first call is running
            return world.gateway.call(tool, arguments)

    model = ScriptedModel(
        [tools(call("search_customers", {}), call("create_customer", ADA)), claim("completed")]
    )
    agent = TargetAgent(policy=policy_for(AgentConfigName.BASELINE), inference=model)
    traj = agent.run(CancellingPort(), world.scenario.objective, cancel=cancel)
    assert traj.termination is TerminationReason.CANCELLED
    assert [c.disposition for c in traj.tool_calls] == [
        ToolCallDisposition.EXECUTED,
        ToolCallDisposition.CANCELLED,
    ]
    assert gateway_calls(world) == 1
    validate_tool_protocol(traj.messages)


# --- what the agent is (and is not) given ------------------------------------------------------


def test_both_configurations_get_identical_tools_mission_and_budget(world: World) -> None:
    budget = AgentBudget(max_steps=4)
    requests: dict[AgentConfigName, InferenceRequest] = {}
    for config in AgentConfigName:
        _, model = run(world, [claim("not_completed")], config=config, budget=budget)
        requests[config] = model.requests[0]
    base, hard = requests[AgentConfigName.BASELINE], requests[AgentConfigName.HARDENED]
    assert base.tools == hard.tools == agent_tool_specs()
    assert base.messages[1] == hard.messages[1]  # the mission
    assert (base.max_tokens, base.temperature) == (hard.max_tokens, hard.temperature)
    base_system, hard_system = base.messages[0], hard.messages[0]
    assert isinstance(base_system, ChatMessage)
    assert isinstance(hard_system, ChatMessage)
    assert hard_system.content.startswith(base_system.content)  # policy is additive
    assert "Reliability rules" in hard_system.content
    assert "Reliability rules" not in base_system.content


def test_policy_selection_is_recorded(world: World) -> None:
    for config in AgentConfigName:
        traj, _ = run(world, [claim("not_completed")], config=config)
        assert traj.config is config
        assert traj.policy_version == POLICIES[config].version
        assert traj.policy_sha256 == POLICIES[config].sha256


def test_agent_never_sees_faults_paths_or_scenario_description(tmp_path: Path) -> None:
    scenario = make_scenario(
        faults=[{"kind": "phantom_failure", "error_message": "Upstream timed out."}],
        description="SECRET-DESCRIPTION: first create is a phantom failure",
    )
    with World(scenario, root_dir=tmp_path) as w:
        model = ScriptedModel([create_call(), claim("not_completed")])
        agent = TargetAgent(policy=policy_for(AgentConfigName.HARDENED), inference=model)
        agent.run(w.gateway, w.scenario.objective)
        db_path = str(w.db_path)
        seen = "\n".join(r.model_dump_json() for r in model.requests)
    for forbidden in (
        "SECRET-DESCRIPTION",
        "phantom",
        "fault",
        db_path,
        str(tmp_path),
        "sqlite",
        "cus_seed_grace",  # seed data is reachable only through tools, not the prompt
        "oracle",
        "verdict",
    ):
        # Word boundaries: "fault" must not match the JSON-schema keyword "default".
        assert not re.search(rf"\b{re.escape(forbidden)}\b", seen, re.IGNORECASE), forbidden
    # The distorted response itself is delivered, as the agent would see it in reality.
    assert "Upstream timed out." in seen


def test_mission_contains_objective_attributes_only(world: World) -> None:
    prompt = mission_prompt(world.scenario.objective)
    assert world.scenario.objective.instructions in prompt
    assert '"email": "ada@analytical.example"' in prompt
    assert '"tier": "platinum"' in prompt
