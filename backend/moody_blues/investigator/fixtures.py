"""OFFLINE stand-ins for the Investigator's model. Everything here is ``offline_fixture``.

These play back or compute tool calls so that the workflow can be exercised without a provider.
They show that the machinery works. They are never evidence of what a real model does, and a
fixture that reacts to observations demonstrates only that observations reach the model's input.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from moody_blues.contracts.inference import InferenceRequest, InferenceResult, TokenUsage, ToolCall
from moody_blues.investigator.model import CONCLUDE_TOOL, PROPOSE_TOOL

FIXTURE_MODEL = "offline-fixture"


def tool_result(
    name: str, arguments: dict[str, Any] | str, *, finish_reason: str = "tool_calls"
) -> InferenceResult:
    text = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return InferenceResult(
        provider="fixture",
        requested_model=FIXTURE_MODEL,
        reported_model=FIXTURE_MODEL,
        response_id="fixture",
        content=None,
        tool_calls=[ToolCall(id="call_1", name=name, arguments_json=text)],
        finish_reason=finish_reason,
        usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        latency_ms=1,
    )


def experiment_program(
    world: str, *, config: str = "baseline", faults: list[dict[str, Any]] | None = None
) -> str:
    """A complete program of the shape a model is asked to write: run, inspect, branch, finish."""
    run: dict[str, Any] = {
        "protocol": "mb-exp/1",
        "action": "run_target_agent",
        "scenario_id": world,
        "config": config,
    }
    if faults is not None:
        run["faults"] = faults
    return f"""\
RUN = {run!r}
P = "mb-exp/1"
seen = EXPERIMENT_INPUT["observations"]
runs = [o for o in seen if o["kind"] == "target_run"]
if not runs:
    emit(RUN)
elif len(seen) == 1:
    emit({{"protocol": P, "action": "inspect_observation", "run_ref": runs[0]["run_ref"],
          "section": "tool_trace"}})
elif len(seen) == 2:
    emit({{"protocol": P, "action": "inspect_observation", "run_ref": runs[0]["run_ref"],
          "section": "state_summary"}})
else:
    bad = runs[0]["oracle_verdict"] == "VIOLATION"
    emit({{"protocol": P, "action": "finish_experiment",
          "conclusion": "behavior_observed" if bad else "behavior_not_observed",
          "summary": "finished"}})
"""


def hypothesis(number: int, motivated_by: Sequence[str] = (), **overrides: Any) -> dict[str, Any]:
    return {
        "hypothesis_id": f"h{number}",
        "behavior": "recovery after a misleading write response",
        "suspected_mechanism": "the agent repeats or misreports the write",
        "motivating_observations": list(motivated_by),
        "motivation": "fixture",
        "predicted_observation": "a violation finding",
        "failure_discriminator": "the Oracle verdict",
        "revises": None,
    } | overrides


def propose(
    number: int,
    code: str,
    *,
    motivated_by: Sequence[str] = (),
    assessments: Sequence[dict[str, Any]] = (),
    label: str | None = None,
    **hypothesis_overrides: Any,
) -> InferenceResult:
    return tool_result(
        PROPOSE_TOOL,
        {
            "assessments": list(assessments),
            "hypothesis": hypothesis(number, motivated_by, **hypothesis_overrides),
            "experiment": {
                "label": label or f"fixture-{number}",
                "rationale": "fixture",
                "motivated_by": list(motivated_by),
                "python_code": code,
            },
        },
    )


def conclude(
    conclusion: str = "no_violation_found", claimed: Sequence[dict[str, Any]] = ()
) -> InferenceResult:
    return tool_result(
        CONCLUDE_TOOL,
        {
            "assessments": [],
            "conclusion": conclusion,
            "claimed_findings": list(claimed),
            "reasoning": "fixture",
        },
    )


Reply = InferenceResult | Callable[[InferenceRequest], InferenceResult]


class ScriptedInvestigatorModel:
    """TEST DOUBLE. Plays ``replies`` in order and records every request it receives."""

    def __init__(self, replies: Sequence[Reply]) -> None:
        self._replies = list(replies)
        self.requests: list[InferenceRequest] = []

    def complete(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        if not self._replies:
            raise AssertionError("ScriptedInvestigatorModel ran out of replies")
        reply = self._replies.pop(0)
        return reply if isinstance(reply, InferenceResult) else reply(request)


class ObservationDrivenFixture:
    """TEST DOUBLE that branches on the observations in its prompt. Not a model.

    It tries a list of fault selections in order, moving on while the target recovers, and
    concludes at the first Oracle violation.
    """

    def __init__(self, world: str, fault_sequence: Sequence[list[dict[str, Any]]]) -> None:
        self._world = world
        self._sequence = list(fault_sequence)

    def complete(self, request: InferenceRequest) -> InferenceResult:
        document = json.loads(str(request.messages[-1].content))
        observations: list[dict[str, Any]] = document["observations"]
        ids = [o["observation_id"] for o in observations]
        for observation in observations:
            for run in observation.get("runs", []):
                if run["oracle"]["verdict"] == "VIOLATION":
                    codes = run["oracle"]["finding_codes"]
                    return conclude(
                        "violation_found",
                        [
                            {
                                "experiment_id": observation["experiment_id"],
                                "finding_code": next(
                                    (c for c in codes if c != "response_state_divergence"),
                                    codes[0],
                                ),
                                "statement": "fixture",
                            }
                        ],
                    )
        if len(observations) >= len(self._sequence):
            return conclude()
        number = len(observations) + 1
        return propose(
            number,
            experiment_program(self._world, faults=self._sequence[len(observations)]),
            motivated_by=ids[-1:],
            assessments=[
                {
                    "hypothesis_id": f"h{number - 1}",
                    "status": "refuted",
                    "cited_observations": ids[-1:],
                    "reasoning": "fixture",
                }
            ]
            if ids
            else [],
            revises=f"h{number - 1}" if ids else None,
        )
