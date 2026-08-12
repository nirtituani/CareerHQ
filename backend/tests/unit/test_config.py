"""Configuration tests (T021).

A missing required value must stop the process at startup with a message naming
the field (FR-006). The failure mode this guards against is a container that
starts happily and then fails on the first request that needs the value — at
which point the cause is several layers away from the symptom.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from careerhq.config import DependencyNotConfiguredError, Settings, get_settings
from careerhq.infrastructure.redis import get_redis
from careerhq.infrastructure.storage import get_s3_client
from tests.conftest import TEST_ENV

# Only these two. The cache and object-storage settings were required until
# slice 002: nothing uses them yet, but a missing value stopped the process at
# import, so a deployment without them could not start at all — not merely
# report them unhealthy (specs/002-deployment/research.md R1).
#
# DATABASE_URL and SESSION_SECRET stay required because no environment can run
# without them. Relaxing SESSION_SECRET in particular would undo a T068
# protection: sessions signed with nothing are forgeable by anyone.
REQUIRED_FIELDS = (
    "database_url",
    "session_secret",
)

#: Set together or not at all. A half-configured client is worse than none.
OPTIONAL_DEPENDENCY_FIELDS = (
    "REDIS_URL",
    "S3_ENDPOINT_URL",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
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


@pytest.mark.parametrize("empty_value", ["", "   ", "too-short"])
def test_empty_or_weak_session_secret_is_rejected(
    monkeypatch: pytest.MonkeyPatch, empty_value: str
) -> None:
    """Found during quickstart verification (T030).

    `.env.example` ships SESSION_SECRET present but empty. "Required" alone
    accepts an empty string, so a developer who copies the example without
    filling it in would run with an empty token-signing secret — sessions
    forgeable by anyone. A minimum length turns that into a startup failure.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("SESSION_SECRET", empty_value)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "session_secret" in str(exc_info.value)


@pytest.mark.parametrize("weak_value", ["short-secret-value-abc", "hunter2"])
def test_startup_failure_does_not_echo_the_secret(
    monkeypatch: pytest.MonkeyPatch, weak_value: str
) -> None:
    """Found during the security review (T068).

    Pydantic puts the rejected input in the error text — `input_value='...'` —
    so a SESSION_SECRET that is merely too short lands in the container startup
    log in full. `get_settings()` is what the container calls, so that is where
    the message is rebuilt from field names and error types alone.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("SESSION_SECRET", weak_value)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError) as exc_info:
        get_settings()

    message = str(exc_info.value)
    assert "session_secret" in message, "the operator still needs to know which field"
    assert weak_value not in message, "the rejected secret was echoed"

    get_settings.cache_clear()


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


def test_platform_starts_without_cache_or_object_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T004 — the deployed environment runs Postgres only.

    Until slice 002 these were required fields, so a deployment without them
    raised at import and never reached an endpoint. Readiness reporting was
    downstream of a problem one layer earlier.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    for key in OPTIONAL_DEPENDENCY_FIELDS:
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.redis_url is None
    assert settings.s3_endpoint_url is None


def test_configured_properties_report_what_is_actually_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T005 — the sole input to which dependencies get probed.

    Mirrors `google_oauth_configured`, which already exists for the same reason.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)

    configured = Settings(_env_file=None)  # type: ignore[call-arg]
    assert configured.cache_configured is True
    assert configured.object_storage_configured is True

    for key in OPTIONAL_DEPENDENCY_FIELDS:
        monkeypatch.delenv(key, raising=False)

    absent = Settings(_env_file=None)  # type: ignore[call-arg]
    assert absent.cache_configured is False
    assert absent.object_storage_configured is False


def test_database_and_session_secret_are_still_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T006 — making two dependencies optional must not relax the other two.

    A missing SESSION_SECRET has to keep stopping the process. The failure this
    guards against is not a crash; it is a container that starts happily and
    signs session tokens with nothing.
    """
    for key in TEST_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in TEST_ENV.items():
        if key != "SESSION_SECRET":
            monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    message = str(exc_info.value)
    assert "session_secret" in message
    assert TEST_ENV["SESSION_SECRET"] not in message, "the rejected secret was echoed"


def test_accessors_fail_loudly_when_their_dependency_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T010 — the failure moved from startup to first use; it did not vanish.

    Optional configuration gives up the fail-fast property slice 001 built
    deliberately. This is the mitigation: asking for a client that is not
    configured raises something that names the problem, rather than
    constructing a client from None and failing somewhere unrelated.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    for key in OPTIONAL_DEPENDENCY_FIELDS:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    get_redis.cache_clear()
    get_s3_client.cache_clear()

    with pytest.raises(DependencyNotConfiguredError) as redis_error:
        get_redis()
    assert "REDIS_URL" in str(redis_error.value)

    with pytest.raises(DependencyNotConfiguredError) as storage_error:
        get_s3_client()
    assert "S3_" in str(storage_error.value)

    get_settings.cache_clear()
    get_redis.cache_clear()
    get_s3_client.cache_clear()


def test_secrets_are_not_exposed_by_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """A settings object must not leak credentials into a log line."""
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert TEST_ENV["SESSION_SECRET"] not in repr(settings)
    assert TEST_ENV["S3_SECRET_KEY"] not in repr(settings)
