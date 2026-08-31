"""First-sign-in provisioning (T031, T032, T033).

Constitution Principle I: each user owns exactly one Professional Profile. These
tests exist because that invariant is easy to state and easy to violate — a
check-then-insert in application code loses the race the first time two requests
arrive together.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.provision_user import provision_user
from careerhq.domain.models import ProfessionalProfile, User

CLAIMS = {
    "sub": "google-subject-12345",
    "email": "nir@example.com",
    "name": "Nir Tituani",
    "picture": "https://example.com/avatar.png",
}


async def _counts(session: AsyncSession) -> tuple[int, int]:
    users = await session.scalar(select(func.count()).select_from(User))
    profiles = await session.scalar(select(func.count()).select_from(ProfessionalProfile))
    return users or 0, profiles or 0


async def test_first_sign_in_creates_one_user_and_one_profile(db_session: AsyncSession) -> None:
    """T031 (FR-010)."""
    user = await provision_user(db_session, CLAIMS)
    await db_session.commit()

    assert user.google_sub == CLAIMS["sub"]
    assert user.email == CLAIMS["email"]
    assert user.display_name == CLAIMS["name"]
    assert await _counts(db_session) == (1, 1)


async def test_returning_user_creates_no_second_profile(db_session: AsyncSession) -> None:
    """T032 (FR-011): signing in repeatedly must not accumulate profiles."""
    first = await provision_user(db_session, CLAIMS)
    await db_session.commit()

    second = await provision_user(db_session, CLAIMS)
    await db_session.commit()

    third = await provision_user(db_session, CLAIMS)
    await db_session.commit()

    assert first.id == second.id == third.id
    assert await _counts(db_session) == (1, 1)


async def test_returning_user_email_change_does_not_split_the_account(
    db_session: AsyncSession,
) -> None:
    """Identity is the Google subject, not the email.

    A Google account can change its email address. Matching on email would turn
    one person into two accounts and orphan their history.
    """
    await provision_user(db_session, CLAIMS)
    await db_session.commit()

    changed = {**CLAIMS, "email": "changed.address@example.com"}
    user = await provision_user(db_session, changed)
    await db_session.commit()

    assert user.email == "changed.address@example.com"
    assert await _counts(db_session) == (1, 1)


async def test_concurrent_first_sign_in_yields_exactly_one_profile(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """T033 (SC-004, research.md R-004) — the reason the constraint is in the schema.

    Two sign-ins for the same brand-new account arrive together. Each opens its
    own transaction, so neither can see the other's uncommitted insert: a
    check-then-insert in Python has both read "no user exists" and both insert.
    Only a UNIQUE constraint can serialise this.
    """

    async def sign_in() -> None:
        async with session_factory() as session:
            await provision_user(session, CLAIMS)
            await session.commit()

    results = await asyncio.gather(sign_in(), sign_in(), sign_in(), return_exceptions=True)

    # Losing the race is fine; provisioning must absorb it and return the winner.
    for result in results:
        assert not isinstance(result, Exception), f"provisioning raised: {result!r}"

    async with session_factory() as session:
        assert await _counts(session) == (1, 1)


async def test_different_users_get_their_own_profiles(db_session: AsyncSession) -> None:
    """The invariant is one profile *per user*, not one profile overall."""
    await provision_user(db_session, CLAIMS)
    await provision_user(
        db_session, {**CLAIMS, "sub": "google-subject-99999", "email": "second.person@example.com"}
    )
    await db_session.commit()

    assert await _counts(db_session) == (2, 2)


async def test_missing_subject_is_rejected(db_session: AsyncSession) -> None:
    """Without a subject there is no identity to key on."""
    with pytest.raises((KeyError, ValueError)):
        await provision_user(db_session, {"email": "no-sub@example.com"})
