"""Redis client.

Used for caching and, later, workflow state. Redis is never a source of truth —
anything lost here must be reconstructible from PostgreSQL.
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from careerhq.config import DependencyNotConfiguredError, get_settings


@lru_cache
def get_redis() -> Redis:
    """Return the process-wide Redis client.

    Raises `DependencyNotConfiguredError` when the cache is not configured.
    `REDIS_URL` is optional, so absence is a legitimate deployment state rather
    than a fault — but a caller that asks for a client anyway has made a
    mistake, and it should say so here rather than fail later on `None`.
    """
    settings = get_settings()
    if settings.redis_url is None:
        raise DependencyNotConfiguredError("Cache", "REDIS_URL")
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def ping() -> None:
    """Raise if Redis is unreachable."""
    await get_redis().ping()
