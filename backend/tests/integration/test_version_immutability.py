"""FR-030, FR-031, SC-007 — a version does not change when the profile does.

**Constitution Principle IV**: *profile updates MUST NOT alter existing Resume
Versions.* `/speckit-analyze` found this had no coverage, which mattered because
`data-model.md` justifies copying `original_text` rather than referencing it
*precisely so this holds* — a design decision defended by an argument nothing
tested.

What breaks without it is not obvious. The version keeps rendering, the diff
keeps loading, and the only symptom is that what a person approved last month
now says something they never agreed to. ADR-012 records lineage rather than
inheriting it for exactly this reason.

Everything is re-read **in a fresh session** (FR-047). A version still held in
the identity map of the session that created it would show the values that
session set, not the ones the database holds — which is the same class of
mistake as slice 004's `is`-versus-`==`, where a test passed because it never
left the session that knew the answer.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.domain.models import (
    ExperienceBullet,
    ResumeProfile,
    ResumeVersion,
    Skill,
    SummaryBlock,
)
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


def _plan() -> dict[str, object]:
    return {
        "emphasise": [{"what": "Platform ownership", "serves_requirement": "5+ years backend"}],
        "de_emphasise": [],
        "protected_gaps": [],
        "strategy": "Lead with scale.",
    }


async def _tailor(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    sub: str,
    email: str,
):
    seeded = await seed_tailorable(db_session, sub=sub, email=email)
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [
                {
                    "items": [
                        {
                            "source_item_id": str(seeded.bullet_ids[0]),
                            "source_kind": "experience_bullet",
                            "position": 0,
                            "included": True,
                            "text": "Owned the payments platform for six years.",
                            "reason": "Leads with the posting's requirement.",
                        }
                    ]
                }
            ],
            "tailor_review": [{"confidence": 91, "findings": []}],
        }
    )
    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    return seeded, version


async def _load(session: AsyncSession, version_id) -> ResumeVersion:
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


async def test_editing_the_profile_does_not_reach_an_existing_version(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The whole of Principle IV, in one test.

    A bullet is rewritten, a skill removed, a summary replaced and an experience
    added — the four shapes of profile edit — and none of them may reach a
    version that already exists.
    """
    seeded, version = await _tailor(
        db_session, session_factory, sub="immutable", email="immutable@example.com"
    )

    async with session_factory() as session:
        before = await _load(session, version.id)
        snapshot = {
            item.id: (item.original_text, item.proposed_text, item.final_text)
            for item in before.items
        }
        source_updated_at = before.source_profile_updated_at
        source_master_id = before.source_resume_profile_id
        assert snapshot, "the version must have items, or this test proves nothing"

    async with session_factory() as session:
        bullet = await session.get(ExperienceBullet, seeded.bullet_ids[0])
        assert bullet is not None
        bullet.text = "COMPLETELY DIFFERENT TEXT WRITTEN AFTER THE VERSION EXISTED"

        summary = await session.get(SummaryBlock, seeded.summary_id)
        assert summary is not None
        summary.text = "A rewritten summary."

        removed = await session.get(Skill, seeded.skill_ids[0])
        assert removed is not None
        await session.delete(removed)

        session.add(Skill(profile_id=seeded.profile.id, name="Rust", source="USER_ADDED"))
        await session.commit()

    async with session_factory() as session:
        after = await _load(session, version.id)

        for item in after.items:
            assert (item.original_text, item.proposed_text, item.final_text) == snapshot[item.id], (
                "a profile edit reached an existing version. Principle IV: profile "
                "updates must not alter existing Resume Versions."
            )

        assert after.source_profile_updated_at == source_updated_at, (
            "lineage records the profile's state at creation and must not advance"
        )
        assert after.source_resume_profile_id == source_master_id


async def test_deleting_the_profile_fact_a_version_quotes_leaves_the_version_readable(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The copy is what makes this survivable.

    A reference would leave the version with a dangling id and nothing to show —
    and this is not hypothetical: people delete a role from their profile after
    tailoring against it.
    """
    seeded, version = await _tailor(
        db_session, session_factory, sub="deleted-fact", email="deleted@example.com"
    )

    async with session_factory() as session:
        before = await _load(session, version.id)
        texts = sorted(item.final_text for item in before.items)

    async with session_factory() as session:
        bullet = await session.get(ExperienceBullet, seeded.bullet_ids[0])
        assert bullet is not None
        await session.delete(bullet)
        await session.commit()

    async with session_factory() as session:
        after = await _load(session, version.id)
        assert sorted(item.final_text for item in after.items) == texts, (
            "deleting the source fact must not empty the version that quoted it"
        )


async def test_the_version_records_which_master_it_came_from(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-030 and SC-007 — lineage is recorded, so two versions are never
    silently incomparable."""
    seeded, version = await _tailor(
        db_session, session_factory, sub="lineage", email="lineage@example.com"
    )

    async with session_factory() as session:
        loaded = await _load(session, version.id)
        master = await session.get(ResumeProfile, loaded.source_resume_profile_id)

        assert master is not None
        assert master.is_master
        assert master.profile_id == seeded.profile.id
        assert loaded.source_profile_updated_at is not None
