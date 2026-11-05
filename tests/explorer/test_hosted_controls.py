"""Controls a hosted deployment depends on: the ledger floor, one ledger, no public smoke route."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from moody_blues.api.app import create_app
from moody_blues.config import Settings
from moody_blues.contracts.agent import TokenTotals
from moody_blues.experiments.budget import (
    BudgetExceededError,
    PriceCeiling,
    SpendLedger,
    ledger_path,
)
from moody_blues.explorer.factories import ledger_for

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "t" * 40
AUTH = {"authorization": f"Bearer {TOKEN}"}
PRICES = PriceCeiling(input_per_million_usd=1.40, output_per_million_usd=4.40)


def hosted(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "artifacts_dir": tmp_path,
        "operator_token": TOKEN,
        "vultr_api_key": "fixture-not-a-key",
        "live_runs_enabled": True,
        "live_spend_limit_usd": 10.0,
        "live_ledger_floor_usd": 1.0,
    }
    return Settings(_env_file=None, **(values | overrides))  # type: ignore[call-arg]


def spend(ledger: SpendLedger, tokens: int) -> None:
    entry = ledger.reserve("fixture", worst_case_tokens=tokens)
    ledger.settle(
        entry,
        TokenTotals(prompt_tokens=tokens, completion_tokens=0, total_tokens=tokens),
    )


def test_a_fresh_ledger_below_the_floor_refuses_to_spend(tmp_path: Path) -> None:
    ledger = SpendLedger(tmp_path / "l.jsonl", limit_usd=10, prices=PRICES, floor_usd=1.0)
    with pytest.raises(BudgetExceededError, match="below"):
        ledger.reserve("x", worst_case_tokens=1)
    assert not ledger.path.exists()


def test_a_migrated_ledger_at_the_floor_spends_and_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    spend(SpendLedger(path, limit_usd=10, prices=PRICES), 1_000_000)  # $1.40
    first = SpendLedger(path, limit_usd=10, prices=PRICES, floor_usd=1.0)
    entry = first.reserve("run", worst_case_tokens=1000)
    restarted = SpendLedger(path, limit_usd=10, prices=PRICES, floor_usd=1.0)
    assert restarted.status().open_reservations == 1
    assert restarted.status().settled_usd == first.status().settled_usd
    assert entry


def test_a_truncated_ledger_is_refused_rather_than_read_as_cheaper(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    spend(SpendLedger(path, limit_usd=10, prices=PRICES), 1_000_000)
    path.write_text("", encoding="utf-8")
    ledger = SpendLedger(path, limit_usd=10, prices=PRICES, floor_usd=1.0)
    with pytest.raises(BudgetExceededError):
        ledger.status()


def test_a_lost_ledger_refuses_a_live_mission_before_a_job_exists(tmp_path: Path) -> None:
    with TestClient(create_app(hosted(tmp_path))) as c:
        status = c.get("/operator/status", headers=AUTH).json()
        assert status["budget_problem"] == "ledger_unreadable"
        live = next(m for m in status["missions"] if m["mode"] == "live")
        assert live["available"] is False
        refused = c.post("/operator/jobs", json={"mission_id": live["mission_id"]}, headers=AUTH)
        assert refused.status_code == 409
        assert c.get("/operator/jobs", headers=AUTH).json() == []


def test_the_proposed_limit_admits_exactly_one_investigation(tmp_path: Path) -> None:
    """$7.30 on $6.50 settled: one run of about $0.10 leaves too little for a second."""
    settings = hosted(tmp_path, live_spend_limit_usd=7.30, live_ledger_floor_usd=6.50)
    ledger = ledger_for(settings, tmp_path)
    fixture = SpendLedger(ledger.path, limit_usd=100, prices=PRICES)
    spend(fixture, 4_642_987)  # $6.500182 at the ceiling price, the figure on the real ledger

    def live_available(c: TestClient) -> bool:
        status = c.get("/operator/status", headers=AUTH).json()
        return next(m for m in status["missions"] if m["mode"] == "live")["available"]

    with TestClient(create_app(settings)) as c:
        assert live_available(c) is True
        spend(fixture, 71_429)  # about $0.10
        assert live_available(c) is False


def test_every_ledger_in_the_backend_is_built_with_the_floor() -> None:
    """A direct constructor would skip the floor, so only ``from_settings`` may build one."""
    offenders: list[str] = []
    for path in (ROOT / "backend").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"SpendLedger", "Ledger"}
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_the_api_and_the_cli_share_one_ledger_on_a_host(tmp_path: Path) -> None:
    settings = hosted(tmp_path)
    assert ledger_for(settings, tmp_path).path == ledger_path(settings, ROOT / ".artifacts")
    assert ledger_path(settings, ROOT / ".artifacts") == tmp_path / "live-spend" / "ledger.jsonl"


def test_the_cli_reads_the_configured_ledger_not_the_release_directory(tmp_path: Path) -> None:
    spend(SpendLedger(tmp_path / "live-spend" / "ledger.jsonl", limit_usd=9, prices=PRICES), 1000)
    done = subprocess.run(
        [sys.executable, "-m", "moody_blues.cli", "ledger-verify"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env={"MOODY_ARTIFACTS_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stderr
    assert str(tmp_path) in done.stdout
    assert '"entries": 2' in done.stdout


def test_commands_write_under_the_configured_directory_not_the_release(tmp_path: Path) -> None:
    """A host's release is read-only: this stopped `investigator-preflight` there (KI-41)."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "from moody_blues import cli\n"
            "from moody_blues.investigator import commands\n"
            "print(cli.ARTIFACTS, commands.ARTIFACTS, commands.INVESTIGATIONS)",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env={"MOODY_ARTIFACTS_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == [str(tmp_path), str(tmp_path), f"{tmp_path}/investigations"]


def test_a_corrupt_ledger_fails_verification(tmp_path: Path) -> None:
    path = tmp_path / "live-spend" / "ledger.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not a ledger\n", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-m", "moody_blues.cli", "ledger-verify"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env={"MOODY_ARTIFACTS_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 1
    assert '"status": "FAIL"' in done.stdout


def test_production_has_no_smoke_route(tmp_path: Path) -> None:
    with TestClient(create_app(hosted(tmp_path))) as c:
        assert c.post("/sandbox/smoke").status_code == 404


def test_development_keeps_the_smoke_route(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, artifacts_dir=tmp_path)  # pyright: ignore[reportCallIssue]
    assert "/sandbox/smoke" in create_app(settings).openapi()["paths"]


def test_expired_sandboxes_are_reaped_even_with_no_open_job(tmp_path: Path) -> None:
    """A container on the VM outlived its job and a reboot, as nothing looked (KI-45)."""
    calls: list[int] = []
    app = create_app(hosted(tmp_path))
    with TestClient(app):
        app.state.jobs.reconcile(lambda: calls.append(1))
    assert calls == [1]
