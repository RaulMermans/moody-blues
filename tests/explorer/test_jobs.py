"""Operator access, admission, the job lifecycle and restart classification."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from moody_blues.contracts.explorer import (
    ExecutionMode,
    InvestigationBundle,
    JobRecord,
    JobStatus,
    JobView,
)
from moody_blues.contracts.investigation import InvestigationReport
from moody_blues.experiments.budget import PriceCeiling, SpendLedger
from moody_blues.experiments.target import ReferenceTarget, TargetRequest, TargetResult
from moody_blues.experiments.workspace import atomic_write
from moody_blues.explorer.jobs import (
    BUNDLE,
    JobManager,
    JobStore,
    MissionBlockedError,
    WorkflowFactory,
)
from moody_blues.explorer.missions import MISSIONS, Mission, find_mission
from moody_blues.explorer.recorded import render
from moody_blues.investigator.fixtures import conclude, propose
from moody_blues.investigator.workflow import InvestigationWorkflow
from tests.conftest import make_settings
from tests.explorer.conftest import AUTH, RECORDED, TOKEN, VIOLATION, explorer_app, scripted_factory
from tests.investigator.conftest import CODE, PF, PS, experiment

REHEARSAL = "rehearsal-recovery"
LIVE = "live-validation-adaptive"


def job_with_bundle(store: JobStore, recorded: Path) -> str:
    """Files a real bundle as a finished job, relabeled, under a fresh id."""
    bundle = InvestigationBundle.model_validate_json((recorded / f"{VIOLATION}.json").read_text())
    investigation_id = "inv_0123456789ab"
    copy = bundle.model_copy(
        update={
            "summary": bundle.summary.model_copy(
                update={"investigation_id": investigation_id, "mode": ExecutionMode.REHEARSAL}
            )
        }
    )
    now = datetime.now(UTC)
    record = JobRecord(
        job_id="job_0123456789ab",
        mission_id=REHEARSAL,
        mode=ExecutionMode.REHEARSAL,
        status=JobStatus.COMPLETED,
        investigation_id=investigation_id,
        created_at=now,
        updated_at=now,
        evidence_available=True,
    )
    store.create(record)
    digest = atomic_write(store.directory(record.job_id) / BUNDLE, render(copy))
    store.save(record.model_copy(update={"bundle_sha256": digest}))
    return investigation_id


def clean_factory(tmp: Path) -> WorkflowFactory:
    return scripted_factory(
        tmp,
        replies=[propose(1, CODE), conclude()],
        steps=experiment(faults=[PF]),
    )


def operator_client(tmp: Path, **settings: Any) -> TestClient:
    settings.setdefault("operator_token", TOKEN)
    app = explorer_app(tmp, factory=clean_factory(tmp), **settings)
    return TestClient(app, raise_server_exceptions=False)


def wait_for_terminal(c: TestClient, job_id: str, seconds: float = 20) -> JobView:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        view = JobView.model_validate(c.get(f"/operator/jobs/{job_id}", headers=AUTH).json())
        if view.job.finished_at is not None and view.events[-1].type == view.job.status.value:
            return view
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def settle_all(ledger: SpendLedger, amount_tokens: int) -> None:
    from moody_blues.contracts.agent import TokenTotals

    entry = ledger.reserve("test", worst_case_tokens=amount_tokens)
    ledger.settle(
        entry,
        TokenTotals(prompt_tokens=amount_tokens, completion_tokens=0, total_tokens=amount_tokens),
    )


# --- authorization ------------------------------------------------------------------------


def test_with_no_token_configured_every_operator_route_refuses(tmp_path: Path) -> None:
    c = TestClient(explorer_app(tmp_path), raise_server_exceptions=False)
    for method, path in [
        ("get", "/operator/session"),
        ("get", "/operator/status"),
        ("post", "/operator/jobs"),
        ("get", "/operator/jobs"),
        ("get", "/operator/jobs/job_000000000000"),
        ("post", "/operator/jobs/job_000000000000/cancel"),
        ("get", "/operator/jobs/job_000000000000/events"),
    ]:
        r = getattr(c, method)(path, headers=AUTH)
        assert r.status_code == 403, path
        assert r.json()["error"]["category"] == "forbidden"


def test_a_missing_or_wrong_token_starts_nothing(tmp_path: Path) -> None:
    calls: list[str] = []

    def factory(mission: Mission, investigation_id: str, cancel: Event) -> InvestigationWorkflow:
        calls.append(mission.mission_id)
        raise MissionBlockedError("unreachable")

    app = explorer_app(tmp_path, factory=factory, operator_token=TOKEN)
    c = TestClient(app, raise_server_exceptions=False)
    body = {"mission_id": REHEARSAL}
    assert c.post("/operator/jobs", json=body).status_code == 401
    wrong = {"authorization": "Bearer not-the-token-not-the-token-not-the-token"}
    assert c.post("/operator/jobs", json=body, headers=wrong).status_code == 401
    assert c.post("/operator/jobs", json=body, headers={"authorization": TOKEN}).status_code == 401
    assert calls == []
    assert not (tmp_path / "live-jobs").exists()


def test_repeated_failures_are_throttled_even_for_the_right_token(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    for _ in range(10):
        assert c.get("/operator/session").status_code == 401
    assert c.get("/operator/session").status_code == 429
    assert c.get("/operator/session", headers=AUTH).status_code == 429


def test_a_short_token_is_a_configuration_error() -> None:
    with pytest.raises(ValidationError):
        make_settings(operator_token="short")


def test_the_token_never_appears_in_responses(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    assert TOKEN not in c.get("/operator/status", headers=AUTH).text
    assert TOKEN not in c.get("/health").text


# --- admission ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"mission_id": "custom"},
        {"mission_id": "../../etc"},
        {"mission_id": REHEARSAL, "code": "print(1)"},
        {"mission_id": REHEARSAL, "faults": []},
        {"mission_id": REHEARSAL, "limits": {"max_experiments": 6}},
        {"mission_id": REHEARSAL, "model": "other"},
        {},
    ],
)
def test_only_a_catalog_mission_id_is_accepted(tmp_path: Path, body: dict[str, object]) -> None:
    c = operator_client(tmp_path)
    r = c.post("/operator/jobs", json=body, headers=AUTH)
    assert r.status_code == 422
    assert not (tmp_path / "live-jobs").exists()


def test_no_mission_touches_a_used_or_reserved_world() -> None:
    for mission in MISSIONS:
        assert not any(w.startswith(("w-e", "w-r")) for w in mission.worlds)


def test_live_missions_are_off_by_default(tmp_path: Path) -> None:
    c = operator_client(tmp_path, vultr_api_key="k")
    r = c.post("/operator/jobs", json={"mission_id": LIVE}, headers=AUTH)
    assert r.status_code == 403
    assert "disabled" in r.json()["error"]["message"]


def test_a_live_mission_needs_credentials(tmp_path: Path) -> None:
    c = operator_client(tmp_path, live_runs_enabled=True)
    r = c.post("/operator/jobs", json={"mission_id": LIVE}, headers=AUTH)
    assert r.status_code == 503
    assert r.json()["error"]["category"] == "provider_not_configured"


def test_a_spent_ledger_refuses_a_live_mission_before_a_job_exists(tmp_path: Path) -> None:
    settings: dict[str, Any] = {
        "live_runs_enabled": True,
        "vultr_api_key": "k",
        "live_spend_limit_usd": 1.0,
    }
    ledger = SpendLedger(
        tmp_path / "live-spend" / "ledger.jsonl",
        limit_usd=1.0,
        prices=PriceCeiling(input_per_million_usd=1.40, output_per_million_usd=4.40),
    )
    settle_all(ledger, 200_000)  # $0.28 settled, so $0.72 is left: below the $0.75 cap
    calls: list[str] = []

    def factory(mission: Mission, investigation_id: str, cancel: Event) -> InvestigationWorkflow:
        calls.append(mission.mission_id)
        raise MissionBlockedError("unreachable")

    c = TestClient(
        explorer_app(tmp_path, factory=factory, operator_token=TOKEN, **settings),
        raise_server_exceptions=False,
    )
    r = c.post("/operator/jobs", json={"mission_id": LIVE}, headers=AUTH)
    assert r.status_code == 409
    assert r.json()["error"]["category"] == "budget_exceeded"
    assert calls == []
    status = c.get("/operator/status", headers=AUTH).json()
    live = next(m for m in status["missions"] if m["mission_id"] == LIVE)
    assert live == live | {"available": False, "blocked_by": "budget_insufficient"}
    assert status["budget"]["remaining_usd"] < status["budget"]["required_usd"]


def test_a_corrupt_ledger_refuses_live_and_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "live-spend" / "ledger.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not a ledger\n", encoding="utf-8")
    c = operator_client(tmp_path, live_runs_enabled=True, vultr_api_key="k")
    r = c.post("/operator/jobs", json={"mission_id": LIVE}, headers=AUTH)
    assert r.status_code == 409
    assert c.get("/operator/status", headers=AUTH).json()["budget_problem"] == "ledger_unreadable"


def test_the_api_cannot_raise_the_spend_limit(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    before = c.get("/operator/status", headers=AUTH).json()["budget"]["limit_usd"]
    r = c.post("/operator/jobs", json={"mission_id": LIVE, "limit_usd": 200}, headers=AUTH)
    assert r.status_code == 422
    assert c.get("/operator/status", headers=AUTH).json()["budget"]["limit_usd"] == before


# --- lifecycle ----------------------------------------------------------------------------


def start(c: TestClient, mission: str = REHEARSAL) -> JobRecord:
    r = c.post("/operator/jobs", json={"mission_id": mission}, headers=AUTH)
    assert r.status_code == 202, r.text
    return JobRecord.model_validate(r.json())


def test_a_job_runs_to_durable_evidence(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    job = start(c)
    assert job.mode == "rehearsal"
    view = wait_for_terminal(c, job.job_id)
    assert view.job.status == "completed"
    assert view.job.evidence_available
    types = [e.type.value for e in view.events]
    assert types[:3] == ["created", "queued", "running"]
    assert "experiment_completed" in types
    assert types[-1] == "completed"
    assert [e.event_id for e in view.events] == list(range(1, len(types) + 1))

    detail = c.get(f"/investigations/{job.investigation_id}", headers=AUTH)
    assert detail.status_code == 200
    summary = detail.json()["summary"]
    assert summary["mode"] == "rehearsal"
    assert summary["investigator_evidence"] == "offline_fixture"
    assert summary["target_evidence"] == ["reference_executor"]


def test_the_bundle_is_on_disk_before_the_job_says_it_finished(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    job = start(c)
    view = wait_for_terminal(c, job.job_id)
    bundle = tmp_path / "live-jobs" / job.job_id / BUNDLE
    assert bundle.is_file()
    assert view.job.bundle_sha256 is not None


def test_a_verified_finding_is_announced_from_the_journal(tmp_path: Path) -> None:
    factory = scripted_factory(
        tmp_path,
        replies=[propose(1, CODE), conclude("violation_found")],
        steps=experiment(faults=[PS]),
        target=ReferenceTarget("blind_retry"),
    )
    app = explorer_app(tmp_path, factory=factory, operator_token=TOKEN)
    c = TestClient(app, raise_server_exceptions=False)
    view = wait_for_terminal(c, start(c).job_id)
    types = [e.type.value for e in view.events]
    assert "finding_verified" in types
    assert types.index("finding_verified") > types.index("experiment_completed")


def test_events_carry_no_free_text(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    job = start(c)
    wait_for_terminal(c, job.job_id)
    for line in (tmp_path / "live-jobs" / job.job_id / "events.jsonl").read_text().splitlines():
        body = json.loads(line)
        assert set(body) == {
            "event_id",
            "job_id",
            "at",
            "type",
            "code",
            "experiment_id",
            "result_class",
        }
        assert " " not in body["code"]


class Blocking(ReferenceTarget):
    """Holds a target run open until released."""

    def __init__(self, release: Event, entered: Event) -> None:
        super().__init__("verify_then_report")
        self.release = release
        self.entered = entered

    def run(self, request: TargetRequest) -> TargetResult:
        self.entered.set()
        self.release.wait(10)
        return super().run(request)


def test_a_second_job_is_refused_not_queued(tmp_path: Path) -> None:
    release, entered = Event(), Event()
    factory = scripted_factory(
        tmp_path,
        replies=[propose(1, CODE), conclude()],
        steps=experiment(faults=[PF]),
        target=Blocking(release, entered),
    )
    app = explorer_app(tmp_path, factory=factory, operator_token=TOKEN)
    c = TestClient(app, raise_server_exceptions=False)
    job = start(c)
    assert entered.wait(5)
    r = c.post("/operator/jobs", json={"mission_id": REHEARSAL}, headers=AUTH)
    assert r.status_code == 409
    assert r.json()["error"]["category"] == "conflict"
    status = c.get("/operator/status", headers=AUTH).json()
    assert status["active_job_id"] == job.job_id
    assert all(m["blocked_by"] == "another_job_running" for m in status["missions"])
    release.set()
    wait_for_terminal(c, job.job_id)
    assert len(list((tmp_path / "live-jobs").iterdir())) == 1


def test_cancellation_is_recorded_and_keeps_evidence(tmp_path: Path) -> None:
    release, entered = Event(), Event()
    factory = scripted_factory(
        tmp_path,
        replies=[propose(1, CODE), propose(2, CODE), conclude()],
        steps=[*experiment(faults=[PF]), *experiment(faults=[PS])],
        target=Blocking(release, entered),
    )
    app = explorer_app(tmp_path, factory=factory, operator_token=TOKEN)
    c = TestClient(app, raise_server_exceptions=False)
    job = start(c)
    assert entered.wait(5)
    r = c.post(f"/operator/jobs/{job.job_id}/cancel", headers=AUTH)
    assert r.status_code == 202
    assert r.json()["cancel_requested"] is True
    release.set()
    view = wait_for_terminal(c, job.job_id)
    assert view.job.status in {"cancelled", "outcome_uncertain"}
    assert "cancel_requested" in [e.type.value for e in view.events]
    assert view.job.evidence_available


def test_a_finished_job_cannot_be_cancelled(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    job = start(c)
    wait_for_terminal(c, job.job_id)
    assert c.post(f"/operator/jobs/{job.job_id}/cancel", headers=AUTH).status_code == 409


def test_a_blocked_mission_ends_failed_with_a_code_and_no_investigation(tmp_path: Path) -> None:
    def factory(mission: Mission, investigation_id: str, cancel: Event) -> InvestigationWorkflow:
        raise MissionBlockedError("sandbox_preflight_failed")

    app = explorer_app(tmp_path, factory=factory, operator_token=TOKEN)
    c = TestClient(app, raise_server_exceptions=False)
    job = start(c)
    view = wait_for_terminal(c, job.job_id)
    assert view.job.status == "failed"
    assert view.job.code == "sandbox_preflight_failed"
    assert not view.job.evidence_available
    assert c.get(f"/investigations/{job.investigation_id}", headers=AUTH).status_code == 404


def test_a_crash_inside_the_worker_is_uncertain_not_failed(tmp_path: Path) -> None:
    class Boom(InvestigationWorkflow):
        def run(self) -> InvestigationReport:
            raise RuntimeError("boom")

    inner = clean_factory(tmp_path)

    def factory(mission: Mission, investigation_id: str, cancel: Event) -> InvestigationWorkflow:
        workflow = inner(mission, investigation_id, cancel)
        workflow.__class__ = Boom
        return workflow

    app = explorer_app(tmp_path, factory=factory, operator_token=TOKEN)
    c = TestClient(app, raise_server_exceptions=False)
    view = wait_for_terminal(c, start(c).job_id)
    assert view.job.status == "outcome_uncertain"
    assert view.job.code == "worker_crashed"
    assert "boom" not in c.get(f"/operator/jobs/{view.job.job_id}", headers=AUTH).text


def test_polling_resumes_after_the_last_event(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    job = start(c)
    view = wait_for_terminal(c, job.job_id)
    resumed = c.get(f"/operator/jobs/{job.job_id}?after=2", headers=AUTH).json()
    assert [e["event_id"] for e in resumed["events"]] == [e.event_id for e in view.events[2:]]


def test_sse_replays_from_last_event_id_and_ends(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    job = start(c)
    view = wait_for_terminal(c, job.job_id)
    r = c.get(
        f"/operator/jobs/{job.job_id}/events",
        headers=AUTH | {"last-event-id": "2"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    ids = [int(line[4:]) for line in r.text.splitlines() if line.startswith("id: ")]
    assert ids == [e.event_id for e in view.events[2:]]
    assert "event: end" in r.text


def test_a_bad_job_id_is_a_clean_404(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    for job_id in ("job_000000000000", "../../x", "job_..%2f"):
        assert c.get(f"/operator/jobs/{job_id}", headers=AUTH).status_code == 404


def test_mission_lookup_is_exact() -> None:
    assert find_mission("rehearsal-recovery") is not None
    assert find_mission("REHEARSAL-RECOVERY") is None


# --- after a restart ----------------------------------------------------------------------


def manager(tmp: Path) -> JobManager:
    return JobManager(JobStore(tmp / "live-jobs"), artifacts=tmp, factory=clean_factory(tmp))


def open_job(store: JobStore, status: JobStatus = JobStatus.RUNNING) -> JobRecord:
    now = datetime.now(UTC)
    record = JobRecord(
        job_id="job_aaaaaaaaaaaa",
        mission_id=REHEARSAL,
        mode=ExecutionMode.REHEARSAL,
        status=status,
        investigation_id="inv_aaaaaaaaaaaa",
        created_at=now,
        updated_at=now,
    )
    store.create(record)
    return record


def test_a_job_that_never_started_closes_as_failed_and_is_not_retried(tmp_path: Path) -> None:
    jobs = manager(tmp_path)
    open_job(jobs.store, JobStatus.QUEUED)
    assert jobs.reconcile() == ["job_aaaaaaaaaaaa"]
    record = jobs.store.read("job_aaaaaaaaaaaa")
    assert record is not None
    assert (record.status, record.code) == (JobStatus.FAILED, "interrupted_before_start")
    assert jobs.active_job_id is None
    assert not (tmp_path / "investigations" / record.investigation_id).exists()


def test_reconcile_is_idempotent_and_ignores_finished_jobs(tmp_path: Path) -> None:
    jobs = manager(tmp_path)
    open_job(jobs.store)
    assert jobs.reconcile() == ["job_aaaaaaaaaaaa"]
    assert jobs.reconcile() == []


def test_a_killed_worker_during_a_target_run_is_classified_uncertain(tmp_path: Path) -> None:
    """Real SIGKILL of a real process, mid-run, after a real write committed."""
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "tests.explorer.job_crash_driver", str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        line = ""
        while "COMMITTED" not in line:
            line = child.stdout.readline()
            assert line, "the driver exited before committing"
    finally:
        os.kill(child.pid, signal.SIGKILL)
        child.wait(10)

    jobs = manager(tmp_path)
    [record] = jobs.store.all()
    assert record.status == "running"  # exactly what a dead process leaves behind

    assert jobs.reconcile() == [record.job_id]

    closed = jobs.store.read(record.job_id)
    assert closed is not None
    assert closed.status == "outcome_uncertain"
    assert closed.code == "interrupted_target_run_unresolved"
    assert closed.finished_at is not None
    assert not closed.evidence_available
    assert jobs.store.events(record.job_id)[-1].type == "outcome_uncertain"
    # Nothing was resumed or repeated.
    assert jobs.active_job_id is None
    assert len(jobs.store.all()) == 1


def test_a_job_whose_report_landed_before_the_crash_is_finished_properly(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    job = start(c)
    wait_for_terminal(c, job.job_id)
    # Rewind the job record to what a crash between the report and the job update would leave.
    store = JobStore(tmp_path / "live-jobs")
    done = store.read(job.job_id)
    assert done is not None
    store.save(
        done.model_copy(
            update={
                "status": JobStatus.RUNNING,
                "finished_at": None,
                "evidence_available": False,
                "bundle_sha256": None,
            }
        )
    )
    jobs = JobManager(store, artifacts=tmp_path, factory=clean_factory(tmp_path))
    assert jobs.reconcile() == [job.job_id]
    closed = store.read(job.job_id)
    assert closed is not None
    assert closed.status == "completed"
    assert closed.evidence_available


def test_no_network_or_model_is_used_by_the_default_app(tmp_path: Path) -> None:
    """Constructing the app and reading evidence makes no provider call."""
    assert explorer_app(tmp_path).state.settings.vultr_configured is False


def test_budget_view_is_an_estimate_and_says_so(tmp_path: Path) -> None:
    c = operator_client(tmp_path)
    budget = c.get("/operator/status", headers=AUTH).json()["budget"]
    assert "estimate" in budget["note"].lower()
    assert budget["required_usd"] == 0.75


def test_recorded_evidence_stays_public_without_operator_access(tmp_path: Path) -> None:
    c = TestClient(explorer_app(tmp_path, recorded=RECORDED), raise_server_exceptions=False)
    assert c.get(f"/investigations/{VIOLATION}").status_code == 200
