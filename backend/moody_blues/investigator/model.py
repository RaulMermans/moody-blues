"""The one door to the Investigator's model: budgeted calls and strict parsing of decisions.

Every call reserves its worst case first and is settled afterwards. A failed call keeps its full
reservation, because a request that errored may still have been billed. Nothing here retries.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from moody_blues.agents.target import InferencePort
from moody_blues.contracts.agent import EvidenceSource, TokenTotals
from moody_blues.contracts.common import MoodyBluesError
from moody_blues.contracts.inference import (
    ChatMessage,
    ConversationMessage,
    InferenceRequest,
    InferenceResult,
    ToolSpec,
)
from moody_blues.contracts.investigation import (
    ConcludeInvestigation,
    GenerationDiagnostic,
    ModelCallRecord,
    ProposeExperiment,
    ProposePlan,
)
from moody_blues.experiments.budget import SpendPort
from moody_blues.experiments.workspace import atomic_write, sha256_text
from moody_blues.investigator.observations import HINTS

PROPOSE_TOOL = "propose_experiment"
PLAN_TOOL = "propose_plan"
CONCLUDE_TOOL = "conclude_investigation"

_ARGUMENTS: dict[str, type[BaseModel]] = {
    PROPOSE_TOOL: ProposeExperiment,
    PLAN_TOOL: ProposePlan,
    CONCLUDE_TOOL: ConcludeInvestigation,
}
_DESCRIPTIONS = {
    PROPOSE_TOOL: "Assess earlier hypotheses, state a new one and submit its experiment program.",
    PLAN_TOOL: "Submit every experiment now. No results will be available to you.",
    CONCLUDE_TOOL: "End the investigation with your assessment and any claimed findings.",
}
# Names a diagnostic may repeat. Anything else in a validation error came from the model.
_KNOWN_FIELDS = frozenset(
    {
        "assessments",
        "hypothesis",
        "experiment",
        "experiments",
        "conclusion",
        "claimed_findings",
        "hypothesis_id",
        "behavior",
        "suspected_mechanism",
        "motivating_observations",
        "motivation",
        "predicted_observation",
        "failure_discriminator",
        "revises",
        "label",
        "rationale",
        "motivated_by",
        "python_code",
        "status",
        "cited_observations",
        "reasoning",
        "experiment_id",
        "finding_code",
        "statement",
    }
)

Decision = ProposeExperiment | ProposePlan | ConcludeInvestigation


def tool_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=_DESCRIPTIONS[name],
        parameters=_ARGUMENTS[name].model_json_schema(),
    )


def invalid(problem: str, fields: list[str] | None = None) -> GenerationDiagnostic:
    hint = HINTS.get(problem, HINTS["invalid_decision"])
    return GenerationDiagnostic(problem=problem, invalid_fields=(fields or [])[:12], hint=hint)


def parse_decision(result: InferenceResult, offered: list[str]) -> Decision | GenerationDiagnostic:
    """Exactly one offered tool call with valid arguments, or a diagnostic. Never repaired."""
    if result.finish_reason == "length":
        return invalid("truncated_response")
    if len(result.tool_calls) != 1:
        return invalid("invalid_decision")
    call = result.tool_calls[0]
    if call.name not in offered:
        return invalid("invalid_decision")
    try:
        parsed = _ARGUMENTS[call.name].model_validate_json(call.arguments_json)
    except ValidationError as exc:
        names = {str(p) for e in exc.errors() for p in e["loc"]}
        return invalid("invalid_decision", sorted(names & _KNOWN_FIELDS))
    if isinstance(parsed, ProposeExperiment | ProposePlan | ConcludeInvestigation):
        return parsed
    raise AssertionError("unreachable: every tool maps to a decision model")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class ModelCall:
    record: ModelCallRecord
    result: InferenceResult | None  # None after a provider error


class InvestigatorModel:
    def __init__(
        self,
        *,
        inference: InferencePort,
        evidence: EvidenceSource,
        model: str,
        provider: str | None,
        spend: SpendPort | None,
        max_completion_tokens: int,
        temperature: float,
        provider_attempts: int = 1,
    ) -> None:
        if evidence == "live_provider" and spend is None:
            raise ValueError("a live Investigator requires a spend ledger")
        self._inference = inference
        self.evidence: EvidenceSource = evidence
        self.model = model
        self._provider = provider
        self._spend = spend
        self._max_completion = max_completion_tokens
        self._temperature = temperature
        self._attempts = provider_attempts

    def worst_case_tokens(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> int:
        """Two characters per token is well below any tokenizer's average for this text."""
        chars = sum(len(m.content) for m in messages)
        chars += sum(len(t.model_dump_json()) for t in tools)
        return self._attempts * (math.ceil(chars / 2) + self._max_completion)

    def call(
        self,
        *,
        seq: int,
        purpose: str,
        messages: list[ChatMessage],
        offered: list[str],
        artifact_dir: Path,
    ) -> ModelCall:
        """Raises ``BudgetExceededError`` before anything is sent if the call cannot be funded."""
        tools = [tool_spec(name) for name in offered]
        entry = (
            self._spend.reserve(
                f"investigator:{purpose}",
                worst_case_tokens=self.worst_case_tokens(messages, tools),
            )
            if self._spend is not None
            else None
        )
        conversation: list[ConversationMessage] = list(messages)
        request = InferenceRequest(
            messages=conversation,
            model=self.model,
            tools=tools,
            tool_choice="required",
            max_tokens=self._max_completion,
            temperature=self._temperature,
        )
        prompt_text = request.model_dump_json()
        name = f"call-{seq:02d}.json"
        path = artifact_dir / name
        artifact: dict[str, Any] = {"seq": seq, "purpose": purpose, "request": prompt_text}
        try:
            result = self._inference.complete(request)
        except MoodyBluesError as exc:
            cost = self._spend.settle(entry, None) if self._spend and entry else None
            artifact["error_category"] = exc.detail.category.value
            atomic_write(path, _dump(artifact))
            return ModelCall(
                self._record(seq, purpose, prompt_text, name, entry, cost, None, None), None
            )
        tokens = _totals(result)
        cost = self._spend.settle(entry, tokens) if self._spend and entry else None
        response_text = result.model_dump_json()
        artifact["response"] = response_text
        atomic_write(path, _dump(artifact))
        return ModelCall(
            self._record(seq, purpose, prompt_text, name, entry, cost, result, response_text),
            result,
        )

    def _record(
        self,
        seq: int,
        purpose: str,
        prompt_text: str,
        name: str,
        entry: str | None,
        cost: float | None,
        result: InferenceResult | None,
        response_text: str | None,
    ) -> ModelCallRecord:
        usage = result.usage if result is not None else None
        return ModelCallRecord(
            seq=seq,
            purpose=purpose,
            evidence_source=self.evidence,
            provider=self._provider,
            requested_model=self.model,
            reported_model=result.reported_model if result is not None else None,
            response_id=result.response_id if result is not None else None,
            finish_reason=result.finish_reason if result is not None else None,
            outcome="ok" if result is not None else "provider_error",
            prompt_sha256=sha256_text(prompt_text),
            response_sha256=sha256_text(response_text) if response_text is not None else None,
            artifact_path=f"calls/{name}",
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
            latency_ms=result.latency_ms if result is not None else 0,
            estimated_cost_usd=round(cost, 6) if cost is not None else None,
            spend_entry=entry,
        )


def _totals(result: InferenceResult) -> TokenTotals | None:
    """``None`` keeps the whole reservation: unknown usage is never booked as cheap."""
    usage = result.usage
    if usage is None or usage.prompt_tokens is None or usage.completion_tokens is None:
        return None
    return TokenTotals(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens or usage.prompt_tokens + usage.completion_tokens,
    )


def _dump(artifact: dict[str, Any]) -> str:
    return json.dumps(artifact, indent=1) + "\n"
