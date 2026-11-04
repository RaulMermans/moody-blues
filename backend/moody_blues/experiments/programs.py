"""Developer-authored experiment programs. These run inside the sandbox.

They are fixed scripts, not an Investigator: nothing here forms or adapts a hypothesis, and
their results are never autonomous discoveries (evidence records ``developer_script``).
Each one is plain Python that reads ``EXPERIMENT_INPUT`` and calls ``emit`` once per step.
"""

from __future__ import annotations

import json

from pydantic import JsonValue

_PROBE = """\
PLAN = __PLAN__
PROTOCOL = "mb-exp/1"
observations = EXPERIMENT_INPUT["observations"]

if not observations:
    action = {"protocol": PROTOCOL, "action": "run_target_agent",
              "scenario_id": PLAN["scenario_id"], "config": PLAN["config"]}
    if PLAN["faults"] is not None:
        action["faults"] = PLAN["faults"]
    emit(action)
elif len(observations) == 1:
    emit({"protocol": PROTOCOL, "action": "inspect_observation",
          "run_ref": observations[0]["run_ref"], "section": "tool_trace"})
elif len(observations) == 2:
    emit({"protocol": PROTOCOL, "action": "inspect_observation",
          "run_ref": observations[0]["run_ref"], "section": "state_summary"})
else:
    run = observations[0]
    trace = observations[1]["tool_calls"]
    errors = sum(1 for call in trace if not call["ok"])
    seen = PLAN["looking_for"] in run["finding_codes"]
    emit({"protocol": PROTOCOL, "action": "finish_experiment",
          "conclusion": "behavior_observed" if seen else "behavior_not_observed",
          "summary": f"looked for {PLAN['looking_for']}; saw {len(trace)} calls, {errors} errors, "
                     f"{observations[2]['objective_matching_records']} matching records"})
"""


def probe_program(
    *,
    scenario_id: str,
    config: str,
    looking_for: str,
    faults: list[dict[str, JsonValue]] | None = None,
) -> str:
    """Run the target once, inspect the trace and state, then finish."""
    plan = {
        "scenario_id": scenario_id,
        "config": config,
        "faults": faults,
        "looking_for": looking_for,
    }
    return _PROBE.replace("__PLAN__", repr(json.loads(json.dumps(plan))))


UNAUTHORIZED_ACTION_PROGRAM = """\
emit({"protocol": "mb-exp/1", "action": "execute_sql",
      "sql": "UPDATE customers SET email = 'attacker@example.com'"})
"""

HANGING_PROGRAM = """\
while True:
    pass
"""

SLEEPING_PROGRAM = """\
import time
time.sleep(60)
"""
