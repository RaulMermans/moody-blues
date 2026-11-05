"""The live switch, run for real against a temporary env file.

The only stand-ins are `ssh`, which runs the remote command here and logs its arguments, and the
two programs that touch the service. A key must survive any character and never be an argument.
"""

# ruff: noqa: S603, S607

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra" / "vultr"
PLAIN_KEY = "ABCDEF0123456789-plain.key"
ENV = """# a comment that stays
MOODY_ENVIRONMENT=production
MOODY_OPERATOR_TOKEN=keep-this-token
MOODY_LIVE_RUNS_ENABLED=false
MOODY_LIVE_SPEND_LIMIT_USD=5

MOODY_VULTR_API_KEY=
MOODY_VULTR_MODEL=glm-5.3
"""
SPECIAL_KEYS = [
    "pipe|in|key",
    "amp&ersand",
    "back\\slash\\",
    "slash/in/key",
    "dollar$HOME$(id)",
    'double"quote',
    "single'quote",
    "hash#tag",
    "back`tick`",
    "with space",
    "sed\\1&|s/x/y/",
]


class Rig:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.repo = base / "repo"
        self.env_file = base / "etc" / "backend.env"
        self.argv_log = base / "argv.log"
        self.stdin_log = base / "stdin.log"
        self.restarts = base / "restarts.log"
        tools = self.repo / "infra" / "vultr"
        tools.mkdir(parents=True)
        for name in ("live-switch.sh", "live-env.py"):
            shutil.copy(INFRA / name, tools / name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.env_file.parent.mkdir()
        self.env_file.write_text(ENV, encoding="utf-8")
        self.env_file.chmod(0o640)
        bin_dir = base / "bin"
        bin_dir.mkdir()
        self._tool(
            bin_dir / "ssh",
            f"""for arg in "$@"; do printf '%s\\n' "$arg" >> {self.argv_log}; done
remote="${{@: -1}}"
exec bash -c "$remote"
""",
        )
        self._tool(bin_dir / "systemctl", f'echo "$*" >> {self.restarts}\nexit 0\n')
        self._tool(bin_dir / "curl", f"[ ! -e {base}/unhealthy ]\n")
        self.environment = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MOODY_BACKEND_ENV_FILE": str(self.env_file),
            "MOODY_HEALTH_WAIT_SECONDS": "0",
        }

    @staticmethod
    def _tool(path: Path, body: str) -> None:
        path.write_text(f"#!/usr/bin/env bash\n{body}", encoding="utf-8")
        path.chmod(0o755)

    def switch(self, *args: str, key: str = PLAIN_KEY) -> subprocess.CompletedProcess[str]:
        (self.repo / ".env").write_text(f"MOODY_VULTR_API_KEY={key}\n", encoding="utf-8")
        return subprocess.run(
            ["bash", str(self.repo / "infra" / "vultr" / "live-switch.sh"), "203.0.113.9", *args],
            cwd=self.repo,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def sourced(self, name: str) -> str:
        """What `moody-cli` would see: the file read by a real shell."""
        script = f'set -a; source "$1"; set +a; printf %s "${{{name}}}"'
        result = subprocess.run(
            ["bash", "-c", script, "bash", str(self.env_file)],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def break_the_backend(self) -> None:
        (self.base / "unhealthy").touch()


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


@pytest.mark.parametrize("key", SPECIAL_KEYS)
def test_a_key_with_special_characters_arrives_unchanged(rig: Rig, key: str) -> None:
    result = rig.switch("on", "7.30", key=key)
    assert result.returncode == 0, result.stderr
    assert rig.sourced("MOODY_VULTR_API_KEY") == key
    assert rig.sourced("MOODY_OPERATOR_TOKEN") == "keep-this-token"
    assert rig.sourced("MOODY_LIVE_RUNS_ENABLED") == "true"
    assert rig.sourced("MOODY_LIVE_SPEND_LIMIT_USD") == "7.30"


@pytest.mark.parametrize("key", [PLAIN_KEY, *SPECIAL_KEYS])
def test_the_key_is_never_an_argument_or_printed(rig: Rig, key: str) -> None:
    result = rig.switch("on", "7.30", key=key)
    assert key not in rig.argv_log.read_text(encoding="utf-8")
    assert key not in rig.restarts.read_text(encoding="utf-8")
    assert key not in result.stdout + result.stderr


def test_unrelated_lines_stay_byte_for_byte(rig: Rig) -> None:
    rig.switch("on", "7.30")
    changed = {"MOODY_VULTR_API_KEY", "MOODY_LIVE_RUNS_ENABLED", "MOODY_LIVE_SPEND_LIMIT_USD"}
    lines = rig.env_file.read_text(encoding="utf-8").splitlines()
    expected = ENV.splitlines()
    assert len(lines) == len(expected)
    for now, was in zip(lines, expected, strict=True):
        if was.split("=", 1)[0] not in changed:
            assert now == was


def test_permissions_hold_and_no_temporary_file_is_left(rig: Rig) -> None:
    rig.switch("on", "7.30")
    assert stat.S_IMODE(rig.env_file.stat().st_mode) == 0o640
    assert [p.name for p in rig.env_file.parent.iterdir()] == ["backend.env"]
    rig.switch("off")
    assert stat.S_IMODE(rig.env_file.stat().st_mode) == 0o640
    assert [p.name for p in rig.env_file.parent.iterdir()] == ["backend.env"]


def test_off_removes_the_key_and_keeps_everything_else(rig: Rig) -> None:
    rig.switch("on", "7.30", key="pipe|in|key")
    result = rig.switch("off")
    assert result.returncode == 0, result.stderr
    assert rig.env_file.read_text(encoding="utf-8") == ENV
    assert "pipe|in|key" not in rig.env_file.read_text(encoding="utf-8")


def test_a_failed_on_restores_the_previous_file(rig: Rig) -> None:
    rig.break_the_backend()
    result = rig.switch("on", "7.30", key="pipe|in|key")
    assert result.returncode != 0
    assert rig.env_file.read_text(encoding="utf-8") == ENV
    assert "pipe|in|key" not in result.stdout + result.stderr


def test_a_failed_off_never_restores_the_key(rig: Rig) -> None:
    rig.switch("on", "7.30", key="pipe|in|key")
    rig.break_the_backend()
    result = rig.switch("off")
    assert result.returncode != 0
    assert rig.env_file.read_text(encoding="utf-8") == ENV


def test_an_empty_key_changes_nothing(rig: Rig) -> None:
    result = rig.switch("on", "7.30", key="")
    assert result.returncode != 0
    assert rig.env_file.read_text(encoding="utf-8") == ENV
    assert not rig.restarts.exists()


def test_a_bad_limit_changes_nothing(rig: Rig) -> None:
    result = rig.switch("on", "7.30; reboot")
    assert result.returncode != 0
    assert rig.env_file.read_text(encoding="utf-8") == ENV


def test_a_missing_line_is_added_and_duplicates_collapse(rig: Rig) -> None:
    rig.env_file.write_text(
        "MOODY_VULTR_API_KEY=old\nMOODY_VULTR_API_KEY=older\nOTHER=1", encoding="utf-8"
    )
    rig.switch("on", "7.30")
    text = rig.env_file.read_text(encoding="utf-8")
    assert text.count("MOODY_VULTR_API_KEY=") == 1
    assert rig.sourced("MOODY_VULTR_API_KEY") == PLAIN_KEY
    assert rig.sourced("OTHER") == "1"
    assert rig.sourced("MOODY_LIVE_RUNS_ENABLED") == "true"


def test_the_switch_no_longer_edits_with_sed() -> None:
    assert "sed" not in (INFRA / "live-switch.sh").read_text(encoding="utf-8")
