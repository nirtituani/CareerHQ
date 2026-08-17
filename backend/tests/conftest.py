"""Shared test fixtures.

Tests run against the real application object over an in-process ASGI
transport, so routing, middleware, dependency overrides, and response encoding
are all exercised for real. Only the network is removed.

Database tests run against a real PostgreSQL — the one Docker Compose already
provides — in a dedicated `careerhq_test` database. A mock would not have
UNIQUE constraints or transaction isolation, and those are precisely what the
provisioning tests are checking.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio

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
    # Present so the OAuth client constructs. No network call is made: the
    # endpoints are configured explicitly rather than discovered, and the token
    # exchange itself is overridden at the dependency boundary.
    "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    # Present for the same reason as the Google credentials above: the provider
    # must read as configured so readiness reports it like any other dependency.
    # No network call is made anywhere in the suite — the completion seam is
    # overridden at the dependency boundary, which is what FR-027 requires and
    # what T049 verifies by unsetting the real key and watching it not matter.
    "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
}
for _key, _value in TEST_ENV.items():
    os.environ.setdefault(_key, _value)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from careerhq.config import Settings, get_settings  # noqa: E402
from careerhq.infrastructure.database import Base  # noqa: E402
from careerhq.main import create_app  # noqa: E402

#: Tables cleared between tests, in dependency order (children first).
_TABLES = ("professional_profiles", "users")


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


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[object]:  # type: ignore[no-untyped-def]
    """An HTTP client that speaks to the app in process, without a socket."""
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


async def _ensure_test_database(url: str) -> None:
    """Create the test database if it does not exist.

    Connects to the `postgres` maintenance database because a database cannot
    be created from inside itself, and in AUTOCOMMIT because PostgreSQL forbids
    CREATE DATABASE inside a transaction.
    """
    database_name = url.rsplit("/", 1)[-1]
    admin_url = url.rsplit("/", 1)[0] + "/postgres"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Session-wide engine against a prepared test database.

    Skips the whole database suite when PostgreSQL is unreachable, so the unit
    tests still run for someone who has not started Docker Compose.
    """
    url = TEST_ENV["DATABASE_URL"]
    try:
        await _ensure_test_database(url)
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable ({exc.__class__.__name__}); skipping database tests")

    test_engine = create_async_engine(url, pool_pre_ping=True)
    async with test_engine.begin() as connection:
        # Matches migration 0001; the schema itself comes from the models.
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Dropped first, because `create_all` skips tables that already exist
        # rather than reconciling them. Without this the test database keeps
        # whatever shape it had when it was first built, and any test that
        # reads the *schema* silently checks a stale one. That is not
        # hypothetical: T067 asserts no `rejected` column exists anywhere
        # (FR-016, a release blocker), and it passed against a deliberately
        # added column until this line existed.
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield test_engine

    await test_engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A factory producing independent sessions.

    Concurrency tests need genuinely separate sessions that each commit, so
    they cannot share one rolled-back transaction. Tables are truncated
    afterwards instead.
    """
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory

    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(_TABLES)} CASCADE"))


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A single session for tests that do not need concurrency."""
    async with session_factory() as session:
        yield session
