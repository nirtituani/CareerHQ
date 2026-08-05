"""Redis client.

Used for caching and, later, workflow state. Redis is never a source of truth —
anything lost here must be reconstructible from PostgreSQL.
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from careerhq.config import get_settings


@lru_cache
def get_redis() -> Redis:
    """Return the process-wide Redis client."""
    settings = get_settings()
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def ping() -> None:
    """Raise if Redis is unreachable."""
    await get_redis().ping()
