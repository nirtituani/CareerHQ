"""The tailoring loop, driven end to end without a provider (FR-045).

Every path here exists because it is the one a green suite would otherwise miss.
Slice 004 shipped nine defects under a passing suite, and the pattern was always
the same: the branch was never exercised, so nothing was ever wrong.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from careerhq.application.finalisation_rules import FINALISATION_RULES_VERSION
from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.domain.models import (
    ProposalDecision,
    ResumeVersion,
    ReviewerFinding,
    RunStatus,
    TailoringRun,
    VersionStatus,
)
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


def _plan() -> dict[str, object]:
    return {
        "emphasise": [
            {
                "what": "Six years owning a payments platform",
                "serves_requirement": "5+ years backend services",
            }
        ],
        "de_emphasise": [],
        "protected_gaps": [
            {
                "requirement": "Kubernetes in production",
                "why_protected": "The profile mentions containers but never Kubernetes.",
            }
        ],
        "strategy": "Lead with platform ownership at scale.",
    }


def _draft(bullet_id: uuid.UUID, text: str = "Owned the payments platform for six years.") -> dict:
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


def _review(confidence: int, findings: list[dict] | None = None) -> dict:
    return {"confidence": confidence, "findings": findings or []}


async def test_a_draft_that_clears_review_first_time_makes_three_calls(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Plan, draft, review. No revision, and nothing left running."""
    seeded = await seed_tailorable(db_session)
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

    assert seam.tasks_called == ["tailor_plan", "tailor_draft", "tailor_review"]

    async with session_factory() as session:
        reloaded = await session.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert reloaded.status == VersionStatus.AWAITING_APPROVAL
        assert reloaded.confidence_score == 90

        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None
        assert run.status == RunStatus.SUCCEEDED
        assert run.attempts == 0
        assert run.finished_at is not None
        assert run.finalisation_rules_version == FINALISATION_RULES_VERSION


async def test_one_revision_then_clears_and_the_second_draft_is_what_persists(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Five calls, and the revised wording is the one stored."""
    seeded = await seed_tailorable(db_session)
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    seam = ScriptedSeam(
        script={
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
                            "detail": "'Owned' where the profile says 'led'.",
                            "quoted_text": "First attempt, overstated.",
                        }
                    ],
                ),
                _review(88),
            ],
        }
    )

    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    assert seam.call_count == 5
    assert seam.tasks_called.count("tailor_review") == 2
    assert "tailor_revise" in seam.tasks_called

    async with session_factory() as session:
        version_row = await session.get(ResumeVersion, version.id)
        assert version_row is not None
        items = (
            await session.execute(select(ResumeVersion).where(ResumeVersion.id == version.id))
        ).scalar_one()
        assert version_row.confidence_score == 88
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == items.id)
        )
        assert run is not None
        assert run.attempts == 1


async def test_the_full_revision_budget_escalates_and_still_finalises(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Seven calls, the second revision on the escalated task, and a finished run.

    Exhausting the budget is a **normal exit**, not an error (FR-013). The
    escalation is proved by the task *name*, which is what keeps docs/08 §3.2.3
    in configuration rather than in workflow code.
    """
    seeded = await seed_tailorable(db_session)
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    overstated = [
        {
            "kind": "overstated",
            "source_item_id": str(bullet),
            "detail": "Still stronger than the profile supports.",
            "quoted_text": "Owned the payments platform for six years.",
        }
    ]
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(bullet, "Attempt one.")],
            "tailor_revise": [_draft(bullet, "Attempt two.")],
            "tailor_revise_escalated": [_draft(bullet, "Attempt three.")],
            "tailor_review": [
                _review(30, overstated),
                _review(45, overstated),
                _review(50, overstated),
            ],
        }
    )

    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    assert seam.call_count == 7
    assert seam.tasks_called == [
        "tailor_plan",
        "tailor_draft",
        "tailor_review",
        "tailor_revise",
        "tailor_review",
        "tailor_revise_escalated",
        "tailor_review",
    ]

    async with session_factory() as session:
        reloaded = await session.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert reloaded.status == VersionStatus.AWAITING_APPROVAL, (
            "a draft that never cleared review still reaches the owner, flagged"
        )
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None
        assert run.attempts == 2
        assert run.status == RunStatus.SUCCEEDED


