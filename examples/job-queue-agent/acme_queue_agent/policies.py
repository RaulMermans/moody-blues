"""Two deterministic decision policies. These are scripts: no model runs here.

They prove the integration boundary in a second world, and that the Oracle tells them apart. They
say nothing about how any LLM agent behaves, and neither one is given a verdict to reach.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from moody_blues_sdk import AgentAdapter, AgentResult, ExecutionContext, ToolClient

MAX_ATTEMPTS = 3
MAX_POLLS = 6


def _job(context: ExecutionContext) -> dict[str, Any]:
    return context.task.objective["job"]


def _request_key(context: ExecutionContext) -> str:
    """The task's key if it names one, otherwise one stable key of our own."""
    named = context.task.objective.get("request_key")
    if named:
        return named
    digest = hashlib.sha256(json.dumps(_job(context), sort_keys=True).encode()).hexdigest()
    return "acme-" + digest[:24]


def _find(key: str, tools: ToolClient) -> str | None:
    """Look the job up, rather than believing what a write said."""
    found = tools.call("list_jobs", request_key=key)
    rows: list[dict[str, Any]] = (found.data or {}).get("jobs", []) if found.ok else []
    return rows[0]["job_id"] if rows else None


class CarefulQueueAgent(AgentAdapter):
    """One idempotency key throughout. Reports only a status it read."""

    agent_id = "acme-queue-careful"
    name = "Acme queue agent (careful script)"

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        key = _request_key(context)
        required: list[str] = context.task.objective["required_statuses"]
        job_id: str | None = None
        for _ in range(MAX_ATTEMPTS):
            tools.call("submit_job", request_key=key, **_job(context))
            job_id = _find(key, tools)
            if job_id is not None:
                break
        if job_id is None:
            return AgentResult.not_completed(message=f"not confirmed after {MAX_ATTEMPTS} attempts")
        status: str | None = None
        for _ in range(MAX_POLLS):
            read = tools.call("get_job_status", job_id=job_id)
            status = (read.data or {}).get("status")
            if status in required:
                return AgentResult.completed(
                    record_id=job_id,
                    message=f"read back as {status}",
                    evidence=(read.evidence_ref,) if read.evidence_ref else (),
                )
            if status == "failed":
                break
        return AgentResult.not_completed(record_id=job_id, message=f"last read: {status}")


class UnsafeQueueAgent(AgentAdapter):
    """Retries a failed submit with no key, and believes the last response."""

    agent_id = "acme-queue-unsafe"
    name = "Acme queue agent (unsafe script)"

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        for _ in range(MAX_ATTEMPTS):
            submitted = tools.call("submit_job", **_job(context))
            if submitted.ok and submitted.data is not None:
                return AgentResult.completed(
                    record_id=submitted.data["job"]["job_id"],
                    message="submit_job reported success",
                )
            if not submitted.retryable:
                break
        return AgentResult.not_completed(message="gave up after retrying")
