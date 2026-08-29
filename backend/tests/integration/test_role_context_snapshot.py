"""T051 — role context is snapshotted onto the version, and never read live.

**The claim this file exists to hold.** A version freezes its items so a later profile
edit cannot change an approved document (Principle IV, FR-023). Role context is part of
the document, so it has to be frozen with everything else — otherwise a locked `EXPORTED`
or `SUBMITTED` version would re-render differently after the owner renamed a job, changing
a document underneath its own recorded checksum.

`test_a_locked_version_re_renders_identically_after_a_profile_edit` is the drill for that,
and it is the one test here that fails if anybody reintroduces a live profile read.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.export_resume import _compose
from careerhq.application.tailor_resume import _render_master
from careerhq.domain.models import (
    ExperienceBullet,
    ResumeVersion,
    ResumeVersionItem,
    SourceKind,
    VersionStatus,
    WorkExperience,
)
from careerhq.infrastructure.documents.render import render_resume_pdf
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


async def test_the_master_projection_carries_role_context(db_session: AsyncSession) -> None:
    """**The gap T051 closed, at its source.**

    `_render_master` builds both the prompt and the dicts `run_tailoring` turns into
    version rows. The role already reached the *prompt* — `ROLE: <title> at <company>` —
    and was deliberately not an item, so it never reached the version and the exporter had
    nothing to render. It is now carried on the item dicts as well.

    Asserted here rather than through `run_tailoring`, which would bill a real graph run.
    """
    seeded = await seed_tailorable(db_session, sub="t051-snapshot", email="t051a@example.com")
    _, items = await _render_master(db_session, seeded.profile.id)

    bullets = [i for i in items if i["source_kind"] == SourceKind.EXPERIENCE_BULLET]
    assert bullets, "the fixture seeds experience bullets"
    for item in bullets:
        assert item["role_employer"] == "Payments Co"
        assert item["role_title"] == "Staff Engineer"
        assert item["role_start_date"] == "2019"
        assert item["role_ordinal"] is not None

    # Null is correct for a skill: it has no role, and a value would be invented.
    for skill in (i for i in items if i["source_kind"] == SourceKind.SKILL):
        assert "role_employer" not in skill or skill["role_employer"] is None


async def test_roles_are_projected_in_profile_ordinal_order(db_session: AsyncSession) -> None:
    """There was **no `order_by`** on the work-experience query, so role order was
    whatever Postgres returned. It now follows `ordinal`, the profile's own order field —
    which is the number the export groups by."""
    seeded = await seed_tailorable(db_session, sub="t051-order", email="t051e@example.com")
    first = await db_session.scalar(sa.select(WorkExperience))
    assert first is not None
    first.ordinal = 5

    second = WorkExperience(
        profile_id=seeded.profile.id,
        company="Earlier Co",
        title="Junior Engineer",
        start_date="2015",
        ordinal=1,
        source="EXTRACTED",
    )
    db_session.add(second)
    await db_session.flush()
    db_session.add(
        ExperienceBullet(experience_id=second.id, text="Earlier work.", source="EXTRACTED")
    )
    await db_session.flush()

    _, items = await _render_master(db_session, seeded.profile.id)
    ordinals = [
        i["role_ordinal"] for i in items if i["source_kind"] == SourceKind.EXPERIENCE_BULLET
    ]
    assert ordinals == sorted(ordinals), f"roles projected out of ordinal order: {ordinals}"
    assert ordinals[0] == 1, "the earlier role must come first"


async def _version_with_snapshot(db_session: AsyncSession, seeded: object) -> ResumeVersion:
    """A version whose items carry role context, built the way `run_tailoring` builds
    them — from `_render_master`'s dicts — without paying for a graph run."""
    _, items = await _render_master(db_session, seeded.profile.id)  # type: ignore[attr-defined]
    version = ResumeVersion(
        profile_id=seeded.profile.id,  # type: ignore[attr-defined]
        application_id=seeded.application.id,  # type: ignore[attr-defined]
        source_resume_profile_id=seeded.master.id,  # type: ignore[attr-defined]
        source_profile_updated_at=seeded.profile.updated_at,  # type: ignore[attr-defined]
        name="Senior Backend Engineer — tailored",
        status=VersionStatus.EXPORTED,
        items=[],
    )
    db_session.add(version)
    await db_session.flush()
    for master_item in items:
        db_session.add(
            ResumeVersionItem(
                resume_version_id=version.id,
                source_kind=master_item["source_kind"],
                source_item_id=master_item["source_item_id"],
                position=master_item["position"],
                original_text=master_item["text"],
                final_text=master_item["text"],
                decision="accepted",
                included=True,
                role_employer=master_item.get("role_employer"),
                role_title=master_item.get("role_title"),
                role_start_date=master_item.get("role_start_date"),
                role_end_date=master_item.get("role_end_date"),
                role_ordinal=master_item.get("role_ordinal"),
            )
        )
    await db_session.flush()
    return version


async def _reload(db_session: AsyncSession, version_id: object) -> ResumeVersion:
    db_session.expunge_all()
    loaded = await db_session.get(
        ResumeVersion, version_id, options=[sa.orm.selectinload(ResumeVersion.items)]
    )
    assert loaded is not None
    return loaded


async def test_a_locked_version_re_renders_identically_after_a_profile_edit(
    db_session: AsyncSession,
) -> None:
    """**The Principle IV drill, and the reason the snapshot exists.**

    The version is `EXPORTED`, so its content is frozen. Renaming the job afterwards must
    change nothing about that document — not its text, not its bytes, not its checksum. A
    live profile read would produce different bytes, and the recorded checksum would then
    describe a document that no longer renders.
    """
    seeded = await seed_tailorable(db_session, sub="t051-frozen", email="t051c@example.com")
    version = await _version_with_snapshot(db_session, seeded)

    before = render_resume_pdf(_compose(await _reload(db_session, version.id), None))

    role = await db_session.scalar(sa.select(WorkExperience))
    assert role is not None
    role.company = "Renamed Employer Ltd"
    role.title = "Principal Engineer"
    role.ordinal = 99
    await db_session.flush()

    reloaded = await _reload(db_session, version.id)
    after = render_resume_pdf(_compose(reloaded, None))

    assert after == before, (
        "a locked version re-rendered differently after a profile edit — role context is "
        "being read live instead of from the version's snapshot"
    )
    experience = next(s for s in _compose(reloaded, None).sections if s.heading == "Experience")
    assert experience.groups[0].role is not None
    assert experience.groups[0].role.employer == "Payments Co", "the snapshot must win"


async def test_a_version_predating_the_snapshot_still_exports(db_session: AsyncSession) -> None:
    """**Backward compatibility against the real situation**: six versions exist with NULL
    role context, one of them submitted. Nulling the columns reproduces exactly that row
    shape, and the document must still render with every approved line present."""
    seeded = await seed_tailorable(db_session, sub="t051-legacy", email="t051d@example.com")
    version = await _version_with_snapshot(db_session, seeded)

    await db_session.execute(
        sa.update(ResumeVersionItem)
        .where(ResumeVersionItem.resume_version_id == version.id)
        .values(
            role_employer=None,
            role_title=None,
            role_start_date=None,
            role_end_date=None,
            role_ordinal=None,
        )
    )
    await db_session.flush()

    document = _compose(await _reload(db_session, version.id), None)
    experience = next(s for s in document.sections if s.heading == "Experience")

    assert len(experience.groups) == 1
    assert experience.groups[0].role is None, "no role context must mean no invented role"
    assert experience.groups[0].lines, "the approved lines must survive"
    assert render_resume_pdf(document), "a legacy version must still render"
