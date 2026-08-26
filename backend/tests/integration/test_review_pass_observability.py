"""Per-pass review observability (T093).

`state.findings` accumulates across review passes, but until this task the
entries carried no pass label — `run_tailoring` stamped every persisted
`ReviewerFinding` with the run's **final** attempt, and `state.confidence` had
no reducer, so each review pass overwrote the last. A fabrication caught on the
first review and fixed on the second was indistinguishable from one raised at
the end, and the first pass's confidence was destroyed in state, upstream of
anything that could persist it.

The label is attached where the graph's review node appends to state — the one
place that knows which pass is running — and **never** in the model-facing
schema, which the provider fills and has no honest basis to know the attempt.

The four runs recorded before this task keep their stamped values exactly as
persisted: the per-pass information was destroyed before persistence, and
reconstructing it would be inference presented as record (HANDOFF §2a).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.domain.models import ResumeVersion, ReviewerFinding, RunStatus, TailoringRun
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

# Distinct details, so a persisted row maps back to the pass that raised it by
# content rather than by anything the implementation might get wrong.
FIRST_PASS_OVERSTATED = "'Owned' where the profile says 'led'."
FIRST_PASS_UNCOVERED = "Kubernetes is never addressed."
SECOND_PASS_UNCOVERED = "Kubernetes is still not addressed."


def _plan() -> dict[str, object]:
    return {
        "emphasise": [
            {
                "what": "Six years owning a payments platform",
                "serves_requirement": "5+ years backend services",
            }
        ],
        "de_emphasise": [],
        "protected_gaps": [],
        "strategy": "Lead with platform ownership at scale.",
    }


def _draft(bullet_id: uuid.UUID, text: str) -> dict[str, object]:
    return {
        "items": [
            {
                "source_item_id": str(bullet_id),
                "source_kind": "experience_bullet",
                "position": 0,
                "included": True,
                "text": text,
                "reason": "Leads with the posting's primary requirement.",
            }
        ]
    }


def _review(confidence: int, findings: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {"confidence": confidence, "findings": findings or []}


def _one_revision_script(bullet: uuid.UUID) -> dict[str, list[dict[str, object]]]:
    """First review objects twice at confidence 40; the revised draft clears at
    88 with one remaining concern. One revision, two review passes."""
    return {
        "tailor_plan": [_plan()],
        "tailor_draft": [_draft(bullet, "First attempt, overstated.")],
        "tailor_revise": [_draft(bullet, "Second attempt, accurate.")],
        "tailor_review": [
            _review(
                40,
                [
                    {
                        "kind": "overstated",
                        "source_item_id": str(bullet),
                        "detail": FIRST_PASS_OVERSTATED,
                        "quoted_text": "First attempt, overstated.",
                    },
                    {"kind": "uncovered", "detail": FIRST_PASS_UNCOVERED},
                ],
            ),
            _review(88, [{"kind": "uncovered", "detail": SECOND_PASS_UNCOVERED}]),
        ],
    }


async def test_each_finding_carries_the_review_pass_that_raised_it(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A run with one revision: the first review's findings are stamped with the
    first pass and the second review's with the second — not every row with the
    run's final attempt, which is the exact defect this task fixes."""
    seeded = await seed_tailorable(db_session, sub="pass-attempt", email="pass-attempt@example.com")
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=_one_revision_script(bullet)),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    # A fresh session, so nothing here reads the identity map that wrote it.
    async with session_factory() as session:
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None
        assert run.status == RunStatus.SUCCEEDED
        # The run-level total keeps its meaning: one revision happened.
        assert run.attempts == 1

        findings = (
            (
                await session.execute(
                    select(ReviewerFinding).where(ReviewerFinding.tailoring_run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
        # The count gate first: a stamping assertion over zero rows passes
        # forever, and that class of false gate has shipped four times.
        assert len(findings) == 3, f"expected 3 persisted findings, found {len(findings)}"

        by_detail = {f.detail: f.attempt for f in findings}
        assert by_detail == {
            FIRST_PASS_OVERSTATED: 0,
            FIRST_PASS_UNCOVERED: 0,
            SECOND_PASS_UNCOVERED: 1,
        }, (
            "each finding must carry the review pass that raised it; a uniform "
            f"value means the run's final attempt was stamped on every row: {by_detail}"
        )


async def test_every_review_passes_confidence_is_preserved_in_order(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Both passes' confidence values survive, distinguishable and ordered, and
    the version's confidence keeps its existing meaning — the final pass."""
    seeded = await seed_tailorable(
        db_session, sub="pass-confidence", email="pass-confidence@example.com"
    )
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=_one_revision_script(seeded.bullet_ids[0])),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None
        # Two review passes ran; the count gate before the content.
        assert run.review_confidences is not None
        assert len(run.review_confidences) == 2
        assert run.review_confidences == [40, 88]

        reloaded = await session.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert reloaded.confidence_score == 88, (
            "the version's confidence must still mean the final review's judgement"
        )


async def test_a_first_pass_clear_run_stamps_its_single_pass(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """No revision: the one review pass is pass zero, on every finding it
    raised, and the confidence record holds exactly one value."""
    seeded = await seed_tailorable(db_session, sub="pass-clean", email="pass-clean@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [_draft(seeded.bullet_ids[0], "Accurate first time.")],
                    "tailor_review": [
                        # Clears: no ungrounded finding and confidence >= 70.
                        # The concern still persists, and must carry its pass.
                        _review(90, [{"kind": "uncovered", "detail": FIRST_PASS_UNCOVERED}])
                    ],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None
        assert run.attempts == 0

        findings = (
            (
                await session.execute(
                    select(ReviewerFinding).where(ReviewerFinding.tailoring_run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(findings) == 1, f"expected 1 persisted finding, found {len(findings)}"
        assert findings[0].attempt == 0

        assert run.review_confidences == [90]
