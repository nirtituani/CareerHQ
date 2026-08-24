"""FR-004 — at most one tailoring run in flight per job.

Asserted against **the partial index**, not against the code path that usually
checks it. An application-level guard is a read followed by a write, and two
clicks land in the gap between them; the index cannot be raced, and this is the
project's stated rule that business invariants belong in the schema.

The distinction matters here more than usual: a duplicate run is not a cosmetic
problem. It is two agents drafting against one job, each spending up to seven
model calls, and whichever finishes second overwrites the version the person may
already be reading.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.tailor_resume import (
    TailoringInFlight,
    create_pending_version,
)
from careerhq.domain.models import ResumeVersion, VersionStatus
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


async def test_a_second_request_while_one_runs_is_refused(db_session: AsyncSession) -> None:
    seeded = await seed_tailorable(db_session, sub="inflight", email="inflight@example.com")
    await create_pending_version(db_session, seeded.application)
    await db_session.flush()

    with pytest.raises(TailoringInFlight):
        await create_pending_version(db_session, seeded.application)


async def test_the_database_refuses_a_second_in_flight_version_directly(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The guard that a race cannot get past.

    Inserting a second `tailoring` row by hand skips every application-level
    check, which is exactly what two simultaneous requests would do.
    """
    seeded = await seed_tailorable(db_session, sub="race", email="race@example.com")
    first = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                ResumeVersion(
                    profile_id=first.profile_id,
                    application_id=first.application_id,
                    source_resume_profile_id=first.source_resume_profile_id,
                    source_profile_updated_at=first.source_profile_updated_at,
                    name="A racing second version",
                    status=VersionStatus.TAILORING,
                    items=[],
                )
            )
            await session.commit()


async def test_finished_versions_do_not_block_a_new_run(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The index is partial for a reason.

    A job accumulates versions over time — tailored, approved, tailored again
    after the posting changed. Only `tailoring` and `reviewing` may collide, or
    a person could tailor each job exactly once, forever.
    """
    seeded = await seed_tailorable(db_session, sub="repeat", email="repeat@example.com")
    first = await create_pending_version(db_session, seeded.application)
    first.status = VersionStatus.READY
    await db_session.commit()

    async with session_factory() as session:
        application = await session.get(type(seeded.application), seeded.application.id)
        assert application is not None
        second = await create_pending_version(session, application)
        await session.commit()

    assert second.id != first.id

    async with session_factory() as session:
        count = len(
            (
                await session.execute(
                    select(ResumeVersion).where(
                        ResumeVersion.application_id == seeded.application.id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert count == 2


async def test_the_index_is_partial_on_exactly_the_in_flight_statuses(
    db_session: AsyncSession,
) -> None:
    """If the predicate ever drifts from the two working states, the two tests
    above would still pass — one because nothing collides, the other because
    everything does."""
    definition = await db_session.scalar(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'uq_resume_versions_one_in_flight_per_application'"
        )
    )

    assert definition is not None, "the in-flight index is gone; FR-004 is unenforced"
    assert "UNIQUE" in definition.upper()
    assert "tailoring" in definition
    assert "reviewing" in definition
    for finished in ("awaiting_approval", "ready"):
        assert finished not in definition, (
            f"'{finished}' is a finished state and must not block a new run: {definition}"
        )
