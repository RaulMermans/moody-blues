"""The host's model broker, attacked from the agent's side and failed from the provider's.

Every model here is a labeled test double. What these show is that the limits hold, that nothing
is paid for twice, and that the record says what the host did. They say nothing about any real model.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from moody_blues.contracts.adapter import AdapterEventKind, ExternalAgentRecord, ModelCallStatus
from moody_blues.contracts.agent import TerminationReason
from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.inference import InferenceRequest, InferenceResult, TokenUsage, ToolCall
from moody_blues.contracts.oracle import Verdict
from moody_blues.experiments.recovery import unresolved_model_calls
from moody_blues.experiments.target import TargetResult
from moody_blues.external import commands
from moody_blues.external.bundle import build_bundle
from moody_blues.external.driver import InferenceBroker
from moody_blues.external.target import LiveInference
from tests.external.conftest import fixture_manifest, run_agent

MODEL_AGENT = {"capabilities": ("tools", "cancellation", "model"), "target_type": "llm"}


def _result(content: str | None = "fine", calls: list[ToolCall] | None = None) -> InferenceResult:
    return InferenceResult(
        provider="fixture",
        requested_model="approved-model",
        reported_model="approved-model",
        response_id="r",
        content=content,
        tool_calls=calls or [],
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        latency_ms=1,
    )


Reply = InferenceResult | Exception | Callable[[], InferenceResult]


class Provider:
    """TEST DOUBLE. Counts what actually reached it, which is the number that costs money."""

    def __init__(self, *replies: Reply) -> None:
        self._replies = list(replies)
        self.requests: list[InferenceRequest] = []

    def complete(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, InferenceResult) else reply()


def _live(
    provider: Provider, *, calls: int = 4, timeout: float = 5.0, tokens: int = 50_000
) -> LiveInference:
    return LiveInference(
        broker=InferenceBroker(
            inference=provider,
            evidence="offline_fixture",
            provider="fixture",
            model="approved-model",
            max_model_calls=calls,
            max_total_tokens=tokens,
            max_completion_tokens=64,
            call_timeout_seconds=timeout,
        ),
        ledger=None,
    )


def _run(tmp_path: Path, entry: str, live: LiveInference | None, **options: Any) -> TargetResult:
    bundle = build_bundle(fixture_manifest(tmp_path, entry, **MODEL_AGENT))
    return run_agent(tmp_path, bundle, live=live, **options)


def _record(result: TargetResult) -> ExternalAgentRecord:
    assert result.external is not None
    return result.external


def _error(category: ErrorCategory) -> MoodyBluesError:
    return MoodyBluesError(category, "provider said no")


def _kinds(record: ExternalAgentRecord) -> list[AdapterEventKind]:
    return [e.kind for e in record.events]


# --- what an agent can ask for ------------------------------------------------------------------


def test_a_reused_model_call_id_is_refused_and_not_paid_for_twice(tmp_path: Path) -> None:
    provider = Provider(_result())
    result = _run(tmp_path, "ReusesModelCallId", _live(provider))
    assert len(provider.requests) == 1
    states = [(r.status, r.code) for r in _record(result).model_requests]
    assert states == [
        (ModelCallStatus.COMPLETED, None),
        (ModelCallStatus.REJECTED, "duplicate_call_id"),
    ]


@pytest.mark.parametrize("entry", ["ChoosesItsOwnModel", "ChoosesItsOwnEndpoint"])
def test_an_agent_cannot_name_a_model_or_an_endpoint(tmp_path: Path, entry: str) -> None:
    provider = Provider(_result())
    result = _run(tmp_path, entry, _live(provider))
    assert provider.requests == []
    record = _record(result)
    assert record.rejection is not None
    assert record.rejection.code.value == "schema_violation"
    assert result.termination == TerminationReason.MALFORMED_MESSAGE.value
    assert result.evidence_source == "external_scripted"


def test_a_model_hidden_in_the_conversation_never_reaches_a_provider(tmp_path: Path) -> None:
    provider = Provider(_result())
    result = _run(tmp_path, "HidesModelInTheMessages", _live(provider))
    assert provider.requests == []
    assert _record(result).model_requests[0].code == "invalid_messages"


def test_the_host_sets_the_model_and_the_limits(tmp_path: Path) -> None:
    provider = Provider(_result())
    _run(tmp_path, "GivesUpOnModelFailure", _live(provider))
    sent = provider.requests[0]
    assert (sent.model, sent.max_tokens, sent.temperature) == ("approved-model", 64, 0.0)


def test_an_oversized_prompt_is_refused_before_the_provider(tmp_path: Path) -> None:
    provider = Provider(_result())
    result = _run(tmp_path, "HugePrompt", _live(provider))
    assert provider.requests == []
    request = _record(result).model_requests[0]
    assert (request.status, request.code) == (ModelCallStatus.REJECTED, "prompt_too_large")
    assert request.prompt_bytes > 48_000


def test_a_forged_model_reply_from_the_agent_ends_the_run(tmp_path: Path) -> None:
    result = _run(tmp_path, "ForgesModelReply", _live(Provider(_result())))
    assert result.termination == TerminationReason.MALFORMED_MESSAGE.value
    assert _record(result).model_requests == []
    assert result.evidence_source == "external_scripted"  # it said it used a model; none was seen


# --- budgets ------------------------------------------------------------------------------------


def test_failed_calls_count_against_the_model_budget(tmp_path: Path) -> None:
    """They may be billed. Counting only successes left the loop unbounded."""
    provider = Provider(_error(ErrorCategory.PROVIDER_TIMEOUT))
    result = _run(tmp_path, "ModelLoop", _live(provider, calls=2))
    assert len(provider.requests) == 2
    assert _record(result).final is not None
    codes = str(_record(result).final.message).split(",")  # pyright: ignore[reportOptionalMemberAccess]
    assert codes[:3] == ["provider_error", "provider_error", "model_call_budget_exhausted"]


def test_a_call_that_could_pass_the_token_budget_is_refused_first(tmp_path: Path) -> None:
    provider = Provider(_result())
    result = _run(tmp_path, "GivesUpOnModelFailure", _live(provider, tokens=40))
    assert provider.requests == []
    assert _record(result).model_requests[0].code == "token_budget_exhausted"
    assert result.termination == TerminationReason.TOKEN_BUDGET.value


# --- a provider that misbehaves -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (ErrorCategory.PROVIDER_TIMEOUT, ModelCallStatus.UNCERTAIN),
        (ErrorCategory.PROVIDER_CONNECTION, ModelCallStatus.UNCERTAIN),
        (ErrorCategory.PROVIDER_SERVER_ERROR, ModelCallStatus.UNCERTAIN),
        (ErrorCategory.PROVIDER_AUTH, ModelCallStatus.FAILED),
        (ErrorCategory.PROVIDER_RATE_LIMITED, ModelCallStatus.FAILED),
        (ErrorCategory.PROVIDER_INVALID_RESPONSE, ModelCallStatus.MALFORMED),
    ],
)
def test_provider_failures_are_classified_and_keep_the_reservation(
    tmp_path: Path, failure: ErrorCategory, status: ModelCallStatus
) -> None:
    provider = Provider(_error(failure))
    result = _run(tmp_path, "GivesUpOnModelFailure", _live(provider))
    assert len(provider.requests) == 1
    assert _record(result).model_requests[0].status is status
    assert result.termination == TerminationReason.PROVIDER_ERROR.value
    assert result.tokens is not None
    assert result.tokens.complete is False  # the ledger keeps the whole reservation


def test_only_a_failed_model_call_still_makes_it_a_model_run(tmp_path: Path) -> None:
    """A provider was asked, and may bill for it. Calling this scripted would hide that."""
    provider = Provider(_error(ErrorCategory.PROVIDER_SERVER_ERROR))
    result = _run(tmp_path, "GivesUpOnModelFailure", _live(provider))
    assert result.evidence_source == "offline_fixture"
    assert result.requested_model == "approved-model"
    assert _record(result).model_calls == 1


def test_an_empty_provider_answer_is_not_delivered(tmp_path: Path) -> None:
    result = _run(tmp_path, "GivesUpOnModelFailure", _live(Provider(_result(content=None))))
    request = _record(result).model_requests[0]
    assert (request.status, request.code) == (ModelCallStatus.MALFORMED, "provider_malformed")
    assert request.prompt_tokens == 10  # it answered, so what it reported is kept
    assert AdapterEventKind.MODEL_CALL_FAILED in _kinds(_record(result))


def test_a_provider_answer_that_fails_validation_is_not_delivered(tmp_path: Path) -> None:
    class Shape(BaseModel):
        value: int

    try:
        Shape.model_validate({"value": "no"})
    except ValidationError as exc:
        broken = exc
    result = _run(tmp_path, "GivesUpOnModelFailure", _live(Provider(broken)))
    assert _record(result).model_requests[0].status is ModelCallStatus.MALFORMED
    assert result.termination == TerminationReason.PROVIDER_ERROR.value


def test_a_timed_out_call_is_uncertain_and_never_repeated(tmp_path: Path) -> None:
    def slow() -> InferenceResult:
        time.sleep(0.6)
        return _result(content="too late")

    provider = Provider(slow)
    result = _run(tmp_path, "GivesUpOnModelFailure", _live(provider, timeout=0.2))
    assert len(provider.requests) == 1
    record = _record(result)
    request = record.model_requests[0]
    assert (request.status, request.code) == (ModelCallStatus.UNCERTAIN, "model_call_timeout")
    assert request.response_sha256 is None  # the late answer was never taken
    assert record.final is not None
    assert record.final.message == "model_call_timeout"
    assert result.termination == TerminationReason.PROVIDER_ERROR.value
    assert result.tokens is not None
    assert result.tokens.complete is False


def test_a_model_call_cannot_outlast_the_run_deadline(tmp_path: Path) -> None:
    """Before this, a 120 s client timeout could hold a 60 s run open."""
    from moody_blues.contracts.adapter import AdapterLimits

    def stuck() -> InferenceResult:
        time.sleep(5)
        return _result()

    limits = AdapterLimits(
        startup_timeout_seconds=10,
        run_timeout_seconds=0.5,
        cancel_grace_seconds=0.2,
        exit_grace_seconds=0.2,
    )
    started = time.monotonic()
    result = _run(
        tmp_path, "GivesUpOnModelFailure", _live(Provider(stuck), timeout=30), limits=limits
    )
    assert time.monotonic() - started < 4
    assert result.termination == TerminationReason.WALL_TIMEOUT.value
    assert _record(result).model_requests[0].status is ModelCallStatus.UNCERTAIN


def test_cancel_during_a_model_call_does_not_wait_for_it(tmp_path: Path) -> None:
    release = Event()

    def stuck() -> InferenceResult:
        release.wait(10)
        return _result()

    cancel = Event()
    provider = Provider(stuck)

    def press() -> None:
        while not provider.requests:
            time.sleep(0.01)
        cancel.set()

    Thread(target=press, daemon=True).start()
    started = time.monotonic()
    result = _run(tmp_path, "GivesUpOnModelFailure", _live(provider, timeout=30), cancel=cancel)
    elapsed = time.monotonic() - started
    release.set()
    assert elapsed < 5
    assert result.termination == TerminationReason.CANCELLED.value
    record = _record(result)
    assert record.model_requests[0].status is ModelCallStatus.UNCERTAIN
    assert AdapterEventKind.MODEL_CALL_UNCERTAIN in _kinds(record)
    assert result.tokens is not None
    assert result.tokens.complete is False


def test_a_provider_failure_after_real_effects_still_reaches_the_oracle(tmp_path: Path) -> None:
    provider = Provider(_error(ErrorCategory.PROVIDER_TIMEOUT))
    result = _run(tmp_path, "CreatesThenAsks", _live(provider))
    assert result.termination == TerminationReason.PROVIDER_ERROR.value
    assert len([c for c in result.committed_changes if c.created_by_call]) == 1
    assert result.oracle.verdict is not None


# --- crashes ------------------------------------------------------------------------------------


def test_a_crash_after_a_model_reply_keeps_the_usage_and_repeats_nothing(tmp_path: Path) -> None:
    provider = Provider(_result())
    result = _run(tmp_path, "CrashesAfterModelReply", _live(provider))
    assert len(provider.requests) == 1
    assert result.termination == TerminationReason.ADAPTER_CRASHED.value
    assert result.tokens is not None
    assert result.tokens.total_tokens == 15
    assert _record(result).model_requests[0].status is ModelCallStatus.COMPLETED


def test_a_crash_during_a_model_call_keeps_the_record(tmp_path: Path) -> None:
    provider = Provider(_result())
    result = _run(tmp_path, "CrashesDuringModelCall", _live(provider))
    assert len(provider.requests) <= 1
    assert result.termination == TerminationReason.ADAPTER_CRASHED.value


def test_a_crash_during_a_tool_call_is_not_replayed(tmp_path: Path) -> None:
    bundle = build_bundle(fixture_manifest(tmp_path, "CrashesDuringToolCall"))
    result = run_agent(tmp_path, bundle)
    assert result.termination in {
        TerminationReason.ADAPTER_CRASHED.value,
        TerminationReason.NO_FINAL_CLAIM.value,
    }
    assert len([c for c in result.committed_changes if c.created_by_call]) <= 1
    assert result.oracle.verdict is not None


# --- what recovery can see ----------------------------------------------------------------------


def test_a_model_call_is_written_down_before_it_is_made(tmp_path: Path) -> None:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    seen: list[str] = []

    def peek() -> InferenceResult:
        seen.extend(p.read_text("utf-8") for p in tmp_path.rglob("*.model-calls.jsonl"))
        return _result()

    _run(tmp_path, "GivesUpOnModelFailure", _live(Provider(peek)))
    assert seen
    assert json.loads(seen[0].splitlines()[0])["status"] == "requested"


def test_recovery_counts_calls_with_no_outcome(tmp_path: Path) -> None:
    lines = [
        {"request_id": "run.m1", "status": "requested"},
        {"request_id": "run.m1", "status": "completed"},
        {"request_id": "run.m2", "status": "requested"},
    ]
    text = "\n".join(json.dumps(line) for line in lines)
    (tmp_path / "run.model-calls.jsonl").write_text(text + '\n{"request_id": "ru', "utf-8")
    assert unresolved_model_calls(tmp_path) == 1


# --- the live gate ------------------------------------------------------------------------------


def test_a_live_client_never_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    built: dict[str, Any] = {}

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            built.update(kwargs)

    monkeypatch.setattr(commands, "VultrInferenceClient", Client)
    from tests.conftest import make_settings

    commands._no_retry_client(make_settings(), "k", "m")  # pyright: ignore[reportPrivateUsage]
    assert built["max_retries"] == 0
