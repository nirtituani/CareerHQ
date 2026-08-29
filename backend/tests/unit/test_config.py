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
    """The AI settings have usable defaults and require no key (research.md R-008).

    Slice 001 wrote this when nothing set `ANTHROPIC_API_KEY`, so "no key" was
    incidentally true. Slice 003 puts a placeholder in the test environment, so
    the key is now removed explicitly — the property under test is unchanged and
    is now actually being tested rather than assumed.

    It matters because docs/06 §7 commits to the stack running on a clean clone
    before any provider account exists.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # **Removed for exactly the reason the key above is** — and the docstring's own words
    # apply unchanged: the property under test is now actually being tested rather than
    # assumed. Importing `litellm` calls `load_dotenv()`, which walks up from the working
    # directory and injects the developer's `.env` as real environment variables;
    # `_env_file=None` does not stop that. Left in place, this test asserts whatever the
    # machine happens to be configured for, and passes or fails on whether some earlier
    # test imported `litellm` first.
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.llm_provider_model == "anthropic/claude-opus-5"
    # **The committed default, exactly.** It is `BAAI/bge-small-en-v1.5` — the model
    # `backend/Dockerfile` bakes into the image, so a container never downloads weights
    # at run time. This used to assert `sentence-transformers/`, and passed locally for a
    # reason worth knowing: importing `litellm` calls `load_dotenv()`, which walks up from
    # the working directory and injects the developer's `.env` — where `EMBEDDING_MODEL`
    # names a different model — into `os.environ`. `_env_file=None` above does not stop
    # that, because the value arrives as a real environment variable. So the assertion
    # held whenever some earlier test had imported `litellm`, and failed on a clean
    # checkout and in CI, where there is no `.env` to load.
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"
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


# ---------------------------------------------------------------------------
# Slice 003 — the AI provider becomes a real dependency (T008)
# ---------------------------------------------------------------------------


def test_ai_provider_configured_reports_what_is_actually_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T008 — the sole input to whether extraction can run.

    Mirrors `google_oauth_configured` and the two dependency properties slice
    002 added, for the same reason: readiness must follow configuration rather
    than a hardcoded assumption about which environments have what.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-value")

    configured = Settings(_env_file=None)  # type: ignore[call-arg]
    assert configured.ai_provider_configured is True

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    absent = Settings(_env_file=None)  # type: ignore[call-arg]
    assert absent.ai_provider_configured is False, (
        "a missing key must read as unconfigured, not as a broken configuration"
    )


def test_fixture_provider_is_configured_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fixture mode needs no credentials — but must be chosen explicitly.

    The inverse is the dangerous one and is asserted in the test below: absence
    of a key must never *select* fixture mode.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AI_PROVIDER", "fixture")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.ai_provider_configured is True
    assert settings.ai_provider == "fixture"


def test_absent_key_does_not_select_fixture_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """research.md R3 — the failure that would matter most.

    Silently falling back to canned content when no key is set would mean a
    user uploads their real CV and reviews someone else's career history. The
    default provider stays `anthropic` and simply reports itself unconfigured.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.ai_provider == "anthropic"
    assert settings.ai_provider_configured is False


def test_model_resolves_from_task_name_not_from_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """contracts/extraction-seam.md obligation O3.

    Model choice is keyed by task so slice 004 can express docs/08 §3.2.3 as
    configuration — the escalation from Sonnet to Opus on a second failed
    revision is a different task name, not a branch inside workflow code.
    Asserted now, while the seam has one caller and is cheap to change.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LLM_MODEL_CV_EXTRACTION", "anthropic/claude-sonnet-5")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.model_for_task("cv_extraction") == "anthropic/claude-sonnet-5"

    # An unknown task falls back to the default model rather than raising: a new
    # task name should work before someone remembers to configure it.
    assert settings.model_for_task("some_future_task") == settings.llm_provider_model


def test_match_analysis_does_not_fall_through_to_the_opus_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slice 004 T002 — the fallback is the expensive failure, not a missing key.

    `model_for_task` deliberately falls back to `llm_provider_model` rather than
    raising, so a new task name works before anyone configures it (O3). That
    kindness has a price: `llm_provider_model` is **Opus**, so a task with no
    entry runs at roughly 2.5x Sonnet's cost, silently, with no quality gain and
    nothing in the output to show for it.

    This is not hypothetical. The same fallback already caught CV extraction
    once, and `research.md` R8 puts match analysis at $0.065 per job on Opus
    against $0.022 on Sonnet.

    The second assertion is the one that matters. Asserting only the model
    string would still pass if someone changed `llm_provider_model` to Sonnet —
    the entry would then be redundant rather than protective, and the next
    change to the default would silently re-arm the trap.
    """
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("LLM_MODEL_MATCH_ANALYSIS", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.model_for_task("match_analysis") == "anthropic/claude-sonnet-5"
    assert settings.model_for_task("match_analysis") != settings.llm_provider_model
