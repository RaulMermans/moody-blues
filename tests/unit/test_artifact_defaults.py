"""A free command must not reach canonical evidence unless someone says so (KI-79)."""

from __future__ import annotations

from pathlib import Path

from moody_blues.evaluation.benchmark import commands
from moody_blues.explorer.paths import REPO_ROOT, artifacts_dir, rehearsal_artifacts
from tests.conftest import make_settings

CANONICAL = (REPO_ROOT / ".artifacts").resolve()


def test_a_rehearsal_is_never_canonical_by_default() -> None:
    first = rehearsal_artifacts(make_settings())
    second = rehearsal_artifacts(make_settings())
    assert first != second
    assert CANONICAL not in (first.resolve(), *first.resolve().parents)


def test_an_explicit_directory_is_honored(tmp_path: Path) -> None:
    assert rehearsal_artifacts(make_settings(artifacts_dir=tmp_path)) == tmp_path


def test_paid_commands_keep_one_place_for_the_ledger() -> None:
    assert artifacts_dir(make_settings()).resolve() == CANONICAL


def test_the_benchmark_refuses_canonical_artifacts(tmp_path: Path) -> None:
    root = commands._root  # pyright: ignore[reportPrivateUsage]
    assert root(make_settings()) is None
    assert root(make_settings(artifacts_dir=CANONICAL)) is None
    assert root(make_settings(artifacts_dir=tmp_path)) == tmp_path
