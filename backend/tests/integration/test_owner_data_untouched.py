"""FR-011 and FR-021 — tailoring reads owner data and writes none of it.

**Constitution Principle II is non-negotiable**, and this is the only thing that
checks it. `/speckit-analyze` found the requirement had no coverage at all,
which is the pattern worth naming: feature work generates obvious tasks,
"nothing changed" does not. Nobody reviews a diff looking for a write that
should not be there.

Every owner-owned table is snapshotted and compared, rather than a chosen few.
A test that names three tables silently stops covering the fourth the day
someone adds it — and the profile has twelve.

Three outcomes are checked, because they take different code paths through the
use case and only one of them is the happy one. A failing run reaches the
exception handler; an abandoned one reaches the reaper.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.domain.models import RunStatus, TailoringRun
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

#: Everything the owner owns. Tailoring may read all of it and write none of it.
#:
#: `match_analyses` and `match_requirements` are here because FR-011 is the same
#: rule one step out: slice 004's calibration is measured over the history of
#: those rows, so a tailoring run that touched one would corrupt a measurement
#: nobody would think to re-check.
OWNER_TABLES = (
    "contact_information",
    "professional_titles",
    "summary_blocks",
    "work_experiences",
    "experience_bullets",
    "skills",
    "projects",
    "education",
    "certifications",
    "languages",
    "military_service",
    "volunteer_experiences",
    "match_analyses",
    "match_requirements",
)


async def _snapshot(session: AsyncSession) -> dict[str, list[tuple]]:
    """Every row of every owner-owned table, ordered so the comparison is stable."""
    snapshot: dict[str, list[tuple]] = {}
    for table in OWNER_TABLES:
        rows = (await session.execute(text(f"SELECT * FROM {table} ORDER BY id"))).all()  # noqa: S608
        snapshot[table] = [tuple(row) for row in rows]
    return snapshot


def _assert_identical(before: dict[str, list[tuple]], after: dict[str, list[tuple]]) -> None:
    changed = [table for table in before if before[table] != after[table]]
    assert changed == [], (
        f"tailoring modified owner-owned data in {changed}. "
        "Constitution Principle II: AI must not modify user-owned professional "
        "data without explicit approval, and approval happens after this point."
    )


def _plan() -> dict[str, object]:
    return {
        "emphasise": [{"what": "Platform ownership", "serves_requirement": "5+ years backend"}],
        "de_emphasise": [],
        "protected_gaps": [],
        "strategy": "Lead with scale.",
    }


def _draft(bullet_id, text_: str = "Owned the payments platform.") -> dict:
    return {
        "items": [
            {
                "source_item_id": str(bullet_id),
                "source_kind": "experience_bullet",
                "position": 0,
                "included": True,
                "text": text_,
                "reason": "Leads with the posting's requirement.",
            }
        ]
    }


async def test_a_successful_run_touches_no_owner_data(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    seeded = await seed_tailorable(db_session, sub="untouched-ok", email="ok@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        before = await _snapshot(session)

    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(seeded.bullet_ids[0])],
            "tailor_review": [{"confidence": 92, "findings": []}],
        }
    )
    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        _assert_identical(before, await _snapshot(session))


async def test_a_failed_run_touches_no_owner_data(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The path through the exception handler.

    A partial write that is then abandoned is the most likely way this rule
    breaks in practice, and the least likely to be noticed — the run reports a
    failure, so nobody looks at what it left behind.
    """
    seeded = await seed_tailorable(db_session, sub="untouched-fail", email="fail@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        before = await _snapshot(session)

    # Invalid output: `emphasise` must be non-empty, so the plan node's
    # validation fails and the run never reaches drafting.
    seam = ScriptedSeam(script={"tailor_plan": [{"emphasise": [], "strategy": ""}]})
    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        run = await session.get(TailoringRun, version.tailoring_run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED
        _assert_identical(before, await _snapshot(session))


async def test_reaping_an_abandoned_run_touches_no_owner_data(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The path through the reaper, which runs on the *next* request rather
    than inside a run — the one place where cleanup code touches rows nobody is
    currently looking at."""
    seeded = await seed_tailorable(db_session, sub="untouched-reap", email="reap@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        before = await _snapshot(session)
        await session.execute(
            update(TailoringRun)
            .where(TailoringRun.resume_version_id == version.id)
            .values(started_at=datetime.now(UTC) - timedelta(hours=4))
        )
        await session.commit()

    async with session_factory() as session:
        application = await session.get(type(seeded.application), seeded.application.id)
        assert application is not None
        # Reaps the stalled run and reserves a fresh version.
        await create_pending_version(session, application)
        await session.commit()

    async with session_factory() as session:
        _assert_identical(before, await _snapshot(session))
