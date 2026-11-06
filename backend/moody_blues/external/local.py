"""Opening local inference: what it may do, and what it is, before anything uses it.

This is the only place a local model is opened. Nothing here touches the Vultr client, key or spend
ledger: a local run reserves nothing and pays nothing. The limits below are what bounds it instead.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from moody_blues.config import Settings
from moody_blues.contracts.adapter import AdapterLimits
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import (
    ChatMessage,
    InferenceRequest,
    LocalInferencePolicy,
    LocalModelIdentity,
)
from moody_blues.contracts.investigation import InvestigationLimits
from moody_blues.external.driver import InferenceBroker
from moody_blues.inference.ollama import (
    PROVIDER,
    LocalEndpointError,
    OllamaInferenceClient,
)
from moody_blues.inference.vultr import InferenceError
from moody_blues.investigator.model import InvestigatorModel

# An agent's turn. The Investigator gets more, because it writes a whole program in one answer.
AGENT_COMPLETION_TOKENS = 2_048
AGENT_CALL_TIMEOUT_SECONDS = 60.0
INVESTIGATOR_COMPLETION_TOKENS = 4_096

LOCAL_POLICY = LocalInferencePolicy(
    max_model_calls_per_run=8,
    max_total_tokens_per_run=30_000,
    max_completion_tokens=INVESTIGATOR_COMPLETION_TOKENS,
    max_prompt_bytes=32_000,
    call_timeout_seconds=180.0,
    run_timeout_seconds=95.0,
    max_concurrent_generations=1,
    # Sets the memory the model holds, and a change reloads it, so one value serves both roles.
    context_tokens=12_288,
    max_experiments=2,
    max_investigator_calls=4,
    max_investigation_seconds=600.0,
)
# Startup + this + exit grace stay inside the sandbox's 120 s ceiling, as for a hosted model.
LOCAL_ADAPTER_LIMITS = AdapterLimits(run_timeout_seconds=LOCAL_POLICY.run_timeout_seconds)
LOCAL_INVESTIGATION_LIMITS = InvestigationLimits(
    max_experiments=LOCAL_POLICY.max_experiments,
    max_model_calls=LOCAL_POLICY.max_investigator_calls,
    max_completion_tokens=INVESTIGATOR_COMPLETION_TOKENS,
    reasoning_effort=None,  # thinking is the recorded ``ollama_think`` setting here
    max_prompt_chars=24_000,
    max_reproductions=0,
    max_wall_seconds=LOCAL_POLICY.max_investigation_seconds,
)


@dataclass(frozen=True, slots=True)
class LocalSession:
    """A checked local model. One client, so the concurrency limit holds across every role."""

    client: OllamaInferenceClient
    identity: LocalModelIdentity

    def broker(self) -> InferenceBroker:
        policy = self.identity.policy
        return InferenceBroker(
            inference=self.client,
            evidence="local_ollama",
            provider=PROVIDER,
            model=self.identity.model,
            max_model_calls=policy.max_model_calls_per_run,
            max_total_tokens=policy.max_total_tokens_per_run,
            max_completion_tokens=AGENT_COMPLETION_TOKENS,
            max_prompt_bytes=policy.max_prompt_bytes,
            call_timeout_seconds=AGENT_CALL_TIMEOUT_SECONDS,
            abort=self.client.abort,
            identity=self.identity,
        )

    def investigator(self, limits: InvestigationLimits) -> InvestigatorModel:
        return InvestigatorModel(
            inference=self.client,
            evidence="local_ollama",
            model=self.identity.model,
            provider=PROVIDER,
            spend=None,
            max_completion_tokens=limits.max_completion_tokens,
            temperature=limits.temperature,
            provider_attempts=1,
            reasoning_effort=limits.reasoning_effort,
        )


def _report(status: str, reason: str) -> None:
    print(json.dumps({"status": status, "reason": reason}, indent=2))


def open_local(settings: Settings) -> LocalSession | None:
    """Everything a local call needs. Without all of it nothing is opened, and it says why."""
    try:
        client = OllamaInferenceClient.from_settings(settings, LOCAL_POLICY)
        return LocalSession(client=client, identity=client.describe())
    except LocalEndpointError as exc:
        _report("FAIL", str(exc))
    except InferenceError as exc:
        unavailable = exc.detail.category in {
            ErrorCategory.PROVIDER_CONNECTION,
            ErrorCategory.PROVIDER_TIMEOUT,
        }
        _report("BLOCKED_BY_LOCAL_DEPENDENCY" if unavailable else "FAIL", exc.detail.message)
    return None


def preflight(settings: Settings, *, smoke: bool) -> int:
    """What is installed and whether the selected model can be used. ``smoke`` generates once."""
    session = open_local(settings)
    if session is None:
        return 2
    report: dict[str, object] = {
        "status": "PASS",
        "endpoint": session.client.base_url,
        "installed": sorted(session.client.installed_models()),
        "allowlist": list(settings.local_model_allowlist),
        "identity": session.identity.model_dump(mode="json"),
    }
    if smoke:
        started = time.perf_counter()
        result = session.client.complete(
            InferenceRequest(
                messages=[ChatMessage(role="user", content="Reply with the single word: ready")],
                max_tokens=256,
            )
        )
        tokens = result.usage.completion_tokens if result.usage else None
        generation = result.timings.generation_ms if result.timings else 0
        report["smoke"] = {
            "wall_ms": int((time.perf_counter() - started) * 1000),
            "reported_model": result.reported_model,
            "finish_reason": result.finish_reason,
            "completion_tokens": tokens,
            "load_ms": result.timings.load_ms if result.timings else None,
            "tokens_per_second": round(tokens / generation * 1000, 1)
            if tokens and generation
            else None,
        }
    print(json.dumps(report, indent=2))
    return 0
