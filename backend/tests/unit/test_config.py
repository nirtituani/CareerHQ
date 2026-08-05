"""Configuration tests (T021).

A missing required value must stop the process at startup with a message naming
the field (FR-006). The failure mode this guards against is a container that
starts happily and then fails on the first request that needs the value — at
which point the cause is several layers away from the symptom.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from careerhq.config import Settings
from tests.conftest import TEST_ENV

REQUIRED_FIELDS = (
    "database_url",
    "redis_url",
    "s3_endpoint_url",
    "s3_access_key",
    "s3_secret_key",
    "s3_bucket",
    "session_secret",
)


@pytest.mark.parametrize("missing", REQUIRED_FIELDS)
def test_missing_required_value_fails_and_names_the_field(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for key in TEST_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in TEST_ENV.items():
        if key.lower() != missing:
            monkeypatch.setenv(key, value)

    # Ignore any .env on the developer's machine — this asserts on the
    # environment, and a local file would mask the missing value.
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert missing in str(exc_info.value)


def test_valid_environment_constructs(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment == "local"
    assert settings.session_ttl_days == 7
    assert settings.is_production is False


def test_google_oauth_is_optional_so_the_platform_starts_without_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sign-in cannot work without it, but health checks must still be verifiable."""
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.google_oauth_configured is False


def test_ai_configuration_seam_has_working_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """No AI code exists yet; the settings it will read do (research.md R-008)."""
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.llm_provider_model == "anthropic/claude-opus-5"
    assert settings.embedding_model.startswith("sentence-transformers/")
    assert settings.anthropic_api_key is None


def test_secrets_are_not_exposed_by_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """A settings object must not leak credentials into a log line."""
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert TEST_ENV["SESSION_SECRET"] not in repr(settings)
    assert TEST_ENV["S3_SECRET_KEY"] not in repr(settings)
