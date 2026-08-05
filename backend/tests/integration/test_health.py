"""Health endpoint tests (T018, T019, T020).

Readiness reports each dependency by name so an outage is diagnosable from the
response alone (FR-002, SC-008). The probes are overridden per test rather than
requiring a real Postgres, Redis, and MinIO — what is under test is the
aggregation and status-code logic, not the drivers.
"""

from __future__ import annotations

import httpx
import pytest

from careerhq.api.routes import health

DEPENDENCIES = ("database", "cache", "object_storage")


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


# -- probe doubles ----------------------------------------------------------


async def _reachable() -> None:
    return None


async def _unreachable() -> None:
    raise ConnectionRefusedError("Connection refused")


async def _hangs() -> None:
    import asyncio

    await asyncio.sleep(10)
