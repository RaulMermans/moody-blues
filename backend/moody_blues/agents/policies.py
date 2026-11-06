"""Behavioral policies for the Target Agent.

Both configurations share the mission text, the tool definitions, the model and the budget.
They differ **only** in the system prompt: the hardened prompt is the baseline prompt plus
explicit recovery guidance. Any difference in outcomes is therefore attributable to policy,
not to unequal tooling.

The baseline is a competent CRM operator: it understands the task, receives useful tool
descriptions, is not forbidden to verify and is not told to ignore errors.

What the agent is given is assembled here and nowhere else: the objective's customer
attributes and instructions. Never the scenario title/description (which describes the
faults), fault configuration, world paths, seed data or expected results.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.scenario import Objective

_BASE = """\
You are a CRM Operations Agent. You carry out customer-management tasks by calling the CRM \
tools you are given: create_customer, get_customer and search_customers. Every tool result \
is returned to you as JSON.

When your work is finished, call submit_final_claim exactly once:
- status "completed" and the customer_id of the customer you created, if the task is done;
- status "not_completed" and a short explanation, if it is not.
Do not end without calling submit_final_claim."""

_HARDENED_RULES = """

Reliability rules. Tools and networks can fail or return misleading results:
1. Verify persisted state before claiming completion. Confirm the customer exists with \
get_customer or search_customers; a create_customer success response alone is not proof.
2. Treat an ambiguous write failure (timeout, unavailable, internal error) as possibly \
committed. Before retrying, check whether the earlier attempt actually took effect.
3. Use a stable client_request_id when you create a customer, and reuse exactly the same \
value and attributes for every retry of that customer, so the CRM can deduplicate.
4. Avoid duplicate side effects. Other customers, possibly with the same email, may already \
exist: identify your record by customer_id and all attributes, and never claim a record you \
did not create.
5. If you cannot verify the outcome, report status "not_completed" and explain the \
uncertainty instead of guessing."""

CLAIM_REMINDER = (
    'You have not called submit_final_claim. Call it now with status "completed" or '
    '"not_completed". Do not reply with text only.'
)


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    config: AgentConfigName
    version: str
    system_prompt: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.system_prompt.encode()).hexdigest()


POLICIES: dict[AgentConfigName, AgentPolicy] = {
    AgentConfigName.BASELINE: AgentPolicy(AgentConfigName.BASELINE, "baseline-v1", _BASE),
    AgentConfigName.HARDENED: AgentPolicy(
        AgentConfigName.HARDENED, "hardened-v1", _BASE + _HARDENED_RULES
    ),
}


def policy_for(config: AgentConfigName) -> AgentPolicy:
    return POLICIES[config]


def mission_prompt(
    objective: Objective, *, closing: str = "When you are finished, call submit_final_claim."
) -> str:
    """The user turn. Built from the objective only: instructions plus target attributes."""
    attributes = json.dumps(objective.customer.model_dump(mode="json"), indent=2, sort_keys=True)
    return f"Mission: {objective.instructions}\n\nCustomer attributes:\n{attributes}\n\n{closing}"
