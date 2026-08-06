"""Authentication tests (T034, T036, T037, T038).

The Google token exchange is substituted at the dependency boundary, so the
callback route, provisioning, cookie issuance, and redirect are all exercised
for real — only the network call to Google is removed (research.md R-009).
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.api import deps
from careerhq.domain.models import User
from careerhq.domain.schemas import GoogleClaims
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

PROTECTED = ("/api/auth/me", "/api/profile")

#: Routes reachable without a session. Everything else must return 401.
PUBLIC_PREFIXES = ("/api/health", "/api/auth/google", "/api/docs", "/api/openapi.json")


def _as(client: httpx.AsyncClient, token: str) -> httpx.AsyncClient:
    """Return the client carrying `token` as its session cookie.

    Set on the client rather than per request: httpx deprecated per-request
    cookies because the persistence semantics were ambiguous.
    """
    client.cookies.set(SESSION_COOKIE, token)
    return client


# -- unauthenticated access (T034, FR-014, SC-003) --------------------------


@pytest.mark.parametrize("path", PROTECTED)
async def test_no_cookie_is_rejected(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
async def test_tampered_cookie_is_rejected(client: httpx.AsyncClient, path: str) -> None:
    """A forged signature must not be accepted."""
    token = create_session_token("0198f2c1-0000-0000-0000-000000000000")
    response = await _as(client, token[:-4] + "AAAA").get(path)
    assert response.status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
async def test_expired_cookie_is_rejected(client: httpx.AsyncClient, path: str) -> None:
    token = create_session_token("0198f2c1-0000-0000-0000-000000000000", ttl_days=-1)
    response = await _as(client, token).get(path)
    assert response.status_code == 401


async def test_cookie_for_a_deleted_account_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A validly-signed token whose subject no longer exists is not an error page.

    Edge case from the spec: the session is simply treated as unauthenticated.
    """
    token = create_session_token("0198f2c1-dead-dead-dead-000000000000")
    response = await _as(client, token).get("/api/auth/me")
    assert response.status_code == 401


async def test_every_non_public_route_requires_a_session(client: httpx.AsyncClient, app) -> None:  # type: ignore[no-untyped-def]
    """SC-003 says 100% of protected endpoints, so enumerate rather than sample.

    This is what catches an endpoint added later without authentication: it
    fails here instead of shipping open.
    """
    unprotected: list[str] = []

    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if not path.startswith("/api") or path.startswith(PUBLIC_PREFIXES):
            continue
        if "{" in path:  # no parameterised routes yet; revisit when there are
            continue

        for method in methods & {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            response = await client.request(method, path)
            if response.status_code != 401:
                unprotected.append(f"{method} {path} -> {response.status_code}")

    assert not unprotected, f"routes reachable without a session: {unprotected}"


# -- sign-in flow (T037, T038) ----------------------------------------------


async def test_login_redirects_to_google(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/google/login", follow_redirects=False)

    assert response.status_code in (302, 307)
    assert "accounts.google.com" in response.headers["location"]


async def test_login_sends_google_the_browser_facing_redirect_uri(
    client: httpx.AsyncClient,
) -> None:
    """Found during the browser walkthrough (T056).

    The redirect URI must be the origin the *browser* uses. Deriving it from
    the incoming request yields `http://backend:8000` — the internal Docker
    hostname the frontend proxies to — which Google rejects with
    `Error 400: invalid_request`. It must come from configuration, which is
    also what makes it match the Cloud Console entry exactly.
    """
    response = await client.get("/api/auth/google/login", follow_redirects=False)
    location = response.headers["location"]

    assert "redirect_uri=http%3A%2F%2Flocalhost%3A3000%2Fapi%2Fauth%2Fgoogle%2Fcallback" in location
    assert "backend%3A8000" not in location


async def test_login_rejects_an_absolute_next_url(client: httpx.AsyncClient) -> None:
    """An open redirect would send a freshly-authenticated user to an attacker."""
    response = await client.get(
        "/api/auth/google/login",
        params={"next": "https://evil.example.com/steal"},
        follow_redirects=False,
    )

    assert "evil.example.com" not in response.headers.get("location", "")


async def test_callback_signs_in_and_sets_an_httponly_cookie(
    client: httpx.AsyncClient,
    app,
    db_session: AsyncSession,  # type: ignore[no-untyped-def]
) -> None:
    """The happy path, with only Google's network call substituted."""
    app.dependency_overrides[deps.get_verified_google_claims] = lambda: GoogleClaims(
        sub="google-subject-abc",
        email="nir@example.com",
        name="Nir Tituani",
        picture=None,
    )

    response = await client.get("/api/auth/google/callback", follow_redirects=False)

    assert response.status_code in (302, 307)
    set_cookie = response.headers["set-cookie"].lower()
    assert SESSION_COOKIE in set_cookie
    assert "httponly" in set_cookie  # FR-016: not readable by browser scripts
    assert "samesite=lax" in set_cookie

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 1

    app.dependency_overrides.clear()


async def test_callback_with_denied_consent_creates_no_account(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T037: the user cancels at Google's prompt."""
    response = await client.get(
        "/api/auth/google/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert "error=access_denied" in response.headers["location"]
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 0


async def test_callback_without_a_code_is_rejected(client: httpx.AsyncClient) -> None:
    """T038: no authorization code means there is nothing to exchange."""
    response = await client.get("/api/auth/google/callback", follow_redirects=False)
    assert response.status_code == 400


# -- session lifecycle (T036) ------------------------------------------------


async def test_me_returns_the_signed_in_identity(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    from careerhq.application.provision_user import provision_user

    user = await provision_user(
        db_session, {"sub": "google-subject-me", "email": "me@example.com", "name": "Me"}
    )
    await db_session.commit()

    response = await _as(client, create_session_token(str(user.id))).get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


async def test_logout_clears_the_cookie_and_is_idempotent(client: httpx.AsyncClient) -> None:
    """Signing out twice must not be an error — the UI needs no special case."""
    first = await client.post("/api/auth/logout")
    assert first.status_code == 204
    assert 'careerhq_session=""' in first.headers.get(
        "set-cookie", ""
    ) or "Max-Age=0" in first.headers.get("set-cookie", "")

    second = await client.post("/api/auth/logout")
    assert second.status_code == 204
