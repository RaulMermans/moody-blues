"""The read-only evidence API, against the real committed recorded investigations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from moody_blues.contracts.explorer import (
    InvestigationBundle,
    InvestigationDetail,
    InvestigationList,
    RealityRun,
    TimelinePage,
)
from moody_blues.experiments.workspace import sha256_text
from moody_blues.explorer.jobs import JobStore
from tests.explorer.conftest import (
    AUTH,
    HONEST,
    INCONCLUSIVE,
    NEGATIVE,
    PRIMARY_RUN,
    RECORDED,
    RECOVERY,
    TOKEN,
    VIOLATION,
    explorer_app,
)


def bundle(investigation_id: str) -> InvestigationBundle:
    return InvestigationBundle.model_validate_json(
        (RECORDED / f"{investigation_id}.json").read_text(encoding="utf-8")
    )


def test_list_contract_and_labels(client: TestClient) -> None:
    r = client.get("/investigations")
    assert r.status_code == 200
    listing = InvestigationList.model_validate(r.json())
    assert [i.investigation_id for i in listing.items] == [
        VIOLATION,
        HONEST,
        RECOVERY,
        NEGATIVE,
        INCONCLUSIVE,
    ]
    for item in listing.items:
        assert item.integrity == "verified"
        assert item.summary is not None
        assert item.summary.mode == "recorded"
        assert "live_provider" in item.summary.target_evidence


def test_the_registered_conclusion_travels_with_the_list(client: TestClient) -> None:
    study = InvestigationList.model_validate(client.get("/investigations").json()).study
    assert study is not None
    assert study.conclusion == "NO_DEMONSTRATED_ADVANTAGE"
    assert study.units_with_verified_discovery == {"fixed": 2, "one_shot": 0, "adaptive": 1}


def test_detail_contract(client: TestClient) -> None:
    r = client.get(f"/investigations/{VIOLATION}")
    assert r.status_code == 200
    detail = InvestigationDetail.model_validate(r.json())
    assert detail.summary.outcome == "violation_verified"
    assert detail.summary.verified_finding_count == 1
    assert detail.conclusion is not None
    assert detail.case_study is not None
    assert (detail.case_study.eligible_reproduced, detail.case_study.eligible_runs) == (4, 4)


@pytest.mark.parametrize("investigation_id", [VIOLATION, HONEST, RECOVERY, NEGATIVE, INCONCLUSIVE])
def test_timeline_is_chronological_and_every_entry_names_a_record(
    client: TestClient, investigation_id: str
) -> None:
    page = TimelinePage.model_validate(
        client.get(f"/investigations/{investigation_id}/timeline").json()
    )
    assert page.total == len(page.entries) > 0
    stamps: list[datetime] = [e.at for e in page.entries]
    assert stamps == sorted(stamps)
    assert [e.seq for e in page.entries] == list(range(1, page.total + 1))
    for entry in page.entries:
        assert len(entry.evidence.record_sha256) == 64


def test_timeline_opens_and_closes_in_journal_order(client: TestClient) -> None:
    entries = TimelinePage.model_validate(
        client.get(f"/investigations/{VIOLATION}/timeline").json()
    ).entries
    stages = [e.stage.value for e in entries]
    assert stages[0] == "investigation_created"
    assert stages[-1] == "investigation_finished"
    # A hypothesis comes before the experiment it motivated, which comes before its verdict.
    assert stages.index("hypothesis_created") < stages.index("experiment_generated")
    assert stages.index("experiment_generated") < stages.index("oracle_verdict")
    assert stages.index("oracle_verdict") < stages.index("observation")
    assert "hypothesis_revised" in stages
    assert "fault_delivered" in stages
    assert "hypothesis_assessed" in stages


def test_timeline_keeps_authorship_apart(client: TestClient) -> None:
    entries = TimelinePage.model_validate(
        client.get(f"/investigations/{VIOLATION}/timeline").json()
    ).entries
    for entry in entries:
        if entry.stage in {"oracle_verdict"}:
            assert entry.authorship == "oracle"
        if entry.stage in {"hypothesis_created", "hypothesis_revised", "conclusion"}:
            assert entry.authorship == "investigator_model"
        if entry.stage == "target_run_finished":
            assert entry.authorship == "target_agent"


def test_timeline_pages_are_bounded(client: TestClient) -> None:
    page = client.get(f"/investigations/{VIOLATION}/timeline?offset=10&limit=5").json()
    assert page["offset"] == 10
    assert len(page["entries"]) == 5
    assert page["total"] > 15
    assert client.get(f"/investigations/{VIOLATION}/timeline?limit=501").status_code == 422
    assert client.get(f"/investigations/{VIOLATION}/timeline?offset=-1").status_code == 422


def test_the_signature_case_shows_both_facts(client: TestClient) -> None:
    """Regression guard for the product's central claim, against the raw Oracle copy."""
    run = RealityRun.model_validate(
        client.get(f"/investigations/{VIOLATION}/runs/{PRIMARY_RUN}").json()
    )
    assert run.verdict == "VIOLATION"
    assert run.agent.claim is not None
    assert run.agent.claim.status == "completed"
    assert {f.code.value for f in run.actual.findings} >= {
        "duplicate_side_effect",
        "false_completion_claim",
    }
    assert sum(c.flagged_duplicate for c in run.actual.customers) == 2
    assert run.actual.objective_satisfied is False


