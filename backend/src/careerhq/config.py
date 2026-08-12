"""Application configuration.

Every environment-specific value is read here and nowhere else. Fields without a
default are required: constructing ``Settings`` without them raises a
``ValidationError`` naming the missing field, which is what makes the container
fail at startup rather than at the first request that needs the value (FR-006).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_core import ErrorDetails
from pydantic_settings import BaseSettings, SettingsConfigDict


class DependencyNotConfiguredError(RuntimeError):
    """Raised when a client is requested for a dependency that is not configured.

    Optional configuration trades away the fail-fast property that a missing
    required field gives: the process no longer stops at startup naming the
    setting. This moves that failure to first use rather than losing it — a
    caller that reaches for an unconfigured cache gets an error naming the
    setting to add, not an `AttributeError` on `None` several frames away.
    """

    def __init__(self, dependency: str, setting: str) -> None:
        super().__init__(
            f"{dependency} is not configured — set {setting}. "
            f"It is optional by design and unset in environments that do not use it yet."
        )


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

    # The origin the *browser* uses, which is not what the backend sees. The
    # frontend proxies /api/* to http://backend:8000, so a redirect URI derived
    # from the incoming request would be the internal Docker hostname — which
    # Google rejects, and rightly so.
    #
    # It is also configuration rather than something to infer from a Host
    # header: the value has to match what is registered in the Google Cloud
    # Console exactly, and a header an attacker controls should never decide
    # where users are sent after authenticating.
    public_base_url: str = "http://localhost:3000"

    # -- Database -----------------------------------------------------------
    database_url: str

    # -- Cache. Never a source of truth. ------------------------------------
    # Optional by design, on the same terms as the Google credentials below.
    # Nothing reads the cache until slice 003, but until slice 002 this was a
    # required field — so a deployment without Redis could not start at all,
    # rather than merely reporting the cache as absent. That put the platform's
    # ability to boot behind a dependency it never called
    # (specs/002-deployment/research.md R1).
    #
    # Unset means "not configured", which readiness reports as such rather than
    # probing. Do not supply a placeholder to fill the blank: the application
    # would believe it has a cache and fail at first use instead of at startup.
    redis_url: str | None = None

    # -- Object storage -----------------------------------------------------
    # Optional on the same terms. Set all four together or none of them; a
    # half-configured client is worse than an absent one.
    s3_endpoint_url: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_bucket: str | None = None
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

    # The two properties below are the sole input to which dependencies the
    # readiness endpoint probes. A dependency that is not configured is
    # reported as `not_configured` — never probed, and never reported healthy,
    # which would make the endpoint claim a result it did not produce.
    # See specs/002-deployment/contracts/readiness.md.

    @property
    def cache_configured(self) -> bool:
        return self.redis_url is not None

    @property
    def object_storage_configured(self) -> bool:
        """All four settings, not any of them.

        A client built from a partial configuration fails at call time with an
        error about credentials rather than about configuration, which sends
        the reader to the wrong place.
        """
        return None not in (
            self.s3_endpoint_url,
            self.s3_access_key,
            self.s3_secret_key,
            self.s3_bucket,
        )


def _secret_fields() -> frozenset[str]:
    """Field names whose values must never appear in an error message.

    Derived from the annotations rather than listed by hand, so a secret added
    later is covered without anyone remembering to update this.
    """
    return frozenset(
        name
        for name, field in Settings.model_fields.items()
        if field.annotation in (SecretStr, SecretStr | None)
    )


def _describe(error: ErrorDetails, secrets: frozenset[str]) -> str:
    """One line per invalid field, with the value withheld when it is a secret.

    Pydantic puts the rejected input in its own message — `input_value='...'` —
    which for SESSION_SECRET means the secret itself is printed by the crash
    that was supposed to protect it (T068).
    """
    field = ".".join(str(part) for part in error["loc"]) or "(root)"
    if field in secrets:
        return f"{field}: {error['type']}"
    return f"{field}: {error['type']} — {error['msg']}"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once.

    Cached so that configuration is read and validated a single time, and so
    tests can clear the cache to substitute a different environment.

    A validation failure is re-raised with the offending values stripped. The
    operator still learns which field is wrong and why — that is the whole point
    of failing at startup (FR-006) — but a rejected secret does not travel into
    the container log on its way out.
    """
    try:
        return Settings()  # values are supplied by the environment
    except ValidationError as exc:
        secrets = _secret_fields()
        details = "\n  ".join(_describe(error, secrets) for error in exc.errors())
        raise RuntimeError(
            f"Invalid configuration ({exc.error_count()} problem(s)):\n  {details}\n"
            "See .env.example for the expected values."
        ) from None  # `from None`: the original exception carries the values
