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

    # --- M2 encryption keys (separate domains; fail-closed, no defaults) ---
    # PII_DATA_KEY / WA_CRED_KEK are Fernet keys (urlsafe-base64, 32 bytes).
    pii_data_key: SecretStr = Field(..., alias="PII_DATA_KEY")
    wa_cred_kek: SecretStr = Field(..., alias="WA_CRED_KEK")
    phone_hmac_key: SecretStr = Field(..., alias="PHONE_HMAC_KEY")

    # --- M2 gateway-role DSN (crown-jewel access). Optional in the shared app
    # config: only the gateway / isolation demo connects as gateway_role. ---
    gateway_database_url: SecretStr | None = Field(default=None, alias="GATEWAY_DATABASE_URL")

    # --- Auth / session (Google OAuth login). All required (fail-closed). ---
    # google_redirect_uri is non-secret but still required + non-blank (a wrong
    # or empty redirect breaks the whole login flow), so it gets its own check.
    google_client_id: SecretStr = Field(..., alias="GOOGLE_CLIENT_ID")
    google_client_secret: SecretStr = Field(..., alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(..., alias="GOOGLE_REDIRECT_URI")
    session_secret: SecretStr = Field(..., alias="SESSION_SECRET")

    # --- M4 AI bot builder (Gemini). OPTIONAL — validate-at-USE, not at boot. ---
    # The stack must still boot with NO Gemini key (try-me/dev without AI). The
    # bot-builder service checks this lazily and raises a typed error → HTTP 503
    # when it's actually needed. So it is NOT in the fail-closed validator below.
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")

    # --- Non-secret operational knobs (safe, explicit defaults allowed) ---
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator(
        "gateway_api_token", "database_url", "redis_url",
        "pii_data_key", "wa_cred_kek", "phone_hmac_key",
        "google_client_id", "google_client_secret", "session_secret",
    )
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

    @field_validator("google_redirect_uri")
    @classmethod
    def _reject_blank_redirect(cls, value: str) -> str:
        """google_redirect_uri is non-secret but still required + non-blank.

        An empty redirect URI silently breaks the OAuth round-trip, so fail
        closed on it just like the secrets above.
        """
        if not value.strip():
            raise ValueError("GOOGLE_REDIRECT_URI must be set to a non-empty value (fail-closed)")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton settings, constructing (and validating) once.

    Cached so the env is read a single time. Constructing this is what makes
    the app fail to boot when a required secret is missing.
    """

    return Settings()  # type: ignore[call-arg]  # values come from env/.env.local