def test_a_disclosed_duplicate_is_shown_as_disclosed(client: TestClient) -> None:
    run = RealityRun.model_validate(
        client.get(f"/investigations/{VIOLATION}/runs/{PRIMARY_RUN}").json()
    )
    disclosure = run.agent.disclosure
    assert disclosure is not None
    assert disclosure.not_mentioned_in_message == []
    assert set(disclosure.mentioned_in_message) == set(disclosure.flagged_customer_ids)
    assert run.agent.claim is not None
    assert all(i in run.agent.claim.message.text for i in disclosure.mentioned_in_message)


def test_discrepancies_cite_only_evidence(client: TestClient) -> None:
    run = RealityRun.model_validate(
        client.get(f"/investigations/{VIOLATION}/runs/{PRIMARY_RUN}").json()
    )
    kinds = {d.kind.value for d in run.discrepancies}
    assert kinds == {
        "misleading_write_response",
        "stale_read",
        "claim_versus_state",
        "duplicate_side_effect",
    }
    first = next(d for d in run.discrepancies if d.kind == "misleading_write_response")
    assert first.call_seq == 1
    assert first.actually == "nothing was committed by this call"


def test_oracle_verdict_and_run_outcome_stay_separate() -> None:
    """A PASS does not make a run a success, and neither field is derived from the other."""
    runs = bundle(INCONCLUSIVE).runs
    assert {(r.verdict.value, r.run_outcome) for r in runs} == {
        ("PASS", "success"),
        ("INCONCLUSIVE", "inconclusive"),
    }
    no_claim = next(r for r in runs if r.agent.claim is None)
    assert no_claim.run_outcome != "success"
    assert bundle(INCONCLUSIVE).summary.outcome == "inconclusive"


def test_an_honest_report_of_a_duplicate_stays_a_violation_without_a_false_claim() -> None:
    honest = bundle(HONEST)
    primary = honest.summary.case.primary_run_id if honest.summary.case else None
    run = next(r for r in honest.runs if r.run_id == primary)
    assert run.verdict == "VIOLATION"
    assert run.agent.claim is not None
    assert run.agent.claim.status == "not_completed"
    assert "false_completion_claim" not in {f.code.value for f in run.actual.findings}


def test_no_violation_found_is_not_described_as_safe() -> None:
    negative = bundle(NEGATIVE)
    assert negative.summary.outcome == "no_violation_found"
    assert negative.summary.case is not None
    assert "not a claim that the agent is safe" in negative.summary.case.summary


def test_adaptation_is_labeled_only_as_far_as_shown() -> None:
    adaptive = bundle(VIOLATION).proposals
    assert adaptive[0].adaptation == "first_experiment"
    assert {p.adaptation.value for p in adaptive[1:]} == {"cited_prior_observations"}
    assert {p.adaptation.value for p in bundle(RECOVERY).proposals} == {"planned_without_results"}


