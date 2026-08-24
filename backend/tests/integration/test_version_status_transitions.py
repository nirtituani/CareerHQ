"""FR-047 — every status path, exercised against a record re-read from storage.

This file exists because of the most expensive bug in slice 004, and the bug is
worth restating exactly, because nothing about it looked wrong.

Status columns are `String(16)`. A row loaded in a **fresh** session comes back
as a plain `str`, so `status is not MatchStatus.PENDING` matched nothing —
`run_analysis` returned immediately on every real call. Nothing raised, nothing
logged, and every analysis sat `pending` forever while 270 tests stayed green.
The tests missed it because they passed the session that *created* the row,
whose identity map still held the enum member.

So: `==`, never `is`, and every assertion below re-reads.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import (
    approve_version,
    create_pending_version,
    decide_item,
    run_tailoring,
)
from careerhq.domain.models import (
    ProposalDecision,
    ResumeVersion,
    RunStatus,
    TailoringRun,
    VersionStatus,
)
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


def _script(bullet_id, confidence: int = 90) -> dict:
    return {
        "tailor_plan": [
            {
                "emphasise": [
                    {"what": "Platform ownership", "serves_requirement": "5+ years backend"}
                ],
                "de_emphasise": [],
                "protected_gaps": [],
                "strategy": "Lead with scale.",
            }
        ],
        "tailor_draft": [
            {
                "items": [
                    {
                        "source_item_id": str(bullet_id),
                        "source_kind": "experience_bullet",
                        "position": 0,
                        "included": True,
                        "text": "Owned the payments platform.",
                        "reason": "Leads with the requirement.",
                    }
                ]
            }
        ],
        "tailor_review": [{"confidence": confidence, "findings": []}],
    }


async def _reload(session: AsyncSession, version_id) -> ResumeVersion:
    return (
        (
            await session.execute(
                select(ResumeVersion)
                .where(ResumeVersion.id == version_id)
                .options(selectinload(ResumeVersion.items))
            )
        )
        .unique()
        .scalar_one()
    )


async def test_status_read_from_a_fresh_session_compares_equal(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The slice-004 bug, as a direct assertion.

    A fresh read returns a plain `str`. `==` matches it; `is` does not. Both are
    asserted, so the day someone "tidies" a comparison to `is`, this fails
    rather than the feature silently stopping.
    """
    seeded = await seed_tailorable(db_session, sub="fresh-read", email="fresh@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        reloaded = await session.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert reloaded.status == VersionStatus.TAILORING, "`==` must match a re-read status"
        assert (reloaded.status is VersionStatus.TAILORING) is False, (
            "a status re-read from the database is a plain str, not the enum member — "
            "which is why `is` silently never matches and must never be used"
        )


async def test_the_whole_lifecycle_runs_forward_through_fresh_sessions(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """draft -> tailoring -> awaiting_approval -> ready, each read anew."""
    seeded = await seed_tailorable(db_session, sub="lifecycle", email="lifecycle@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        assert (await _reload(session, version.id)).status == VersionStatus.TAILORING

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=_script(seeded.bullet_ids[0])),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        assert loaded.status == VersionStatus.AWAITING_APPROVAL, (
            "the agent is finished; this is the state that says it is the owner's turn"
        )

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        await approve_version(session, version=loaded)
        await session.commit()

    async with session_factory() as session:
        assert (await _reload(session, version.id)).status == VersionStatus.READY


async def test_reviewing_and_awaiting_approval_are_not_the_same_state(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The amendment to `docs/03` §10.1, asserted behaviourally.

    One is a machine working for tens of seconds; the other is a human queue
    that may last days. A person watching a spinner cannot tell them apart if
    they share a value, and they have different next actions.
    """
    assert VersionStatus.REVIEWING != VersionStatus.AWAITING_APPROVAL

    seeded = await seed_tailorable(db_session, sub="two-states", email="two@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=_script(seeded.bullet_ids[0])),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        assert loaded.status != VersionStatus.REVIEWING, (
            "a finished run must not leave the version looking like the agent is still working"
        )


async def test_an_approved_version_is_still_editable(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-029. `docs/03`: approval is not a one-way door until export."""
    seeded = await seed_tailorable(db_session, sub="editable", email="editable@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=_script(seeded.bullet_ids[0])),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        await approve_version(session, version=loaded)
        await session.commit()

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        assert loaded.status == VersionStatus.READY
        target = loaded.items[0]
        await decide_item(
            session, item=target, decision=ProposalDecision.EDITED, text="Edited after approval."
        )
        await session.commit()

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        edited = next(i for i in loaded.items if i.id == target.id)
        assert edited.final_text == "Edited after approval."
        assert edited.decision == ProposalDecision.EDITED


async def test_a_run_in_progress_does_not_lock_the_job_or_the_profile(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-044. A background task must not make the rest of the app unusable.

    Slice 004 carried the same requirement and it mattered: the version people
    are waiting on is exactly when they go and look at the job record.
    """
    seeded = await seed_tailorable(db_session, sub="not-locked", email="notlocked@example.com")
    await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        application = await session.get(type(seeded.application), seeded.application.id)
        assert application is not None
        application.notes = "Read and edited while a run was in flight."
        await session.commit()

    async with session_factory() as session:
        run = await session.scalar(select(TailoringRun))
        assert run is not None
        assert run.status == RunStatus.RUNNING, "the run is still going; nothing was blocked"
