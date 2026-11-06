"""Local inference through the existing broker, target and evidence, with a labeled double.

The agent, the process boundary, the gateway, the world and the Oracle are real. Only the words
come from ``LocalDouble``, a TEST DOUBLE speaking Ollama's wire format. Nothing here says anything
about a model. The real runs are ``make local-eval``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from threading import Event, Timer
from typing import Any

import httpx2
import pytest

from moody_blues.contracts.agent import MODEL_EVIDENCE, TerminationReason
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.inference import InferenceResult, LocalModelIdentity
from moody_blues.contracts.investigation import (
    FindingClass,
    ReproductionStatus,
    TargetKind,
    VerifiedFinding,
)
from moody_blues.contracts.oracle import Verdict
from moody_blues.external import commands, local
from moody_blues.external.bundle import build_bundle
from moody_blues.external.selection import external_provenance
from moody_blues.external.target import LOCAL_COST_NOTE, LiveInference
from moody_blues.inference.ollama import OllamaInferenceClient
from moody_blues.investigator.findings import statement
from moody_blues.investigator.model import InvestigatorModel
from tests.conftest import make_settings
from tests.external.conftest import EXAMPLES, fixture_manifest, run_agent

LLM = EXAMPLES / "llm.agent.toml"
MODEL = local.LOCAL_POLICY and "fixture-local:1b"
Handler = Callable[[httpx2.Request], httpx2.Response]


def _identity() -> LocalModelIdentity:
    return LocalModelIdentity(
        server_version="0.0.1-double",
        model=MODEL,
        digest="d" * 64,
        family="fx",
        parameter_size="1B",
        quantization="Q4",
        capabilities=["completion", "tools"],
        context_limit=32_768,
        thinking_enabled=False,
        host_os="test",
        host_arch="test",
        policy=local.LOCAL_POLICY,
    )


def _frames(*items: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(i).encode() + b"\n" for i in items)


def _final(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": MODEL,
        "message": message,
        "done": True,
        "done_reason": "stop",
        "total_duration": 3_000_000,
        "load_duration": 0,
        "prompt_eval_count": 10,
        "prompt_eval_duration": 1_000_000,
        "eval_count": 5,
        "eval_duration": 2_000_000,
    }


class LocalDouble:
    """TEST DOUBLE. Creates the customer it is told to, then reports. Not a model."""

    def __init__(self) -> None:
        self.calls = 0
        self.paths: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        self.paths.append(request.url.path)
        sent = json.loads(request.content)
        if sent["messages"][-1]["role"] == "tool":
            body = {"status": "completed", "customer_id": None, "message": "double"}
            message = {"role": "assistant", "content": json.dumps(body)}
            return httpx2.Response(200, content=_frames(_final(message)))
        arguments = {"name": "Ada Lovelace", "email": "ada@analytical.example"}
        arguments["metadata"] = {"source": "referral", "tier": "platinum"}  # pyright: ignore[reportArgumentType]
        call = {"id": "c1", "function": {"name": "create_customer", "arguments": arguments}}
        return httpx2.Response(
            200,
            content=_frames(
                {"model": MODEL, "message": {"role": "assistant", "tool_calls": [call]}},
                _final({"role": "assistant", "content": ""}),
            ),
        )


def _session(handler: Handler) -> local.LocalSession:
    return local.LocalSession(
        client=OllamaInferenceClient(
            base_url="http://127.0.0.1:11434",
            model=MODEL,
            allowlist=(MODEL,),
            policy=local.LOCAL_POLICY,
            think=False,
            transport=httpx2.MockTransport(handler),
        ),
        identity=_identity(),
    )


def _lent(session: local.LocalSession, **broker: Any) -> LiveInference:
    from dataclasses import replace

    return LiveInference(broker=replace(session.broker(), **broker), ledger=None)


def test_a_local_run_is_labeled_as_local_and_needs_no_ledger(tmp_path: Path) -> None:
    double = LocalDouble()
    result = run_agent(tmp_path, build_bundle(LLM), live=_lent(_session(double)))
    assert result.evidence_source == "local_ollama"
    assert result.provider == "ollama"
    assert result.requested_model == MODEL
    assert result.reported_models == [MODEL]
    assert result.estimated_cost_usd is None
    assert result.cost_note == LOCAL_COST_NOTE
    assert result.external is not None
    assert result.external.model_calls >= 1
    assert result.external.model_identity is not None
    assert result.external.model_identity.digest == "d" * 64
    assert all(r.timings is not None for r in result.external.model_requests)
    assert set(double.paths) == {"/api/chat"}


def test_the_oracle_reads_state_and_not_the_local_models_claim(tmp_path: Path) -> None:
    """The same words, "completed", against two worlds: the state decides, never the claim."""
    bundle = build_bundle(LLM)
    honest = run_agent(tmp_path, bundle, live=_lent(_session(LocalDouble())))
    false = run_agent(
        tmp_path, bundle, scenario="phantom-success", live=_lent(_session(LocalDouble()))
    )
    assert honest.claim is not None
    assert false.claim is not None
    assert honest.claim.status == false.claim.status
    assert honest.oracle.verdict is Verdict.PASS
    assert false.oracle.verdict is Verdict.VIOLATION


def test_a_provider_failure_ends_the_run_as_a_provider_failure(tmp_path: Path) -> None:
    session = _session(lambda _: httpx2.Response(500, json={"error": "runner died"}))
    result = run_agent(tmp_path, build_bundle(LLM), live=_lent(session))
    assert result.termination == TerminationReason.PROVIDER_ERROR.value
    assert result.evidence_source == "local_ollama"  # a provider was asked
    assert result.error is not None
    assert result.error.category is ErrorCategory.PROVIDER_SERVER_ERROR


def test_a_refused_model_call_budget_stops_at_the_host(tmp_path: Path) -> None:
    double = LocalDouble()
    live = _lent(_session(double), max_model_calls=1)
    run_agent(tmp_path, build_bundle(LLM), live=live)
    assert double.calls == 1


def test_an_oversized_prompt_stops_at_the_broker(tmp_path: Path) -> None:
    double = LocalDouble()
    result = run_agent(
        tmp_path, build_bundle(LLM), live=_lent(_session(double), max_prompt_bytes=8)
    )
    assert double.calls == 0
    assert result.external is not None
    assert [r.code for r in result.external.model_requests] == ["prompt_too_large"]


def test_cancelling_aborts_the_generation_in_progress(tmp_path: Path) -> None:
    class Endless(httpx2.SyncByteStream):
        def __init__(self) -> None:
            self.closed = Event()

        def __iter__(self) -> Any:
            for _ in range(100_000):
                if self.closed.wait(0.01):
                    return
                yield _frames({"model": MODEL, "message": {"content": "x"}})

        def close(self) -> None:
            self.closed.set()

    stream = Endless()
    session = _session(lambda _: httpx2.Response(200, stream=stream))
    cancel = Event()
    Timer(0.5, cancel.set).start()
    result = run_agent(tmp_path, build_bundle(LLM), live=_lent(session), cancel=cancel)
    assert result.termination == TerminationReason.CANCELLED.value
    assert stream.closed.wait(5)


def test_provenance_records_the_local_identity(tmp_path: Path) -> None:
    broker = _session(LocalDouble()).broker()
    provenance = external_provenance(TargetKind.EXTERNAL_LLM, build_bundle(LLM), broker)
    assert provenance.model_broker == "local_ollama"
    assert provenance.approved_model == MODEL
    assert provenance.model_identity == _identity()


def test_a_script_is_never_lent_a_local_model(tmp_path: Path) -> None:
    from moody_blues.external.selection import TargetSelectionError

    bundle = build_bundle(fixture_manifest(tmp_path, "Succeeds"))
    with pytest.raises(TargetSelectionError):
        external_provenance(TargetKind.EXTERNAL_SCRIPTED, bundle, _session(LocalDouble()).broker())


def test_a_local_investigator_needs_no_ledger_and_says_what_it_is() -> None:
    model = _session(LocalDouble()).investigator(local.LOCAL_INVESTIGATION_LIMITS)
    assert isinstance(model, InvestigatorModel)
    assert model.evidence == "local_ollama"


def test_local_evidence_is_model_behavior_and_fixtures_are_not() -> None:
    assert "local_ollama" in MODEL_EVIDENCE
    assert "live_provider" in MODEL_EVIDENCE
    assert "offline_fixture" not in MODEL_EVIDENCE
    assert "external_scripted" not in MODEL_EVIDENCE


def _finding(source: str) -> VerifiedFinding:
    return VerifiedFinding.model_validate(
        {
            "experiment_id": "exp_1",
            "proposal_id": "p",
            "run_id": "r",
            "run_ref": "trun_1",
            "world_ref": "w",
            "config": "baseline",
            "selected_faults": [],
            "finding_class": FindingClass.ORACLE_CONFIRMED_VIOLATION,
            "oracle_verdict": Verdict.VIOLATION,
            "run_outcome": "violation",
            "termination": "final_claim",
            "violation_codes": ["x"],
            "faults_delivered": 1,
            "target_evidence_source": source,
            "reproduction": ReproductionStatus.NOT_APPLICABLE,
        }
    )


def test_a_statement_never_calls_a_local_target_a_live_one() -> None:
    assert "local model target" in statement([_finding("local_ollama")])
    assert "live model target" in statement([_finding("live_provider")])


def test_results_without_timings_serialize_as_they_always_did() -> None:
    result = InferenceResult(
        provider="vultr",
        requested_model="m",
        reported_model="m",
        response_id="r",
        content="c",
        finish_reason="stop",
        usage=None,
        latency_ms=1,
    )
    assert "timings" not in result.model_dump_json()


def test_the_local_limits_fit_inside_the_sandbox_ceiling() -> None:
    limits = local.LOCAL_ADAPTER_LIMITS
    assert (
        limits.startup_timeout_seconds + limits.run_timeout_seconds + limits.exit_grace_seconds
        <= 120
    )
    assert local.LOCAL_POLICY.max_concurrent_generations == 1


# --- commands: all refusals, none reach a server, a key or a ledger -------------------------


def _report(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    out = capsys.readouterr().out
    return json.loads(out[out.index("{") :])


def test_local_and_paid_never_mix(capsys: pytest.CaptureFixture[str]) -> None:
    code = commands.run(
        make_settings(),
        LLM,
        world="normal-success",
        live_inference=True,
        confirm_billable=True,
        approved_spend_usd=1.0,
        local_inference=True,
    )
    assert code == 1
    assert _report(capsys)["status"] == "FAIL"
    code = commands.investigate(
        make_settings(),
        kind=TargetKind.EXTERNAL_LLM,
        manifest=LLM,
        world="normal-success",
        live=commands.LiveRequest(target=True, local_investigator=True),
    )
    assert code == 1


@pytest.mark.parametrize("world", ["w-r1", "w-e1", "w-v1"])
def test_reserved_worlds_are_refused_for_local_runs_too(
    world: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = commands.run(
        make_settings(), LLM, world=world, live_inference=False, confirm_billable=False,
        local_inference=True,
    )  # fmt: skip
    assert code == 1


def test_a_stopped_server_blocks_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    settings = make_settings(ollama_base_url="http://127.0.0.1:9")
    assert local.open_local(settings) is None
    assert _report(capsys)["status"] == "BLOCKED_BY_LOCAL_DEPENDENCY"


def test_a_remote_endpoint_is_refused_before_contact(capsys: pytest.CaptureFixture[str]) -> None:
    settings = make_settings(ollama_base_url="https://api.vultrinference.com/v1")
    assert local.open_local(settings) is None
    assert _report(capsys)["status"] == "FAIL"


def test_a_model_off_the_allowlist_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    settings = make_settings(ollama_model="llama3.1:405b")
    assert local.open_local(settings) is None
    report = _report(capsys)
    assert report["status"] == "FAIL"
    assert "allowlist" in report["reason"]


def test_opening_local_inference_touches_no_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(ollama_base_url="http://127.0.0.1:9", artifacts_dir=tmp_path)
    local.open_local(settings)
    assert list(tmp_path.iterdir()) == []
