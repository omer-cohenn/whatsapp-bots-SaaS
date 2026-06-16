"""Fail-closed settings loader (M0+M1 minimal surface).

Loads the *only* secrets this minimal build needs from the environment
(a git-ignored `.env.local` in dev). The app **refuses to boot** if any
required value is missing or blank — there are NO constant / "change-me"
defaults. This keeps the seam right for the later secret-manager swap
(roadmap 0.2) without ever shipping a usable default.

Required for this run:
  - GATEWAY_API_TOKEN : shared service token, header-only (both sides)
  - DATABASE_URL      : Postgres DSN for the non-service app role
  - REDIS_URL         : Redis connection URL
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, fail-closed app settings.

    `pydantic-settings` raises `ValidationError` at construction time if a
    field with no default is absent from the environment, which is exactly
    the fail-closed boot we want. We do NOT give the required fields defaults.
    """

    model_config = SettingsConfigDict(
        # In dev, values come from a git-ignored .env.local. In prod they are
        # injected as real env vars (and later a secret manager). We point at
        # .env.local but never commit it.
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Required secrets / connections (NO defaults — boot fails if missing) ---
    gateway_api_token: SecretStr = Field(..., alias="GATEWAY_API_TOKEN")
    database_url: SecretStr = Field(..., alias="DATABASE_URL")
    redis_url: SecretStr = Field(..., alias="REDIS_URL")

    # --- Non-secret operational knobs (safe, explicit defaults allowed) ---
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("gateway_api_token", "database_url", "redis_url")
    @classmethod
    def _reject_blank_or_placeholder(cls, value: SecretStr) -> SecretStr:
        """Reject empty / whitespace / obvious placeholder secrets.

        An env var set to "" satisfies "is present" but is not a real secret;
        fail closed on it. Also reject the classic placeholder tokens so a
        copied-but-unfilled .env.example can never boot the app.
        """
        raw = value.get_secret_value().strip()
        if not raw:
            raise ValueError("must be set to a non-empty value (fail-closed)")
        banned = {"change-me", "changeme", "my-secret-token", "secret", "todo"}
        if raw.lower() in banned:
            raise ValueError("must not be a placeholder/default value (fail-closed)")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton settings, constructing (and validating) once.

    Cached so the env is read a single time. Constructing this is what makes
    the app fail to boot when a required secret is missing.
    """

    return Settings()  # type: ignore[call-arg]  # values come from env/.env.local
