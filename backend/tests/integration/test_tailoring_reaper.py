"""SC-008 — a run that stops without finishing must be recoverable.

This exists because slice 004 got it wrong three times in a row, and each
recovery needed SQL typed by hand. The shape of the failure is worth restating,
because it is not obvious: the in-flight guard answered 409 to a *second* run,
which was correct — but the run it was protecting was already dead, so the guard
was refusing the one action that would have fixed anything. A safety check that
locks the user out of recovery is worse than no check.

**The threshold is not copied from match analysis.** That guards a run that
should take seconds. This one makes up to seven calls, three of them on the
slower reviewing model, and SC-001 allows three minutes for the full revision
budget. Releasing a run that is legitimately in its second revision would let a
second start against the same job — which the partial index then rejects,
putting the person back in the same trap from the other direction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.tailor_resume import (
    ABANDONED_AFTER,
    TailoringInFlight,
    create_pending_version,
    is_abandoned,
)
from careerhq.domain.models import ResumeVersion, RunStatus, TailoringRun, VersionStatus
from tests.support.tailoring_fixtures import seed_tailorable

# No module-level asyncio marker: half of this file is pure functions with no
# database at all, and marking a sync test as asyncio fails it outright.


def _run(**overrides: object) -> TailoringRun:
    """An unsaved run, for the pure-function checks.

    A real constructor rather than `__new__`: bypassing SQLAlchemy's
    instrumentation leaves the attribute machinery uninitialised, and the first
    `setattr` fails with a `NoneType has no attribute 'set'` that says nothing
    about what is actually wrong.
    """
    defaults: dict[str, object] = {
        "resume_version_id": uuid.uuid4(),
        "match_analysis_id": uuid.uuid4(),
        "finalisation_rules_version": "v1-severity",
        "status": RunStatus.RUNNING,
        "started_at": datetime.now(UTC),
        "finished_at": None,
    }
    return TailoringRun(**{**defaults, **overrides})


def test_a_run_inside_the_window_is_not_abandoned() -> None:
    """The side that matters most. A run in its second revision is working, not
    stuck, and releasing it would corrupt a live workflow."""
    working = _run(started_at=datetime.now(UTC) - (ABANDONED_AFTER - timedelta(minutes=1)))
    assert is_abandoned(working) is False


def test_a_run_past_the_window_is_abandoned() -> None:
    stalled = _run(started_at=datetime.now(UTC) - (ABANDONED_AFTER + timedelta(minutes=1)))
    assert is_abandoned(stalled) is True


def test_a_finished_run_is_never_abandoned() -> None:
    """`finished_at` is the signal, not elapsed time. A run that completed an
    hour ago is old, not stuck — and reaping it would rewrite a successful
    outcome as a failure."""
    done = _run(
        status=RunStatus.SUCCEEDED,
        started_at=datetime.now(UTC) - timedelta(days=2),
        finished_at=datetime.now(UTC) - timedelta(days=2),
    )
    assert is_abandoned(done) is False


def test_the_window_leaves_room_for_the_full_revision_budget() -> None:
    """SC-001 allows three minutes for seven calls. A threshold below that would
    reap runs that are simply slow, which is the failure this whole module is
    about, arriving by a different route."""
    assert ABANDONED_AFTER > timedelta(minutes=3)


@pytest.mark.asyncio
async def test_a_stalled_run_is_released_so_the_owner_can_try_again(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The end-to-end recovery, without database access (SC-008).

    **Corrected after the retry fix**, and the correction is worth recording:
    this test's own failure message said *"a retry reuses this draft rather than
    accumulating versions"* while its assertions required the opposite —
    `fresh_id != stuck.id`. The message was the design, quoted from
    `data-model.md`; the assertions were written to match what the code did.

    A test whose prose and whose assertions disagree will always pass, and will
    always describe something other than what it checks.
    """
    seeded = await seed_tailorable(db_session, sub="stalled", email="stalled@example.com")
    stuck = await create_pending_version(db_session, seeded.application)
    stuck_run_id = stuck.tailoring_run_id
    await db_session.commit()

    async with session_factory() as session:
        run = await session.get(TailoringRun, stuck_run_id)
        assert run is not None
        run.started_at = datetime.now(UTC) - (ABANDONED_AFTER + timedelta(minutes=5))
        await session.commit()

    async with session_factory() as session:
        application = await session.get(type(seeded.application), seeded.application.id)
        assert application is not None
        fresh = await create_pending_version(session, application)
        await session.commit()
        fresh_id = fresh.id

    async with session_factory() as session:
        released = await session.get(TailoringRun, stuck_run_id)
        assert released is not None
        assert released.status == RunStatus.ABANDONED
        assert released.finished_at is not None

        # Released to `draft` and then reused by the same call — there is no
        # `failed` status precisely so that a retry lands back in this draft
        # rather than accumulating abandoned versions (data-model.md).
        assert fresh_id == stuck.id, "the released draft is the retry target"

        reused = await session.get(ResumeVersion, stuck.id)
        assert reused is not None
        assert reused.status == VersionStatus.TAILORING
        # Not captioned by the dead run's error.
        assert reused.failure_reason is None
        # And pointing at the new attempt, not the abandoned one.
        assert reused.tailoring_run_id != stuck_run_id

        versions = (
            await session.scalars(
                select(ResumeVersion).where(ResumeVersion.application_id == seeded.application.id)
            )
        ).all()
        assert len(versions) == 1, f"recovery accumulated {len(versions)} versions"


@pytest.mark.asyncio
async def test_a_live_run_still_blocks_a_second_request(db_session: AsyncSession) -> None:
    """The reaper must not become a way around FR-004."""
    seeded = await seed_tailorable(db_session, sub="live-run", email="live@example.com")
    await create_pending_version(db_session, seeded.application)
    await db_session.flush()

    with pytest.raises(TailoringInFlight):
        await create_pending_version(db_session, seeded.application)

    versions = (
        (
            await db_session.execute(
                select(ResumeVersion).where(ResumeVersion.application_id == seeded.application.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(versions) == 1
