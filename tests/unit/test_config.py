from __future__ import annotations

import pytest
from pydantic import ValidationError

from moody_blues.config import DEFAULT_VULTR_MODEL, VULTR_INFERENCE_BASE_URL, Settings
from tests.conftest import make_settings


def test_defaults_are_safe() -> None:
    s = make_settings()
    assert s.vultr_api_key is None
    assert not s.vultr_configured
    assert s.vultr_base_url == VULTR_INFERENCE_BASE_URL
    assert s.vultr_model == DEFAULT_VULTR_MODEL
    assert s.vultr_max_retries == 2


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOODY_VULTR_API_KEY", "sk-test-123")
    monkeypatch.setenv("MOODY_VULTR_MODEL", "some-model")
    monkeypatch.setenv("MOODY_SANDBOX_MEMORY_MB", "256")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.vultr_configured
    assert s.vultr_model == "some-model"
    assert s.sandbox_memory_mb == 256


def test_secret_never_rendered() -> None:
    s = make_settings(vultr_api_key="sk-super-secret")
    assert "sk-super-secret" not in repr(s)
    assert "sk-super-secret" not in s.model_dump_json()


def test_empty_key_is_not_configured() -> None:
    assert not make_settings(vultr_api_key="").vultr_configured


@pytest.mark.parametrize(
    ("field", "value"),
    [("vultr_max_retries", 99), ("vultr_timeout_seconds", 0), ("sandbox_memory_mb", 1)],
)
def test_bounds_enforced(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})
