"""Health endpoint tests (T018, T019, T020).

Readiness reports each dependency by name so an outage is diagnosable from the
response alone (FR-002, SC-008). The probes are overridden per test rather than
requiring a real Postgres, Redis, and MinIO — what is under test is the
aggregation and status-code logic, not the drivers.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from careerhq.api.routes import health

DEPENDENCIES = ("database", "cache", "object_storage", "ai_provider")


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    """T018: liveness answers without touching any dependency."""
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


async def test_health_echoes_request_id(client: httpx.AsyncClient) -> None:
    """Every response carries a correlation id (FR-008)."""
    response = await client.get("/api/health", headers={"X-Request-ID": "known-id"})

    assert response.headers["X-Request-ID"] == "known-id"


async def test_readiness_names_every_dependency(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T019: all reachable → 200, and each dependency is reported individually."""
    for name in DEPENDENCIES:
        monkeypatch.setattr(health, f"probe_{name}", _reachable)

    response = await client.get("/api/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["dependencies"]) == set(DEPENDENCIES)
    for name in DEPENDENCIES:
        assert body["dependencies"][name]["status"] == "ok"
        assert body["dependencies"][name]["latency_ms"] >= 0


@pytest.mark.parametrize("failing", DEPENDENCIES)
async def test_readiness_names_the_failing_dependency(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """T020: parameterized across all three — SC-008 says 100% of outage cases.

    Testing one dependency would leave the other two unproven, which is exactly
    the gap that lets a probe silently report healthy when it is not.
    """
    for name in DEPENDENCIES:
        monkeypatch.setattr(
            health, f"probe_{name}", _unreachable if name == failing else _reachable
        )

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"

    # The failing one is named, with a reason.
    assert body["dependencies"][failing]["status"] == "error"
    assert body["dependencies"][failing]["error"]

    # The healthy ones are still reported, so the response localises the fault.
    for name in DEPENDENCIES:
        if name != failing:
            assert body["dependencies"][name]["status"] == "ok"


async def test_readiness_reports_a_hung_dependency_as_failed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe that never returns must not hang the health check."""
    monkeypatch.setattr(health, "PROBE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(health, "probe_database", _hangs)
    monkeypatch.setattr(health, "probe_cache", _reachable)
    monkeypatch.setattr(health, "probe_object_storage", _reachable)

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"]["database"]["status"] == "error"


async def test_unconfigured_dependencies_are_reported_as_such_not_as_healthy(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T012: the deployed environment runs Postgres only.

    A dependency that was never deployed must not be reported `ok` — that would
    turn the health check green by claiming a result no probe produced. Nor may
    it fail the check: it is absent by design, not broken.
    """
    monkeypatch.setattr(health, "probe_database", _reachable)
    _configure(monkeypatch, cache=False, object_storage=False)

    response = await client.get("/api/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["database"]["status"] == "ok"
    for absent in ("cache", "object_storage"):
        assert body["dependencies"][absent]["status"] == "not_configured"
        assert "latency_ms" not in body["dependencies"][absent]


async def test_absent_dependency_neither_causes_nor_masks_a_real_failure(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T013 — the test this slice most needs.

    Two mistakes are possible once probing follows configuration, and they pull
    in opposite directions: reporting an absent dependency as failed would
    block every deployment, and excluding absent ones so loosely that a real
    failure stops counting would make the endpoint useless. One response has to
    get both right at once.
    """
    monkeypatch.setattr(health, "probe_database", _unreachable)
    _configure(monkeypatch, cache=False, object_storage=False)

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded", "a real failure must still fail the check"
    assert body["dependencies"]["database"]["status"] == "error"
    assert body["dependencies"]["cache"]["status"] == "not_configured"


async def test_every_dependency_key_is_present_whatever_the_configuration(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T015: a consumer never distinguishes "key missing" from "dependency missing".

    Omitting absent dependencies would be the tidier response and the worse
    contract — a reader could not tell "not deployed" from "we forgot to check".
    """
    monkeypatch.setattr(health, "probe_database", _reachable)
    _configure(monkeypatch, cache=False, object_storage=False)

    body = (await client.get("/api/health/ready")).json()

    assert set(body["dependencies"]) == set(DEPENDENCIES)


async def test_failure_discloses_the_kind_and_not_the_detail(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T014: this endpoint is unauthenticated (T068).

    A real psycopg failure reads `connection to server at "172.19.0.4", port
    5432 failed: FATAL: password authentication failed for user "careerhq"`.
    The caller gets the exception class; the operator gets the rest, in the log.
    """
    monkeypatch.setattr(health, "probe_database", _unreachable_with_internals)
    _configure(monkeypatch, cache=False, object_storage=False)

    body = (await client.get("/api/health/ready")).json()
    reported = body["dependencies"]["database"]["error"]

    assert reported == "OperationalError"
    for leaked in ("172.19.0.4", "5432", "careerhq", "password"):
        assert leaked not in reported


# -- helpers ----------------------------------------------------------------


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cache: bool,
    object_storage: bool,
    ai_provider: bool = True,
) -> None:
    """Present a settings object reporting the dependencies as (un)configured."""
    real = health.get_settings()

    class _Configured:
        cache_configured = cache
        object_storage_configured = object_storage
        ai_provider_configured = ai_provider

        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

    monkeypatch.setattr(health, "get_settings", _Configured)


# -- probe doubles ----------------------------------------------------------


async def _reachable() -> None:
    return None


async def _unreachable() -> None:
    raise ConnectionRefusedError("Connection refused")


async def _unreachable_with_internals() -> None:
    """A driver failure shaped like the real one, internal addresses included.

    SQLAlchemy wraps the driver's exception rather than raising its own message,
    so the double has to be built the same way — the point of the test is what
    happens to `orig`.
    """
    raise OperationalError(
        "SELECT 1",
        {},
        Exception(
            'connection to server at "172.19.0.4", port 5432 failed: '
            'FATAL: password authentication failed for user "careerhq"'
        ),
    )


async def _hangs() -> None:
    import asyncio

    await asyncio.sleep(10)


# ---------------------------------------------------------------------------
# Slice 003 — the AI provider joins the report (T009)
# ---------------------------------------------------------------------------


async def test_ai_provider_absent_is_reported_not_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T009 — the same three-state contract slice 002 established.

    `not_configured` neither fails the check nor masks a real failure. That
    property was the most important thing slice 002's readiness work proved,
    and adding a fourth dependency is exactly the change that could quietly
    break it.
    """
    monkeypatch.setattr(health, "probe_database", _reachable)
    _configure(monkeypatch, cache=False, object_storage=False, ai_provider=False)

    response = await client.get("/api/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["ai_provider"]["status"] == "not_configured"
    assert "latency_ms" not in body["dependencies"]["ai_provider"]


async def test_absent_ai_provider_does_not_mask_a_real_failure(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The T013 property, re-proved for the dependency added this slice.

    A new `not_configured` entry must not become a way for a genuine outage to
    stop counting.
    """
    monkeypatch.setattr(health, "probe_database", _unreachable)
    _configure(monkeypatch, cache=False, object_storage=False, ai_provider=False)

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["database"]["status"] == "error"
    assert body["dependencies"]["ai_provider"]["status"] == "not_configured"
