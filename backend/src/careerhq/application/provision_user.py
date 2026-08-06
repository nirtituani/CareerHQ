"""First-sign-in provisioning.

Creates a user and their single Professional Profile, idempotently and safely
under concurrency.

The naive version — SELECT, and INSERT if absent — is a race. Two sign-ins for
the same new account each open their own transaction, neither sees the other's
uncommitted insert, both conclude the user does not exist, and both insert. One
then fails on the UNIQUE constraint, and the user sees an error on a perfectly
ordinary first sign-in.

``INSERT ... ON CONFLICT DO NOTHING`` pushes the decision into the database,
which is the only participant that can serialise it (research.md R-004).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.domain.models import ProfessionalProfile, User

logger = logging.getLogger("careerhq.provisioning")


async def provision_user(session: AsyncSession, claims: Mapping[str, Any]) -> User:
    """Return the user for ``claims``, creating them and their profile if new.

    Safe to call on every sign-in: the first call creates, subsequent calls
    refresh the profile fields and update ``last_login_at``.
    """
    google_sub = claims.get("sub")
    if not google_sub:
        raise ValueError("Google claims are missing the 'sub' (subject) field")

    email = claims.get("email")
    if not email:
        raise ValueError("Google claims are missing the 'email' field")

    now = datetime.now(UTC)

    # Insert the user, or do nothing if this subject already exists. Profile
    # fields are refreshed on every sign-in so a changed name or avatar follows
    # the Google account.
    user_stmt = (
        insert(User)
        .values(
            google_sub=google_sub,
            email=email,
            display_name=claims.get("name"),
            avatar_url=claims.get("picture"),
            last_login_at=now,
        )
        .on_conflict_do_update(
            index_elements=[User.google_sub],
            set_={
                "email": email,
                "display_name": claims.get("name"),
                "avatar_url": claims.get("picture"),
                "last_login_at": now,
            },
        )
        .returning(User.id)
    )
    user_id = await session.scalar(user_stmt)

    # A concurrent transaction may have committed between our insert and here,
    # in which case ON CONFLICT DO UPDATE still returns our row — but be
    # defensive: if nothing came back, read the winner.
    if user_id is None:  # pragma: no cover - defensive
        user_id = await session.scalar(select(User.id).where(User.google_sub == google_sub))

    # Exactly one profile per user (Constitution Principle I). The UNIQUE
    # constraint on user_id is what makes DO NOTHING correct rather than
    # merely optimistic.
    await session.execute(
        insert(ProfessionalProfile)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=[ProfessionalProfile.user_id])
    )

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:  # pragma: no cover - unreachable while the row exists
        raise RuntimeError("provisioned user disappeared")

    logger.info("user provisioned", extra={"user_id": str(user.id)})
    return user