async def test_usage_accumulates_across_every_call(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Research R3, as an assertion rather than a comment.

    A state key with no append reducer is **overwritten**, so this would record
    one call's tokens instead of seven — an incomplete audit trail and a cost
    figure wrong by 7x, with nothing raising. It would read as a cheap run.
    """
    seeded = await seed_tailorable(db_session)
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    finding = [
        {
            "kind": "overstated",
            "source_item_id": str(bullet),
            "detail": "Overstated.",
            "quoted_text": "Attempt.",
        }
    ]
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(bullet, "Attempt.")],
            "tailor_revise": [_draft(bullet, "Attempt.")],
            "tailor_revise_escalated": [_draft(bullet, "Attempt.")],
            "tailor_review": [_review(10, finding), _review(20, finding), _review(30, finding)],
        },
        input_tokens=1_000,
        output_tokens=500,
    )

    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None
        assert run.input_tokens == 7 * 1_000, "usage must sum across all seven calls, not the last"
        assert run.output_tokens == 7 * 500
        assert run.cost == 7 * seam.cost_per_call


async def test_an_ungrounded_claim_never_reaches_a_row(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-018 and FR-046 — the release blocker of this slice.

    The proposal must be absent from **every** row, the owner's wording must
    stand, and the finding must survive as evidence the guardrail ran.
    """
    seeded = await seed_tailorable(db_session)
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    fabrication = "Ran production Kubernetes clusters for four years."
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(bullet, fabrication)],
            "tailor_revise": [_draft(bullet, fabrication)],
            "tailor_revise_escalated": [_draft(bullet, fabrication)],
            "tailor_review": [
                _review(
                    95,
                    [
                        {
                            "kind": "ungrounded",
                            "source_item_id": str(bullet),
                            "detail": "The profile never mentions Kubernetes.",
                            "quoted_text": fabrication,
                        }
                    ],
                )
            ]
            * 3,
        }
    )

    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        version_row = await session.get(ResumeVersion, version.id)
        assert version_row is not None
        items = list(
            (
                await session.execute(
                    select(ResumeVersion)
                    .where(ResumeVersion.id == version.id)
                    .options(selectinload(ResumeVersion.items))
                )
            )
            .unique()
            .scalar_one()
            .items
        )
        for item in items:
            assert item.proposed_text != fabrication
            assert item.final_text != fabrication
            assert fabrication not in (item.final_text or "")

        target = next(i for i in items if i.source_item_id == bullet)
        assert target.final_text == "Led the payments platform team for six years.", (
            "the owner's own wording must stand where a claim was discarded"
        )

        findings = (
            (
                await session.execute(
                    select(ReviewerFinding)
                    .join(TailoringRun)
                    .where(TailoringRun.resume_version_id == version.id)
                )
            )
            .scalars()
            .all()
        )
        assert any(f.kind == "ungrounded" for f in findings), (
            "the finding is the evidence the guardrail ran; discarding it too "
            "makes a caught fabrication indistinguishable from none"
        )


