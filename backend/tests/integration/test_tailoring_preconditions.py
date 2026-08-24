"""FR-001 — tailoring refuses rather than working from a stale assessment.

The refusal is not defensive tidiness. A plan built on an analysis computed
against an **older profile** cites evidence that no longer exists, and the
Reviewer then rejects claims that were properly grounded when they were
analysed. That failure reads as the Reviewer malfunctioning, and it is expensive
to debug precisely because nothing is actually broken.

The two reasons must stay distinguishable: *score this job first* and *your
profile changed, re-score it* are different actions, and one message covering
both makes the interface guess which to offer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.tailor_resume import (
    TailoringRefused,
    check_preconditions,
    create_pending_version,
)
from careerhq.domain.models import MatchAnalysis, MatchStatus, ProfessionalProfile, ResumeProfile
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


async def test_a_job_with_no_analysis_is_refused(db_session: AsyncSession) -> None:
    seeded = await seed_tailorable(db_session, sub="no-analysis", email="no-analysis@example.com")
    seeded.application.current_match_analysis_id = None
    await db_session.flush()

    with pytest.raises(TailoringRefused) as refused:
        await check_preconditions(db_session, seeded.application)

    assert refused.value.reason == "no_analysis"
    assert "match analysis" in refused.value.detail.lower()


async def test_an_analysis_still_running_is_not_good_enough(db_session: AsyncSession) -> None:
    """`pending` is not `ready`. A half-finished analysis has no verdicts, so a
    plan built from it would have no gaps to protect — the most dangerous
    possible input, because it looks like a profile with nothing missing."""
    seeded = await seed_tailorable(
        db_session,
        sub="pending-analysis",
        email="pending@example.com",
        analysis_status=MatchStatus.PENDING,
    )

    with pytest.raises(TailoringRefused) as refused:
        await check_preconditions(db_session, seeded.application)

    assert refused.value.reason == "no_analysis"


async def test_a_profile_edited_since_scoring_is_refused(db_session: AsyncSession) -> None:
    """The staleness comparison, computed at read time rather than stored."""
    seeded = await seed_tailorable(db_session, sub="stale", email="stale@example.com")

    # Move the profile forward rather than the analysis back: this is the real
    # direction of the event, and `updated_at` has an onupdate that would fight
    # a direct assignment.
    await db_session.execute(
        update(ProfessionalProfile)
        .where(ProfessionalProfile.id == seeded.profile.id)
        .values(updated_at=datetime.now(UTC) + timedelta(minutes=5))
    )
    await db_session.flush()
    # An awaited refresh, not `expire_all()`: expiring makes the next attribute
    # access do IO synchronously, which async SQLAlchemy answers with
    # MissingGreenlet rather than with the value.
    await db_session.refresh(seeded.profile)

    with pytest.raises(TailoringRefused) as refused:
        await check_preconditions(db_session, seeded.application)

    assert refused.value.reason == "stale_analysis"


async def test_the_two_refusals_say_different_things(db_session: AsyncSession) -> None:
    """One message for both causes would make the interface offer the wrong
    action — "run a match analysis" to someone who already has one."""
    unscored = await seed_tailorable(db_session, sub="msg-a", email="msg-a@example.com")
    unscored.application.current_match_analysis_id = None
    await db_session.flush()

    with pytest.raises(TailoringRefused) as first:
        await check_preconditions(db_session, unscored.application)

    stale = await seed_tailorable(db_session, sub="msg-b", email="msg-b@example.com")
    await db_session.execute(
        update(ProfessionalProfile)
        .where(ProfessionalProfile.id == stale.profile.id)
        .values(updated_at=datetime.now(UTC) + timedelta(minutes=5))
    )
    await db_session.flush()
    await db_session.refresh(stale.profile)

    with pytest.raises(TailoringRefused) as second:
        await check_preconditions(db_session, stale.application)

    assert first.value.reason != second.value.reason
    assert first.value.detail != second.value.detail


async def test_a_profile_with_no_master_resume_is_refused(db_session: AsyncSession) -> None:
    """There is nothing to tailor *from*. Reachable in production by a user who
    signed in but never approved an import."""
    seeded = await seed_tailorable(db_session, sub="no-master", email="no-master@example.com")
    await db_session.execute(
        delete(ResumeProfile).where(ResumeProfile.profile_id == seeded.profile.id)
    )
    await db_session.flush()

    with pytest.raises(TailoringRefused) as refused:
        await check_preconditions(db_session, seeded.application)

    assert refused.value.reason == "no_master"


async def test_nothing_is_created_when_a_precondition_fails(db_session: AsyncSession) -> None:
    """A refusal must not leave a version or a run behind.

    Reserving the row first and validating second would produce exactly the
    orphan `draft` versions the lifecycle avoids having a `failed` status for.
    """
    seeded = await seed_tailorable(db_session, sub="no-rows", email="no-rows@example.com")
    seeded.application.current_match_analysis_id = None
    await db_session.flush()

    with pytest.raises(TailoringRefused):
        await create_pending_version(db_session, seeded.application)

    from sqlalchemy import func, select

    from careerhq.domain.models import ResumeVersion, TailoringRun

    versions = await db_session.scalar(
        select(func.count())
        .select_from(ResumeVersion)
        .where(ResumeVersion.application_id == seeded.application.id)
    )
    runs = await db_session.scalar(select(func.count()).select_from(TailoringRun))

    assert versions == 0
    assert runs == 0


async def test_a_ready_analysis_on_an_untouched_profile_is_accepted(
    db_session: AsyncSession,
) -> None:
    """The positive case, so the tests above prove a rule rather than a
    permanently closed door."""
    seeded = await seed_tailorable(db_session, sub="happy", email="happy@example.com")

    analysis, profile, master = await check_preconditions(db_session, seeded.application)

    assert isinstance(analysis, MatchAnalysis)
    assert profile.id == seeded.profile.id
    assert master.is_master
