"""Database engine, session factory, and the request-scoped session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from careerhq.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine.

    ``pool_pre_ping`` costs one cheap round trip per checkout and avoids handing
    out connections that a restarted database has already closed — the usual
    cause of a spurious failure on the first request after a container restart.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that is closed after the request.

    The session is not committed here. Committing is the caller's decision, so
    that a use case spanning several repository calls remains one transaction.
    """
    async with get_session_factory()() as session:
        yield session