async def test_guidelines_used_are_persisted_with_their_sources(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-016. Redundant-looking now; the only thing that makes slice 007's
    retrieval-quality metric measurable once the source is retrieval."""
    seeded = await seed_tailorable(db_session)
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
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None
        assert run.guidelines_used, "the run must record the guidance it actually used"
        assert all("text" in g and "source" in g for g in run.guidelines_used)
        assert run.plan is not None, "the plan is a persisted artifact, not a transient"


async def test_rejecting_every_proposal_yields_the_master(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """SC-005. A valid outcome that must save without error.

    Also the cheapest end-to-end proof that rejection restores the owner's
    wording rather than leaving the proposal in place.
    """
    from careerhq.application.tailor_resume import approve_version, decide_item

    seeded = await seed_tailorable(db_session)
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(seeded.bullet_ids[0], "A rewritten bullet.")],
            "tailor_review": [_review(90)],
        }
    )

    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        loaded = (
            (
                await session.execute(
                    select(ResumeVersion)
                    .where(ResumeVersion.id == version.id)
                    .options(selectinload(ResumeVersion.items))
                )
            )
            .unique()
            .scalar_one()
        )
        for item in loaded.items:
            await decide_item(session, item=item, decision=ProposalDecision.REJECTED)
        await approve_version(session, version=loaded)
        await session.commit()

    async with session_factory() as session:
        loaded = (
            (
                await session.execute(
                    select(ResumeVersion)
                    .where(ResumeVersion.id == version.id)
                    .options(selectinload(ResumeVersion.items))
                )
            )
            .unique()
            .scalar_one()
        )
        assert loaded.status == VersionStatus.READY
        for item in loaded.items:
            assert item.final_text == item.original_text, (
                "rejecting every proposal must leave the master's content exactly"
            )


@pytest.mark.parametrize(
    ("node", "script"),
    [
        # `emphasise` has min_length=1, so an empty plan fails validation.
        ("plan", {"tailor_plan": [{"emphasise": [], "strategy": ""}]}),
        # `items` has min_length=1.
        ("draft", {"tailor_draft": [{"items": []}]}),
        # `confidence` is bounded 0-100.
        ("review", {"tailor_review": [{"confidence": 500, "findings": []}]}),
    ],
)
async def test_invalid_model_output_fails_the_run_at_any_node(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    node: str,
    script: dict,
) -> None:
    """FR-006 and FR-037 — a provider can return anything, and often does.

    The seam raises rather than returning partial data, so the interesting
    question is what the *use case* leaves behind. A run that half-wrote its
    items and then failed would leave a version showing proposals nobody
    reviewed, which is the one thing worse than no version at all.
    """
    seeded = await seed_tailorable(db_session, sub=f"bad-{node}", email=f"bad-{node}@example.com")
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    # Everything up to the failing node succeeds, so each parametrisation
    # reaches a different point in the graph.
    full = {
        "tailor_plan": [_plan()],
        "tailor_draft": [_draft(bullet)],
        "tailor_review": [_review(90)],
    }
    full.update(script)

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script=full),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        reloaded = (
            (
                await session.execute(
                    select(ResumeVersion)
                    .where(ResumeVersion.id == version.id)
                    .options(selectinload(ResumeVersion.items))
                )
            )
            .unique()
            .scalar_one()
        )
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None

        assert run.status == RunStatus.FAILED
        assert run.failure_reason, "a failure must record why (FR-006)"
        assert run.finished_at is not None, "a failed run is finished, not still going"

        assert reloaded.status == VersionStatus.DRAFT, (
            "a failed run returns the version to draft — there is no `failed` status"
        )
        assert reloaded.failure_reason
        assert reloaded.items == [], (
            "no partial items may survive a failed run; the owner would be shown "
            "proposals that were never reviewed"
        )


async def test_a_failed_run_can_be_retried(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-007. The partial index only holds for `tailoring` and `reviewing`, so
    a version back at `draft` does not block the retry that recovers it."""
    seeded = await seed_tailorable(db_session, sub="retry", email="retry@example.com")
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(script={"tailor_plan": [{"emphasise": [], "strategy": ""}]}),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        application = await session.get(type(seeded.application), seeded.application.id)
        assert application is not None
        retried = await create_pending_version(session, application)
        await session.commit()
        retried_id = retried.id

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=retried_id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [_draft(bullet)],
                    "tailor_review": [_review(93)],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        reloaded = await session.get(ResumeVersion, retried_id)
        assert reloaded is not None
        assert reloaded.status == VersionStatus.AWAITING_APPROVAL
        assert reloaded.confidence_score == 93
