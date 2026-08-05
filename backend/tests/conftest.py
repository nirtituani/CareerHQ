"""Shared test fixtures.

Tests run against the real application object over an in-process ASGI
transport, so routing, middleware, dependency overrides, and response encoding
are all exercised for real. Only the network is removed.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest

# Set before careerhq.config is imported anywhere: Settings reads the
# environment at construction, and several fields are deliberately required.
TEST_ENV: dict[str, str] = {
    "ENVIRONMENT": "local",
    "LOG_LEVEL": "WARNING",
    "DATABASE_URL": "postgresql+psycopg://careerhq:careerhq@localhost:5432/careerhq_test",
    "REDIS_URL": "redis://localhost:6379/1",
    "S3_ENDPOINT_URL": "http://localhost:9000",
    "S3_ACCESS_KEY": "test-access-key",
    "S3_SECRET_KEY": "test-secret-key",
    "S3_BUCKET": "careerhq-test",
    "SESSION_SECRET": "test-session-secret-not-used-outside-tests",
}
for _key, _value in TEST_ENV.items():
    os.environ.setdefault(_key, _value)

from careerhq.config import Settings, get_settings  # noqa: E402
from careerhq.main import create_app  # noqa: E402


@pytest.fixture
def settings() -> Iterator[Settings]:
    """Fresh settings built from the test environment."""
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def app(settings: Settings):  # type: ignore[no-untyped-def]
    """A real application instance wired with test settings."""
    return create_app(settings)


@pytest.fixture
async def client(app) -> AsyncIterator[object]:  # type: ignore[no-untyped-def]
    """An HTTP client that speaks to the app in process, without a socket."""
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
