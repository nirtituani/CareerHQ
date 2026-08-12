"""Health endpoints.

Two endpoints with different jobs:

``/api/health`` is liveness. It touches nothing, so a slow dependency cannot
make the container look dead and trigger a restart loop.

``/api/health/ready`` is readiness. It probes every dependency concurrently and
reports each **by name**, so an outage is diagnosable from the response alone
rather than from correlating logs (FR-002, SC-008).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from careerhq.config import get_settings
from careerhq.infrastructure import redis as redis_infra
from careerhq.infrastructure import storage
from careerhq.infrastructure.database import get_engine

router = APIRouter(tags=["health"])
logger = logging.getLogger("careerhq.health")

#: A probe that has not answered within this many seconds is reported as failed.
#: Without it, one hung dependency would hang the health check itself — and a
#: health check that never returns is worse than one that returns bad news.
PROBE_TIMEOUT_SECONDS = 2.0


def _version() -> str:
    try:
        return package_version("careerhq")
    except PackageNotFoundError:  # pragma: no cover - only when not installed
        return "0.0.0"


# -- probes -----------------------------------------------------------------
# Each raises on failure and returns None on success. They are module-level so
# that tests can substitute them without a real Postgres, Redis, and MinIO.


async def probe_database() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def probe_cache() -> None:
    await redis_infra.ping()


async def probe_object_storage() -> None:
    await storage.head_bucket()


async def _run_probe(name: str, probe: Callable[[], Awaitable[None]]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        return {
            "status": "error",
            "error": f"Timed out after {PROBE_TIMEOUT_SECONDS}s",
        }
    except Exception as exc:
        # The driver's message is diagnostic gold and a disclosure risk at once:
        # a real PostgreSQL auth failure reads `connection to server at
        # "172.19.0.4", port 5432 failed: FATAL: password authentication failed
        # for user "careerhq"`. This endpoint is unauthenticated, so the caller
        # gets the kind of failure and the operator gets the rest (T068).
        logger.warning("dependency probe failed", extra={"dependency": name, "error": str(exc)})
        return {"status": "error", "error": exc.__class__.__name__}

    return {
        "status": "ok",
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


@router.get("/health", summary="Liveness")
async def health() -> dict[str, str]:
    """Report that the process is up. Touches no dependency."""
    return {"status": "ok", "version": _version()}


#: Reported for a dependency this environment does not configure. Deliberately
#: distinct from both neighbours: not `ok`, because no probe ran and the
#: endpoint must never claim a result it did not produce; not `error`, because
#: absence by design is not a fault. Omitting the entry entirely was the other
#: candidate and is worse — a reader could not tell "not deployed" from "we
#: forgot to check" (specs/002-deployment/contracts/readiness.md, FR-006).
NOT_CONFIGURED = "not_configured"


@router.get("/health/ready", summary="Readiness")
async def readiness(response: Response) -> dict[str, Any]:
    """Probe every *configured* dependency concurrently and report each by name.

    The probe set follows configuration rather than being fixed, because
    environments legitimately differ: the deployed one runs Postgres alone,
    while local development runs all three. A hardcoded set would report the
    two absent dependencies as failed, and since the platform health check
    points at this endpoint, that would block every deployment.
    """
    # Resolved per request rather than at import so that a test substituting a
    # probe or a configuration is honoured.
    settings = get_settings()
    probes: dict[str, Callable[[], Awaitable[None]] | None] = {
        "database": probe_database,
        "cache": probe_cache if settings.cache_configured else None,
        "object_storage": (probe_object_storage if settings.object_storage_configured else None),
    }

    checked = {name: probe for name, probe in probes.items() if probe is not None}
    results = await asyncio.gather(*(_run_probe(name, probe) for name, probe in checked.items()))
    probed = dict(zip(checked, results, strict=True))

    # Rebuilt in declaration order so the response reads identically however
    # much of the stack an environment happens to run.
    dependencies: dict[str, Any] = {
        name: probed.get(name, {"status": NOT_CONFIGURED}) for name in probes
    }

    # Checked dependencies only. An unconfigured one can neither fail the
    # check nor mask a failure in one that was actually probed.
    healthy = all(dependencies[name]["status"] == "ok" for name in checked)
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if healthy else "degraded",
        "version": _version(),
        "dependencies": dependencies,
    }
