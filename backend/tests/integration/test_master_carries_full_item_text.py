"""T057 — Education, Certification, Project and Language items keep their content (T043).

**The defect is invisibility, not brevity.** `_render_master` built these items as
`(row.id, row.institution)`, `(row.id, row.name)` and `(row.id, row.name)`, so a
profile holding `qualification = "B.Sc. in Computer Science"` reached the model as
the single word *"Ben-Gurion University"*. The credential was not shortened — it
was **never shown**. The agent cannot emphasise what it is never shown, and AI-008
forbids it inventing one.

**This is the sharpest evidence T057 works and it costs nothing.** No model call,
no benchmark, no paid arm: the master block either contains the qualification or it
does not, and that is a deterministic property of a pure rendering function. The
benchmark's much weaker job is only to show the change did not *hurt* anything.

**Written before the fix and watched failing** — the master rendered
`"Ben-Gurion University"` with no degree anywhere in it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.tailor_resume import _render_master
from careerhq.domain.models.profile import Certification, Education, Language, Project

pytestmark = pytest.mark.asyncio


async def _profile(session: AsyncSession) -> uuid.UUID:
    """A scratch profile on an `@example.com` user.

    Never the real profile: a test seeded against it has already merged a
    fictional CV into it once and replaced the contact block.
    """
    from tests.support.tailoring_fixtures import seed_tailorable

    seeded = await seed_tailorable(session, sub="google-t057", email="t057@example.com")
    return seeded.profile.id


async def test_an_education_item_carries_the_qualification_and_the_field(
    db_session: AsyncSession,
) -> None:
    profile_id = await _profile(db_session)
    db_session.add(
        Education(
            profile_id=profile_id,
            institution="Ben-Gurion University",
            qualification="B.Sc. in Computer Science",
            field_of_study="Computer Science",
            start_date="2014",
            end_date="2017",
            grade="87",
        )
    )
    await db_session.flush()

    text, items = await _render_master(db_session, profile_id)

    assert "B.Sc. in Computer Science" in text, (
        "the degree is what a recruiter reads and what the agent may emphasise; "
        f"the master block said only: {text!r}"
    )
    assert "Ben-Gurion University" in text, "the institution must not be lost to the fix"
    education = [i for i in items if i["source_kind"].value == "education"]
    assert len(education) == 1
    assert "B.Sc. in Computer Science" in education[0]["text"], (
        "the item's own text is what a proposal is made against and what the export "
        "renders — putting the degree only in the prompt would fix half of it"
    )


async def test_a_language_item_carries_its_proficiency(db_session: AsyncSession) -> None:
    profile_id = await _profile(db_session)
    db_session.add(Language(profile_id=profile_id, name="Hebrew", proficiency="Native"))
    await db_session.flush()

    text, items = await _render_master(db_session, profile_id)

    assert "Hebrew" in text
    assert "Native" in text, f"proficiency is the whole information content: {text!r}"
    language = [i for i in items if i["source_kind"].value == "language"]
    assert len(language) == 1
    assert "Native" in language[0]["text"]


async def test_a_certification_item_carries_its_issuer_and_year(
    db_session: AsyncSession,
) -> None:
    profile_id = await _profile(db_session)
    db_session.add(Certification(profile_id=profile_id, name="CKA", issuer="CNCF", year="2022"))
    await db_session.flush()

    text, _ = await _render_master(db_session, profile_id)

    assert "CKA" in text
    assert "CNCF" in text, "an unattributed certification name is not a credential"
    assert "2022" in text


async def test_a_project_item_carries_its_description(db_session: AsyncSession) -> None:
    profile_id = await _profile(db_session)
    db_session.add(
        Project(
            profile_id=profile_id,
            name="pgvector-bench",
            description="Benchmarks approximate-nearest-neighbour recall against exact search.",
            url="https://example.com/pgvector-bench",
        )
    )
    await db_session.flush()

    text, _ = await _render_master(db_session, profile_id)

    assert "pgvector-bench" in text
    assert "approximate-nearest-neighbour" in text, (
        "a project name alone tells the model nothing it can tailor against"
    )


async def test_a_row_with_only_its_required_field_still_renders(
    db_session: AsyncSession,
) -> None:
    """The composition adds nothing it was not given.

    Every optional column is genuinely optional, and a profile carrying only an
    institution must render exactly that — not a separator, not an empty field,
    and not a placeholder.
    """
    profile_id = await _profile(db_session)
    db_session.add(Education(profile_id=profile_id, institution="Open University"))
    await db_session.flush()

    text, items = await _render_master(db_session, profile_id)

    education = [i for i in items if i["source_kind"].value == "education"]
    assert education[0]["text"] == "Open University"
    assert "·" not in text.split("EDUCATION:")[1].split("\n")[0]
