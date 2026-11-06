"""Two deterministic decision policies. These are scripts: no model runs here.

They prove the integration boundary, and that the Oracle tells them apart. They say nothing about
how any LLM agent behaves.
"""

from __future__ import annotations

import hashlib
from typing import Any

from moody_blues_sdk import AgentAdapter, AgentResult, ExecutionContext, ToolClient, ToolResult

MAX_ATTEMPTS = 3


def _attributes(context: ExecutionContext) -> dict[str, Any]:
    customer = context.task.customer
    return {"name": customer.name, "email": customer.email, "metadata": customer.metadata}


def _is_target(row: dict[str, Any], context: ExecutionContext) -> bool:
    customer = context.task.customer
    stored: dict[str, str] = row.get("metadata") or {}
    return (
        row.get("name") == customer.name
        and row.get("email") == customer.email
        and all(stored.get(k) == v for k, v in customer.metadata.items())
    )


def _find_in_crm(context: ExecutionContext, tools: ToolClient) -> tuple[str | None, ToolResult]:
    """Look the customer up, rather than believing what a write said."""
    found = tools.call("search_customers", email=context.task.customer.email)
    rows: list[dict[str, Any]] = (found.data or {}).get("customers", []) if found.ok else []
    matches: list[str] = [r["customer_id"] for r in rows if _is_target(r, context)]
    return (matches[0] if matches else None), found


class CarefulAgent(AgentAdapter):
    """Uses one idempotency key throughout, and reports only what a read confirmed."""

    agent_id = "acme-crm-careful"
    name = "Acme CRM agent (careful script)"

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        email = context.task.customer.email
        key = "acme-" + hashlib.sha256(email.encode()).hexdigest()[:24]
        for _ in range(MAX_ATTEMPTS):
            created = tools.call("create_customer", client_request_id=key, **_attributes(context))
            customer_id, read = _find_in_crm(context, tools)
            if customer_id is not None:
                return AgentResult.completed(
                    customer_id=customer_id,
                    message="created and confirmed by a read",
                    evidence=tuple(r for r in (created.evidence_ref, read.evidence_ref) if r),
                )
        return AgentResult.not_completed(message=f"not confirmed after {MAX_ATTEMPTS} attempts")


class UnsafeAgent(AgentAdapter):
    """Retries a failed write with no idempotency key, and believes the last response."""

    agent_id = "acme-crm-unsafe"
    name = "Acme CRM agent (unsafe script)"

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        for _ in range(MAX_ATTEMPTS):
            created = tools.call("create_customer", **_attributes(context))
            if created.ok and created.data is not None:
                return AgentResult.completed(
                    customer_id=created.data["customer"]["customer_id"],
                    message="create_customer reported success",
                )
            if not created.retryable:
                break
        return AgentResult.not_completed(message="gave up after retrying")
