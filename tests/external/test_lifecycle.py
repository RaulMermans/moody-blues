"""Starting, stopping and failing. Scenarios 1, 2, 9, 10, 11 and 13 of the evaluation plan."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event, Timer

import pytest

from moody_blues.contracts.adapter import (
    AdapterEventKind,
    AdapterLimits,
    AdapterRejectionCode,
    ExternalAgentRecord,
)
from moody_blues.contracts.agent import AgentConfigName, TerminationReason
from moody_blues.contracts.common import ErrorCategory
from moody_blues.contracts.oracle import FindingCode, Verdict
from moody_blues.contracts.sandbox import SandboxRequest
from moody_blues.experiments.target import TargetRequest, TargetResult
from moody_blues.external.bundle import build_bundle
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.sandbox.base import SandboxError
from moody_blues.sandbox.session import SandboxSession
from moody_blues.world.scenarios import load_scenario
from tests.external.conftest import FAST, LIMITS, LocalProcessRunner, fixture_manifest

Run = Callable[..., TargetResult]
T = TerminationReason


def _record(result: TargetResult) -> ExternalAgentRecord:
    assert result.external is not None
    return result.external


def _kinds(result: TargetResult) -> list[AdapterEventKind]:
    return [e.kind for e in _record(result).events]


# 1. Handshake ---------------------------------------------------------------------------------


def test_valid_handshake(fixture_run: Run) -> None:
    result = fixture_run("Succeeds")
    record = _record(result)
    assert AdapterEventKind.HANDSHAKE_ACCEPTED in _kinds(result)
    assert record.startup_ms is not None
    assert record.sdk_version == "0.1.0"
    assert result.termination == T.FINAL_CLAIM.value


def test_events_are_numbered_and_in_order(fixture_run: Run) -> None:
    events = _record(fixture_run("Succeeds")).events
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert events[0].kind is AdapterEventKind.REGISTERED
    assert events[-1].kind is AdapterEventKind.ORACLE_VERIFIED


# 2. Refused at the door -----------------------------------------------------------------------


def test_unsupported_protocol_is_refused_with_what_is_supported(fixture_run: Run) -> None:
    result = fixture_run("FutureProtocol")
    record = _record(result)
    assert result.termination == T.PROTOCOL_VERSION_MISMATCH.value
    assert record.rejection is not None
    assert record.rejection.code is AdapterRejectionCode.UNSUPPORTED_PROTOCOL
    assert AdapterEventKind.HANDSHAKE_REJECTED in _kinds(result)
    assert result.world_trace == []


@pytest.mark.parametrize(
    ("entry", "code"),
    [
        ("WrongIdentity", AdapterRejectionCode.IDENTITY_MISMATCH),
        ("ClaimsLlm", AdapterRejectionCode.IDENTITY_MISMATCH),
        ("ClaimsModelCapability", AdapterRejectionCode.CAPABILITY_REFUSED),
        ("FirstMessageIsATool", AdapterRejectionCode.OUT_OF_ORDER),
    ],
)
def test_a_hello_must_agree_with_the_manifest(
    fixture_run: Run, entry: str, code: AdapterRejectionCode
) -> None:
    result = fixture_run(entry)
    record = _record(result)
    assert result.termination == T.HANDSHAKE_REJECTED.value
    assert record.rejection is not None
    assert record.rejection.code is code
    assert result.world_trace == []


# Startup -------------------------------------------------------------------------------------


def test_startup_failure_keeps_the_agents_stderr_as_untrusted_text(fixture_run: Run) -> None:
    result = fixture_run("CrashesAtImport")
    record = _record(result)
    assert result.termination == T.ADAPTER_STARTUP_FAILED.value
    assert result.oracle.verdict is Verdict.INCONCLUSIVE
    assert record.exit is not None
    assert "cannot start" in record.exit.untrusted_stderr_excerpt
    assert len(record.exit.stderr_sha256) == 64


def test_an_agent_that_never_greets_is_stopped_at_the_startup_deadline(fixture_run: Run) -> None:
    result = fixture_run(
        "NeverGreets", limits=FAST.model_copy(update={"startup_timeout_seconds": 1})
    )
    assert result.termination == T.ADAPTER_STARTUP_FAILED.value
    assert _record(result).exit.killed_by_host  # pyright: ignore[reportOptionalMemberAccess]


class _NoDocker:
    approved_for_generated_code = True

    def open_session(self, request: SandboxRequest, *, max_line_bytes: int) -> SandboxSession:
        raise SandboxError(ErrorCategory.SANDBOX_RUNTIME, "the daemon went away")

    def ping(self) -> None:
        return None


def test_a_sandbox_that_cannot_start_is_recorded_not_raised(tmp_path: Path) -> None:
    target = ExternalAgentTarget(
        runner=_NoDocker(),
        bundle=build_bundle(fixture_manifest(tmp_path, "Succeeds")),
        sandbox_limits=LIMITS,
    )
    result = target.run(
        TargetRequest(
            scenario=load_scenario("normal-success"),
            config=AgentConfigName.BASELINE,
            world_root=tmp_path,
            max_wall_seconds=5,
            cancel=None,
        )
    )
    assert result.termination == T.ADAPTER_STARTUP_FAILED.value
    assert result.error is not None
    assert _record(result).environment is None


# 9. Timeout ----------------------------------------------------------------------------------


def test_a_hung_agent_is_killed_at_the_deadline(fixture_run: Run) -> None:
    limits = FAST.model_copy(update={"run_timeout_seconds": 1})
    result = fixture_run("Hangs", limits=limits)
    assert result.termination == T.WALL_TIMEOUT.value
    assert _record(result).exit.killed_by_host  # pyright: ignore[reportOptionalMemberAccess]
    assert result.oracle.verdict is Verdict.INCONCLUSIVE
    assert result.claim is None


def test_the_experiments_remaining_time_caps_the_run(tmp_path: Path) -> None:
    target = ExternalAgentTarget(
        runner=LocalProcessRunner(tmp_path / "p"),
        bundle=build_bundle(fixture_manifest(tmp_path, "Hangs")),
        sandbox_limits=LIMITS,
        limits=AdapterLimits(run_timeout_seconds=60, exit_grace_seconds=0),
    )
    result = target.run(
        TargetRequest(
            scenario=load_scenario("normal-success"),
            config=AgentConfigName.BASELINE,
            world_root=tmp_path,
            max_wall_seconds=1,
            cancel=None,
        )
    )
    assert result.termination == T.WALL_TIMEOUT.value
    assert result.wall_ms < 10_000


# 10. Crash -----------------------------------------------------------------------------------


def test_a_crash_keeps_what_the_agent_really_did(fixture_run: Run) -> None:
    result = fixture_run("CreatesThenCrashes")
    record = _record(result)
    assert result.termination == T.ADAPTER_CRASHED.value
    assert record.exit is not None
    assert record.exit.exit_code == 9
    assert AdapterEventKind.ADAPTER_CRASHED in _kinds(result)
    assert result.claim is None
    # Two real commits, then a crash. The Oracle finds them anyway.
    assert result.oracle.verdict is Verdict.VIOLATION
    assert FindingCode.DUPLICATE_SIDE_EFFECT in {f.code for f in result.oracle.findings}


def test_an_exception_in_the_agent_is_reported_as_a_failure(fixture_run: Run) -> None:
    result = fixture_run("Raises")
    record = _record(result)
    assert result.termination == T.AGENT_REPORTED_FAILURE.value
    assert record.final is not None
    assert record.final.error_class == "agent_error"
    assert result.claim is None
    assert record.exit is not None
    assert "a bug in the agent" in record.exit.untrusted_stderr_excerpt


def test_a_clean_exit_with_no_report_is_a_missing_claim(fixture_run: Run) -> None:
    result = fixture_run("ExitsCleanly")
    assert result.termination == T.NO_FINAL_CLAIM.value
    assert result.run_outcome != "success"


# 11. Cancellation ----------------------------------------------------------------------------


def _cancelling(seconds: float) -> tuple[Event, Timer]:
    cancel = Event()
    timer = Timer(seconds, cancel.set)
    timer.start()
    return cancel, timer


def test_cancellation_stops_a_cooperative_agent_without_killing_it(fixture_run: Run) -> None:
    cancel, timer = _cancelling(0.6)
    result = fixture_run("ObeysCancel", cancel=cancel)
    timer.cancel()
    record = _record(result)
    assert result.termination == T.CANCELLED.value
    assert record.final is not None
    assert record.final.completion == "cancelled"
    assert record.exit is not None
    assert not record.exit.killed_by_host
    assert AdapterEventKind.EXECUTION_CANCELLED in _kinds(result)


def test_cancellation_kills_an_agent_that_ignores_it(fixture_run: Run) -> None:
    cancel, timer = _cancelling(0.6)
    result = fixture_run("IgnoresCancel", cancel=cancel)
    timer.cancel()
    assert result.termination == T.CANCELLED.value
    assert _record(result).exit.killed_by_host  # pyright: ignore[reportOptionalMemberAccess]


# 13. Malformed output ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "code"),
    [
        ("MalformedFinal", AdapterRejectionCode.SCHEMA_VIOLATION),
        ("NotJson", AdapterRejectionCode.MALFORMED_JSON),
        ("DuplicateKeys", AdapterRejectionCode.MALFORMED_JSON),
        ("Oversized", AdapterRejectionCode.OVERSIZED),
        ("SecondHello", AdapterRejectionCode.OUT_OF_ORDER),
    ],
)
def test_malformed_output_ends_the_run_and_is_not_read_as_a_claim(
    fixture_run: Run, entry: str, code: AdapterRejectionCode
) -> None:
    result = fixture_run(entry)
    record = _record(result)
    assert result.termination == T.MALFORMED_MESSAGE.value
    assert record.rejection is not None
    assert record.rejection.code is code
    assert result.claim is None
    assert record.final is None
    assert result.oracle.verdict is Verdict.INCONCLUSIVE


def test_a_rejected_line_is_recorded_by_hash_only(fixture_run: Run) -> None:
    record = _record(fixture_run("NotJson"))
    assert record.rejected_line_sha256 is not None
    assert "this is not json" not in record.model_dump_json()


def test_print_cannot_reach_the_protocol_stream(fixture_run: Run) -> None:
    result = fixture_run("PrintsALot")
    record = _record(result)
    assert result.termination == T.FINAL_CLAIM.value
    assert record.exit is not None
    assert "hello from the agent" in record.exit.untrusted_stderr_excerpt
    assert result.oracle.verdict is Verdict.PASS
