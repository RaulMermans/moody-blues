"""The commands refuse before anything runs. None of these reach Docker or a provider."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from moody_blues.config import Settings
from moody_blues.external import bundle, commands
from moody_blues.external.bundle import ManifestError, build_bundle
from tests.conftest import make_settings
from tests.external.conftest import EXAMPLES

CAREFUL = EXAMPLES / "careful.agent.toml"
LLM = EXAMPLES / "llm.agent.toml"


def _run(settings: Settings, manifest: Path = CAREFUL, **options: object) -> int:
    defaults: dict[str, object] = {
        "world": "normal-success",
        "live_inference": False,
        "confirm_billable": False,
    }
    return commands.run(settings, manifest, **(defaults | options))  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("world", ["w-r1", "w-e1", "w-v1", "no-such-world"])
def test_reserved_and_evaluation_worlds_are_refused(
    world: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(make_settings(), world=world) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_a_bad_manifest_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "x.toml"
    path.write_text("not toml =")
    assert _run(make_settings(), path) == 1
    assert commands.preflight(make_settings(), path) == 1
    assert "not valid TOML" in capsys.readouterr().out


def test_live_inference_needs_the_billable_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(make_settings(vultr_api_key="k"), LLM, live_inference=True) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "NOT_RUN"
    assert "billable" in report["reason"]


def test_live_inference_needs_a_key(capsys: pytest.CaptureFixture[str]) -> None:
    code = _run(make_settings(vultr_api_key=None), LLM, live_inference=True, confirm_billable=True)
    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED_BY_CREDENTIALS"


def test_nothing_runs_when_the_preflight_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed(_: Settings) -> SimpleNamespace:
        return SimpleNamespace(status="FAIL", checks=[])

    monkeypatch.setattr(commands, "run_preflight", failed)
    assert _run(make_settings()) == 2
    assert commands.demo(make_settings()) == 2
    assert commands.preflight(make_settings(), CAREFUL) == 2
    assert "no external code was run" in capsys.readouterr().out


def test_a_bundle_without_the_sdk_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle, "SDK_ROOT", Path("/nonexistent"))
    with pytest.raises(ManifestError, match="SDK"):
        build_bundle(CAREFUL)
