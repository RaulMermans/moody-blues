"""Environment-based configuration.

All settings are read from environment variables (prefix ``MOODY_``) or a local
``.env`` file. Secrets are held as ``SecretStr`` so they never appear in reprs or logs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

VULTR_INFERENCE_BASE_URL = "https://api.vultrinference.com/v1"

# Documented by Vultr as the model supporting tool calling
# (https://docs.vultr.com/how-to-use-tool-calling-with-vultr-serverless-inference).
# Verify against the live catalog with `make vultr-models` once credentials exist.
DEFAULT_VULTR_MODEL = "kimi-k2-instruct"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOODY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Vultr Serverless Inference
    vultr_api_key: SecretStr | None = None
    vultr_base_url: str = VULTR_INFERENCE_BASE_URL
    vultr_model: str = DEFAULT_VULTR_MODEL
    vultr_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    vultr_max_retries: int = Field(default=2, ge=0, le=5)
    # Optional, for cost estimates only. Unset means "unknown"; nothing guesses a price.
    vultr_price_per_million_tokens_usd: float | None = Field(default=None, ge=0, le=1_000)

    # Live spending guard. An application-side estimate, NOT a provider billing limit.
    live_spend_limit_usd: float = Field(default=5.0, gt=0, le=200)
    # Vultr publishes no per-model price for the models we use, so these are deliberately
    # high assumptions (see docs/deployment/live-budget.md), not quoted prices.
    live_price_ceiling_input_per_million_usd: float = Field(default=1.40, gt=0, le=1_000)
    live_price_ceiling_output_per_million_usd: float = Field(default=4.40, gt=0, le=1_000)

    # Investigator. Model-generated code runs only on this image: pinned to a digest, never
    # pulled implicitly. Verified by `make investigator-preflight`.
    investigator_model: str = "glm-5.3"
    investigator_target_model: str = "glm-5.3"
    investigator_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    # SDK retries happen before a response exists, so they cannot replay a tool call. Model
    # calls reserve once per attempt. A live HTTP 502 ended an investigation with this at 0.
    investigator_max_retries: int = Field(default=1, ge=0, le=2)
    investigator_max_spend_usd: float = Field(default=0.75, gt=0, le=5)
    generated_code_image: str = (
        "python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30"
    )

    # Sandbox
    docker_host: str | None = None
    sandbox_image: str = "python:3.12-slim"
    sandbox_wall_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    sandbox_memory_mb: int = Field(default=128, ge=16, le=2048)
    sandbox_cpus: float = Field(default=0.5, gt=0, le=4)
    sandbox_pids_limit: int = Field(default=64, ge=8, le=1024)
    sandbox_output_limit_bytes: int = Field(default=64_000, ge=1_000, le=1_000_000)

    @property
    def vultr_configured(self) -> bool:
        return self.vultr_api_key is not None and bool(self.vultr_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