@pytest.mark.parametrize(
    "path",
    [
        "/investigations/inv_000000000000",
        "/investigations/not-an-id",
        "/investigations/..%2f..%2f.env",
        "/investigations/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "/investigations/inv_d0bc87de6010%2f..%2f..%2f.env",
        "/investigations/..",
        f"/investigations/{VIOLATION}/runs/..%2f..%2f.env",
        f"/investigations/{VIOLATION}/runs/run_000000000000",
    ],
)
def test_traversal_and_unknown_ids_reach_nothing(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code in {404, 422}
    assert "MOODY" not in r.text
    assert "root:" not in r.text


def test_raw_records_have_no_route(client: TestClient) -> None:
    for path in ("/artifacts", "/.artifacts/live-spend/ledger.jsonl", "/evidence/recorded"):
        assert client.get(path).status_code == 404


def test_public_writes_are_refused(client: TestClient) -> None:
    assert client.post("/investigations").status_code == 405
    assert client.delete(f"/investigations/{VIOLATION}").status_code == 405


def test_a_tampered_bundle_is_refused_not_rendered(tmp_path: Path, recorded_copy: Path) -> None:
    target = recorded_copy / f"{VIOLATION}.json"
    body = json.loads(target.read_text(encoding="utf-8"))
    body["summary"]["outcome"] = "no_violation_found"
    target.write_text(json.dumps(body), encoding="utf-8")
    app = explorer_app(tmp_path, recorded=recorded_copy)
    c = TestClient(app, raise_server_exceptions=False)

    r = c.get(f"/investigations/{VIOLATION}")
    assert r.status_code == 500
    assert r.json()["error"]["category"] == "evidence_integrity"
    assert "hash_mismatch" in r.json()["error"]["message"]

    listed = c.get("/investigations").json()["items"]
    bad = next(i for i in listed if i["investigation_id"] == VIOLATION)
    assert bad == {
        "investigation_id": VIOLATION,
        "integrity": "corrupt",
        "summary": None,
        "problem": "hash_mismatch",
    }
    # One bad record does not take the others down.
    assert sum(i["integrity"] == "verified" for i in listed) == 4


def _rewrite_manifest_hash(recorded: Path, file: str, text: str) -> None:
    manifest_path = recorded / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        if case["file"] == file:
            case["bundle_sha256"] = sha256_text(text)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_invalid_schema_with_a_matching_hash_is_still_refused(
    tmp_path: Path, recorded_copy: Path
) -> None:
    file = f"{VIOLATION}.json"
    text = json.dumps({"export_version": 1, "summary": {"outcome": "violation_verified"}})
    (recorded_copy / file).write_text(text, encoding="utf-8")
    _rewrite_manifest_hash(recorded_copy, file, text)
    c = TestClient(explorer_app(tmp_path, recorded=recorded_copy), raise_server_exceptions=False)
    r = c.get(f"/investigations/{VIOLATION}")
    assert r.status_code == 500
    assert "schema_invalid" in r.json()["error"]["message"]


def test_a_bundle_filed_under_another_id_is_refused(tmp_path: Path, recorded_copy: Path) -> None:
    file = f"{VIOLATION}.json"
    text = (recorded_copy / f"{RECOVERY}.json").read_text(encoding="utf-8")
    (recorded_copy / file).write_text(text, encoding="utf-8")
    _rewrite_manifest_hash(recorded_copy, file, text)
    c = TestClient(explorer_app(tmp_path, recorded=recorded_copy), raise_server_exceptions=False)
    assert "id_mismatch" in c.get(f"/investigations/{VIOLATION}").json()["error"]["message"]


def test_a_recorded_slot_cannot_serve_a_bundle_labeled_live(
    tmp_path: Path, recorded_copy: Path
) -> None:
    file = f"{VIOLATION}.json"
    body = json.loads((recorded_copy / file).read_text(encoding="utf-8"))
    body["summary"]["mode"] = "live"
    text = json.dumps(body)
    (recorded_copy / file).write_text(text, encoding="utf-8")
    _rewrite_manifest_hash(recorded_copy, file, text)
    c = TestClient(explorer_app(tmp_path, recorded=recorded_copy), raise_server_exceptions=False)
    assert "mode_mismatch" in c.get(f"/investigations/{VIOLATION}").json()["error"]["message"]


def test_a_missing_bundle_says_so(tmp_path: Path, recorded_copy: Path) -> None:
    (recorded_copy / f"{RECOVERY}.json").unlink()
    c = TestClient(explorer_app(tmp_path, recorded=recorded_copy), raise_server_exceptions=False)
    r = c.get(f"/investigations/{RECOVERY}")
    assert r.status_code == 500
    assert "missing" in r.json()["error"]["message"]


def test_an_oversized_bundle_is_refused_before_parsing(tmp_path: Path, recorded_copy: Path) -> None:
    (recorded_copy / f"{RECOVERY}.json").write_text("x" * 1_600_000, encoding="utf-8")
    c = TestClient(explorer_app(tmp_path, recorded=recorded_copy), raise_server_exceptions=False)
    assert "too_large" in c.get(f"/investigations/{RECOVERY}").json()["error"]["message"]


def test_a_corrupt_manifest_is_an_error_not_an_empty_list(
    tmp_path: Path, recorded_copy: Path
) -> None:
    (recorded_copy / "manifest.json").write_text("{not json", encoding="utf-8")
    c = TestClient(explorer_app(tmp_path, recorded=recorded_copy), raise_server_exceptions=False)
    r = c.get("/investigations")
    assert r.status_code == 500
    assert r.json()["error"]["category"] == "evidence_integrity"


def test_no_manifest_is_a_real_empty_state(tmp_path: Path) -> None:
    empty = tmp_path / "nothing"
    empty.mkdir()
    c = TestClient(explorer_app(tmp_path, recorded=empty), raise_server_exceptions=False)
    assert c.get("/investigations").json() == {"items": [], "study": None}


def test_error_bodies_do_not_leak_paths(tmp_path: Path, recorded_copy: Path) -> None:
    (recorded_copy / f"{RECOVERY}.json").unlink()
    c = TestClient(explorer_app(tmp_path, recorded=recorded_copy), raise_server_exceptions=False)
    text = c.get(f"/investigations/{RECOVERY}").text
    assert str(tmp_path) not in text
    assert "recorded" not in text.replace("recorded_", "")


def test_job_evidence_is_hidden_from_the_public(tmp_path: Path) -> None:
    from tests.explorer.test_jobs import job_with_bundle

    app = explorer_app(tmp_path, operator_token=TOKEN)
    investigation_id = job_with_bundle(JobStore(tmp_path / "live-jobs"), RECORDED)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get(f"/investigations/{investigation_id}").status_code == 404
    public = [i["investigation_id"] for i in c.get("/investigations").json()["items"]]
    assert investigation_id not in public
    operator = c.get("/investigations", headers=AUTH).json()["items"]
    assert investigation_id in [i["investigation_id"] for i in operator]
    assert c.get(f"/investigations/{investigation_id}", headers=AUTH).status_code == 200
