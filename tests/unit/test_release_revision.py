"""What is live can be read from outside, and only a commit id can be read that way."""

from __future__ import annotations

from pathlib import Path

from moody_blues.services.health import release_revision

COMMIT = "6405817abc" + "0" * 30


def test_a_release_reports_its_commit(tmp_path: Path) -> None:
    path = tmp_path / "REVISION"
    path.write_text(f"{COMMIT}\n", encoding="ascii")
    assert release_revision(path) == COMMIT


def test_a_checkout_reports_none(tmp_path: Path) -> None:
    assert release_revision(tmp_path / "REVISION") is None


def test_anything_but_a_commit_id_is_not_repeated(tmp_path: Path) -> None:
    path = tmp_path / "REVISION"
    for text in ("MOODY_VULTR_API_KEY=abc", "main", COMMIT + "0", COMMIT.upper()):
        path.write_text(text, encoding="ascii")
        assert release_revision(path) is None
