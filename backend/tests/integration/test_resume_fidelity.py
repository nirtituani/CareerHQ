"""What a version must capture for the export to look like the CV it came from.

**Every fact here is captured at version creation, and that is the point.** Export reads
the version, never the profile — a locked document that re-derived its content later
would change underneath the checksum it was recorded with (FR-023). So each of these is
a snapshot taken once, in the same transaction that reserves the version, exactly as
role context has been since T051.

The three gaps this file covers were each measured on a real export before being fixed:
the headline never reached the version at all, a skill's category was dropped on the way
in, and the contact line lost every link the profile held.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.export_resume import _compose
from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import (
    _render_master,
    create_pending_version,
    run_tailoring,
)
from careerhq.domain.models import (
    ContactInformation,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    Skill,
    SourceKind,
)
from tests.integration.test_tailoring_workflow import _draft, _plan, _review
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession, sub: str):  # type: ignore[no-untyped-def]
    return await seed_tailorable(session, sub=f"{sub}-{uuid.uuid4()}", email=f"{sub}@example.com")


# -- the headline -----------------------------------------------------------


async def test_the_version_snapshots_the_professional_headline(db_session: AsyncSession) -> None:
    """`ResumeVersion.professional_title` existed, was exposed by the API, and was never
    written by anything — so the headline under the contact line could not be exported.

    It is restated from the profile's own title rows in their stored order and nothing
    is invented, which is what keeps this a rendering fix rather than a claim.
    """
    seeded = await _seed(db_session, "headline")
    version = await create_pending_version(db_session, seeded.application)

    assert version.professional_title == "Senior Backend Engineer · Payments Specialist"


async def test_a_profile_with_no_title_leaves_the_headline_unset(
    db_session: AsyncSession,
) -> None:
    """Absence must stay absent. A profile that records no headline must not gain one."""
    from careerhq.domain.models import ProfessionalTitle

    seeded = await _seed(db_session, "notitle")
    await db_session.execute(
        ProfessionalTitle.__table__.delete().where(
            ProfessionalTitle.profile_id == seeded.profile.id
        )
    )
    await db_session.flush()

    version = await create_pending_version(db_session, seeded.application)
    assert version.professional_title is None


async def test_the_headline_reaches_the_document(db_session: AsyncSession) -> None:
    seeded = await _seed(db_session, "headdoc")
    version = await create_pending_version(db_session, seeded.application)
    contact = await db_session.scalar(
        select(ContactInformation).where(ContactInformation.profile_id == seeded.profile.id)
    )

    document = _compose(version, contact)
    assert document.headline == "Senior Backend Engineer · Payments Specialist"


# -- the skill category -----------------------------------------------------


async def test_skill_items_snapshot_their_category(db_session: AsyncSession) -> None:
    """The category the profile already holds, frozen onto the item that carries the skill."""
    seeded = await _seed(db_session, "skillcat")
    _prompt, items = await _render_master(db_session, seeded.profile.id)

    skills = [item for item in items if item["source_kind"] == SourceKind.SKILL]
    assert skills, "no skill items were produced — this test would examine nothing"
    assert {item["text"]: item["source_category"] for item in skills} == {
        "Python": "Programming Languages",
        "PostgreSQL": "Databases",
    }


async def test_an_uncategorised_skill_snapshots_no_category(db_session: AsyncSession) -> None:
    seeded = await _seed(db_session, "nocat")
    db_session.add(Skill(profile_id=seeded.profile.id, name="Curiosity", source="EXTRACTED"))
    await db_session.flush()

    _prompt, items = await _render_master(db_session, seeded.profile.id)
    loose = [item for item in items if item.get("text") == "Curiosity"]
    assert loose and loose[0]["source_category"] is None


async def test_uncategorised_skills_still_render_as_plain_rows(
    db_session: AsyncSession,
) -> None:
    """No category is not an error, and must not invent one or drop the skill."""
    seeded = await _seed(db_session, "plainrows")
    version = await create_pending_version(db_session, seeded.application)
    db_session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.SKILL,
            position=0,
            source_category=None,
            original_text="Curiosity",
            final_text="Curiosity",
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    await db_session.flush()
    await db_session.refresh(version, ["items"])

    document = _compose(version, None)
    skills = next(s for s in document.sections if s.heading == "Skills")
    assert [line for group in skills.groups for line in group.lines] == ["Curiosity"]


# -- the contact line -------------------------------------------------------


async def test_contact_links_reach_the_document(db_session: AsyncSession) -> None:
    """The profile stores links; the exported contact line dropped every one of them.

    Stored newline-separated, so each becomes its own fragment rather than one long
    string with a newline in the middle of the rendered line.
    """
    seeded = await _seed(db_session, "links")
    version = await create_pending_version(db_session, seeded.application)
    contact = await db_session.scalar(
        select(ContactInformation).where(ContactInformation.profile_id == seeded.profile.id)
    )
    assert contact is not None
    contact.email = "dana@example.com"
    contact.location = "Tel Aviv"
    contact.links = "example.com/in/dana\nhttps://example.com/dana"
    await db_session.flush()

    document = _compose(version, contact)
    assert "example.com/in/dana" in document.contact
    assert "https://example.com/dana" in document.contact
    # ...and the fields that were already there keep their place ahead of them.
    assert document.contact[:2] == ("dana@example.com", "Tel Aviv")
    assert document.contact[-2:] == ("example.com/in/dana", "https://example.com/dana")


async def test_a_profile_with_no_links_composes_the_same_contact_line_as_before(
    db_session: AsyncSession,
) -> None:
    """Backward compatibility for every profile that stores none."""
    seeded = await _seed(db_session, "nolinks")
    version = await create_pending_version(db_session, seeded.application)
    contact = await db_session.scalar(
        select(ContactInformation).where(ContactInformation.profile_id == seeded.profile.id)
    )
    assert contact is not None
    contact.links = None
    await db_session.flush()

    document = _compose(version, contact)
    assert document.contact == tuple(
        value for value in (contact.email, contact.phone, contact.location) if value
    )


# -- the persistence boundary, driven by the real workflow -------------------


async def test_the_real_workflow_persists_each_skill_category(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """**The gate that was missing, and the bug it did not catch.**

    `_render_master` computed `source_category` correctly and the construction site that
    turns a master item into a row simply never read the key, so every skill persisted
    NULL and the exported Skills block stayed flat. The previous version of this test
    built its `ResumeVersionItem` rows by hand — feeding the double from someone who had
    read the code — which proved the composition groups a snapshot and skipped the one
    line that drops it.

    So this drives `run_tailoring` through a scripted seam (no provider, no key) and
    asserts the **rows the database actually holds**.
    """
    seeded = await _seed(db_session, "persisted")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(seeded.bullet_ids[0])],
            "tailor_review": [_review(90)],
        }
    )
    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(ResumeVersionItem).where(
                    ResumeVersionItem.resume_version_id == version.id,
                    ResumeVersionItem.source_kind == SourceKind.SKILL,
                )
            )
        ).all()

    assert rows, "no skill rows were persisted — this gate would examine nothing"
    stored = {row.final_text: row.source_category for row in rows}
    assert stored == {"Python": "Programming Languages", "PostgreSQL": "Databases"}, (
        f"the category was dropped between the master item and the row: {stored}"
    )


async def test_persisted_categories_are_a_frozen_snapshot(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Editing the profile afterwards must not reshape a document already produced.

    The whole reason the category is a column rather than a live lookup: an approved
    document must re-render to the bytes its checksum was recorded over (FR-023).
    """
    seeded = await _seed(db_session, "frozen")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(seeded.bullet_ids[0])],
            "tailor_review": [_review(90)],
        }
    )
    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    # The owner refiles every skill after the version exists.
    async with session_factory() as session:
        for skill in (
            await session.scalars(select(Skill).where(Skill.profile_id == seeded.profile.id))
        ).all():
            skill.category = "Reorganised After The Fact"
        await session.commit()

    async with session_factory() as session:
        reloaded = await session.scalar(select(ResumeVersion).where(ResumeVersion.id == version.id))
        assert reloaded is not None
        await session.refresh(reloaded, ["items"])
        document = _compose(reloaded, None)

    skills = next(s for s in document.sections if s.heading == "Skills")
    lines = [line for group in skills.groups for line in group.lines]
    assert "Programming Languages: Python" in lines
    assert "Databases: PostgreSQL" in lines
    assert not any("Reorganised After The Fact" in line for line in lines), (
        "composition followed a profile edit; the category is being read live"
    )
