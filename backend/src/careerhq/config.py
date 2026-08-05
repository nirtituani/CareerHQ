"""Application configuration.

Every environment-specific value is read here and nowhere else. Fields without a
default are required: constructing ``Settings`` without them raises a
``ValidationError`` naming the missing field, which is what makes the container
fail at startup rather than at the first request that needs the value (FR-006).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from the environment or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Core ---------------------------------------------------------------
    environment: Literal["local", "production"] = "local"
    log_level: str = "INFO"

    # -- Database -----------------------------------------------------------
    database_url: str

    # -- Cache. Never a source of truth. ------------------------------------
    redis_url: str

    # -- Object storage -----------------------------------------------------
    s3_endpoint_url: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str
    s3_region: str = "us-east-1"

    # -- Authentication -----------------------------------------------------
    # Required, and a minimum length is enforced rather than merely required:
    # .env.example ships this key present but empty, so "required" alone would
    # accept an empty string and the application would sign session tokens with
    # nothing. Rejecting it here is the difference between a startup error and
    # a forgeable session.
    session_secret: SecretStr = Field(min_length=32)
    session_ttl_days: int = Field(default=7, ge=1, le=90)

    # Optional by design. Sign-in cannot work without them, but the platform
    # starts and reports healthy so the environment can be verified before a
    # Google Cloud OAuth client exists. The auth routes fail loudly when these
    # are unset rather than blocking startup for everyone.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # -- AI: configuration seam only. No client code exists in this slice. ---
    # LiteLLM provider/model naming.
    llm_provider_model: str = "anthropic/claude-opus-5"
    anthropic_api_key: SecretStr | None = None
    # Local by default so the stack runs with no API key. Anthropic has no
    # embeddings endpoint, which is why this is not an Anthropic model.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def google_oauth_configured(self) -> bool:
        return self.google_client_id is not None and self.google_client_secret is not None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once.

    Cached so that configuration is read and validated a single time, and so
    tests can clear the cache to substitute a different environment.
    """
    return Settings()  # values are supplied by the environment
