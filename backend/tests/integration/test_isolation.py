"""Cross-user data isolation (T035).

SC-005 and FR-015: one user's session must never reach another user's data.

The design that makes this hold is that no endpoint accepts a user or profile
id from the client — ownership is always derived from the session. These tests
assert the property from the outside, so a future endpoint that takes an id
from a query parameter would fail here.
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.provision_user import provision_user
from careerhq.domain.models import User
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

ALICE = {"sub": "google-alice", "email": "alice@example.com", "name": "Alice"}
BOB = {"sub": "google-bob", "email": "bob@example.com", "name": "Bob"}


def _as(client: httpx.AsyncClient, token: str) -> httpx.AsyncClient:
    """Return the client carrying `token` as its session cookie.

    Set on the client rather than per request: httpx deprecated per-request
    cookies because the persistence semantics were ambiguous.
    """
    client.cookies.set(SESSION_COOKIE, token)
    return client


async def _two_users(session: AsyncSession) -> tuple[User, User]:
    alice = await provision_user(session, ALICE)
    bob = await provision_user(session, BOB)
    await session.commit()
    return alice, bob


async def test_each_session_sees_only_its_own_identity(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    alice, bob = await _two_users(db_session)

    as_alice = await _as(client, create_session_token(str(alice.id))).get("/api/auth/me")
    as_bob = await _as(client, create_session_token(str(bob.id))).get("/api/auth/me")

    assert as_alice.json()["email"] == ALICE["email"]
    assert as_bob.json()["email"] == BOB["email"]
    assert as_alice.json()["id"] != as_bob.json()["id"]


async def test_each_session_sees_only_its_own_profile(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    alice, bob = await _two_users(db_session)

    alice_profile = await _as(client, create_session_token(str(alice.id))).get("/api/profile")
    bob_profile = await _as(client, create_session_token(str(bob.id))).get("/api/profile")

    assert alice_profile.status_code == 200
    assert bob_profile.status_code == 200

    assert alice_profile.json()["user_id"] == str(alice.id)
    assert bob_profile.json()["user_id"] == str(bob.id)
    assert alice_profile.json()["id"] != bob_profile.json()["id"]


async def test_no_endpoint_accepts_a_client_supplied_identity(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Ownership comes from the session, never from the request.

    Passing another user's id as a parameter must be ignored, not honoured —
    this is the attack that a permission check placed in the wrong layer misses.
    """
    alice, bob = await _two_users(db_session)
    scoped = _as(client, create_session_token(str(alice.id)))

    for params in ({"user_id": str(bob.id)}, {"id": str(bob.id)}, {"profile_id": str(bob.id)}):
        response = await scoped.get("/api/profile", params=params)
        assert response.status_code == 200
        assert response.json()["user_id"] == str(alice.id), (
            f"query parameter {params} leaked another user's profile"
        )
