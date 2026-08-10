"""Response header and error-body hardening (T068).

Two leaks found during the security review, both on paths that are reachable
without authentication:

* the readiness body echoed the driver's exception text, which for a real
  PostgreSQL failure reads
  ``connection to server at "172.19.0.4", port 5432 failed: FATAL: password
  authentication failed for user "careerhq"`` — internal address, port, and
  database username handed to anyone who can reach ``/api/health/ready``;
* no response carried the headers that stop a browser from re-interpreting it.

The detail is still logged. It is diagnostic information for the operator, not
for the caller.
"""

from __future__ import annotations

import httpx
import pytest

from careerhq.api.routes import health

#: Stands in for a driver message that names internal infrastructure.
LEAKY_MESSAGE = (
    'connection to server at "172.19.0.4", port 5432 failed: '
    'FATAL:  password authentication failed for user "careerhq"'
)

#: Substrings that must never reach an unauthenticated caller.
INTERNAL_MARKERS = ("172.19.0.4", "5432", "careerhq", "password")


async def _reachable() -> None:
    return None


async def _leaks_internals() -> None:
    raise ConnectionRefusedError(LEAKY_MESSAGE)


async def test_readiness_error_does_not_leak_internals(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failing dependency is still named; the driver's message is not."""
    monkeypatch.setattr(health, "probe_database", _leaks_internals)
    monkeypatch.setattr(health, "probe_cache", _reachable)
    monkeypatch.setattr(health, "probe_object_storage", _reachable)

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()

    # The diagnosis the endpoint exists to provide survives.
    assert body["dependencies"]["database"]["status"] == "error"
    assert body["dependencies"]["database"]["error"]

    raw = response.text
    for marker in INTERNAL_MARKERS:
        assert marker not in raw, f"readiness body leaked {marker!r}"


async def test_readiness_failure_detail_still_reaches_the_log(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sanitising the response must not blind the operator."""
    monkeypatch.setattr(health, "probe_database", _leaks_internals)
    monkeypatch.setattr(health, "probe_cache", _reachable)
    monkeypatch.setattr(health, "probe_object_storage", _reachable)

    with caplog.at_level("WARNING", logger="careerhq.health"):
        await client.get("/api/health/ready")

    assert any(
        LEAKY_MESSAGE in record.getMessage() or LEAKY_MESSAGE in str(record.__dict__)
        for record in caplog.records
    )


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
    ],
)
async def test_security_headers_are_present(
    client: httpx.AsyncClient, header: str, expected: str
) -> None:
    """Every response carries them, including error responses."""
    response = await client.get("/api/health")

    assert response.headers[header] == expected


async def test_security_headers_are_present_on_errors(client: httpx.AsyncClient) -> None:
    """A 401 is exactly the response an attacker is most likely to be probing."""
    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_hsts_is_absent_locally(client: httpx.AsyncClient) -> None:
    """Sending HSTS over plain-HTTP localhost would pin a scheme that does not work."""
    response = await client.get("/api/health")

    assert "Strict-Transport-Security" not in response.headers
