"""What PostgreSQL enforces about advisor runs, and what the reserve path does
(slice 009, T008).

`tests/unit/test_advisor_models.py` asserts what the schema declares and
`tests/unit/test_advisor_run_lifecycle.py` the pure logic; this file asserts
what the database *refuses* — the two-clicks race losing to the partial
unique index — and what recovery looks like when a run is abandoned.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.advise_career import create_pending_run, is_abandoned
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    AdvisorRun,
    AdvisorRunStatus,
    Application,
    Company,
    NormalizedStatus,
    User,
    normalize_company_name,
)

pytestmark = pytest.mark.asyncio


async def _seed_user(session: AsyncSession, *, applications: int = 1) -> User:
    sub = f"advisor-{uuid.uuid4().hex[:12]}"
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Advisor"}
    )
    for index in range(applications):
        company = Company(
            user_id=user.id,
            name=f"Seeded {index}",
            normalized_name=normalize_company_name(f"Seeded {index}"),
        )
        session.add(company)
        await session.flush()
        session.add(
            Application(
                user_id=user.id,
                company_id=company.id,
                job_title="Backend",
                status="Wishlist",
                normalized_status=NormalizedStatus.WISHLIST,
            )
        )
    await session.flush()
    return user


async def test_a_user_with_no_history_gets_no_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The honest empty state costs nothing — no row, no completion."""
    async with session_factory() as session:
        user = await _seed_user(session, applications=0)
        assert await create_pending_run(session, user) is None
        await session.commit()


async def test_the_two_clicks_race_loses_to_the_index(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two sessions reserve concurrently; the second insert violates
    `uq_advisor_run_one_pending_per_user` at commit. The index is the
    enforcement — nothing in application code pre-checks, because a pre-check
    is the raceable copy of the rule."""
    async with session_factory() as session:
        user = await _seed_user(session)
        run = await create_pending_run(session, user)
        assert run is not None
        await session.commit()
        user_id = user.id

    async with session_factory() as second:
        second.add(
            AdvisorRun(
                user_id=user_id,
                status=AdvisorRunStatus.PENDING,
                rules_version="v1-advisor",
                dispositions=[],
            )
        )
        with pytest.raises(IntegrityError) as refusal:
            await second.commit()
        assert "uq_advisor_run_one_pending_per_user" in str(refusal.value)


async def test_an_abandoned_run_reads_as_failed_and_unblocks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A pending row past the deadline is reaped, not honoured — otherwise the
    one action that recovers the feature is the one action refused."""
    async with session_factory() as session:
        user = await _seed_user(session)
        run = await create_pending_run(session, user)
        assert run is not None
        await session.commit()
        await session.execute(
            text(
                "UPDATE advisor_runs SET created_at = now() - interval '11 minutes' WHERE id = :id"
            ),
            {"id": run.id},
        )
        await session.commit()
        run_id, user_id = run.id, user.id

    async with session_factory() as fresh:
        stale = await fresh.get(AdvisorRun, run_id)
        assert stale is not None
        # Read through a second session: `status` is a plain string here, which
        # is exactly the condition under which `is` comparisons shipped broken.
        assert is_abandoned(stale) is True

        # Reap, then a new reservation succeeds — the index only guards
        # `pending`, so the terminal row no longer collides.
        stale.status = AdvisorRunStatus.FAILED
        stale.error = "The analysis stopped before it finished."
        await fresh.flush()
        user_row = await fresh.get(User, user_id)
        assert user_row is not None
        replacement = await create_pending_run(fresh, user_row)
        assert replacement is not None
        await fresh.commit()
