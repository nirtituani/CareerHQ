"""The tailoring loop, driven end to end without a provider (FR-045).

Every path here exists because it is the one a green suite would otherwise miss.
Slice 004 shipped nine defects under a passing suite, and the pattern was always
the same: the branch was never exercised, so nothing was ever wrong.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from careerhq.application.finalisation_rules import FINALISATION_RULES_VERSION
from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.ports import Usage
from careerhq.application.tailor_resume import (
    approve_version,
    create_pending_version,
    decide_item,
    run_tailoring,
)
from careerhq.domain.models import (
    Application,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    ReviewerFinding,
    RunStatus,
    SourceKind,
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


async def test_a_draft_drop_survives_a_revise_that_does_not_mention_it(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T094 — the confirmed Zipher-style failure, at the persistence layer.

    `_REVISE` rule 4 instructs "Return only the items you are changing", so a
    Reviser that touches one rewrite never re-emits the Draft's drops. Run
    `6356fb4e` persisted 35/35 items included while one of its own findings
    praised a drop that existed nowhere in the version. The drop — and every
    Draft decision the Reviser does not mention — must survive to the rows.
    """
    seeded = await seed_tailorable(db_session)
    rewritten, dropped = seeded.bullet_ids
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    drop_item = {
        "source_item_id": str(dropped),
        "source_kind": "experience_bullet",
        "position": 1,
        "included": False,
    }
    draft = _draft(rewritten, "Owned the payments platform end to end.")
    draft["items"].append(drop_item)

    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [draft],
            "tailor_revise": [_draft(rewritten, "Led the payments platform for six years.")],
            "tailor_review": [
                _review(
                    40,
                    [
                        {
                            "kind": "overstated",
                            "source_item_id": str(rewritten),
                            "detail": "'Owned' where the profile says 'led'.",
                            "quoted_text": "Owned the payments platform end to end.",
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

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ResumeVersionItem).where(
                        ResumeVersionItem.resume_version_id == version.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows, "the run must have persisted version rows to examine"

        identities = [(row.source_kind, row.source_item_id) for row in rows]
        assert len(identities) == len(set(identities)), (
            "the merge must never produce two rows for one (kind, source id)"
        )

        dropped_row = next(r for r in rows if r.source_item_id == dropped)
        assert dropped_row.included is False, (
            "the Draft dropped this bullet and the Reviser never mentioned it; "
            "an included row here means the Revise output replaced the Draft "
            "instead of merging over it"
        )

        revised_row = next(r for r in rows if r.source_item_id == rewritten)
        assert revised_row.proposed_text == "Led the payments platform for six years."
        assert revised_row.final_text == "Led the payments platform for six years."


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


async def test_a_fabrication_fixed_by_revision_survives_as_a_normal_proposal(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The other half of FR-018, and the one the discard rule got wrong.

    An `ungrounded` finding describes **the draft the Reviewer read**, not the
    item for all time. When the Reviser fixes the claim and the final review
    clears the result, the corrected wording is a legitimate proposal and must
    reach the owner with the ordinary controls — the same reasoning T096
    applied to the revision gate (`active_findings`): the final pass is a
    complete statement about the document as it now stands.

    Before the fix, `run_tailoring` handed `finalise` the findings of **every**
    pass, so the stale pass-0 finding discarded the fixed revision: the item
    persisted with `proposed_text` NULL and rendered as "Withdrawn before
    saving" with nothing to decide. Every real ungrounded finding in the dev
    database at the time (4/4) had exactly this shape — raised on pass 0, run
    revised and cleared, fix thrown away.

    The pass-0 finding must still persist, stamped with its pass: it is the
    evidence the guardrail ran, and hiding it would make a caught fabrication
    indistinguishable from none.
    """
    seeded = await seed_tailorable(db_session)
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    fabrication = "Shipped 0-to-1 products under real ambiguity."
    fixed = "Built backend services with Python and FastAPI."
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(bullet, fabrication)],
            "tailor_revise": [_draft(bullet, fixed)],
            "tailor_review": [
                _review(
                    95,
                    [
                        {
                            "kind": "ungrounded",
                            "source_item_id": str(bullet),
                            "detail": "Nothing in the profile describes ambiguity.",
                            "quoted_text": fabrication,
                        }
                    ],
                ),
                # The revision cleared: no findings at all.
                _review(90),
            ],
        }
    )

    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        row = (
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
        target = next(i for i in row.items if i.source_item_id == bullet)
        assert target.proposed_text == fixed, (
            "the final review cleared the revision, so the fixed wording is a "
            "legitimate proposal — a stale pass-0 finding must not discard it"
        )
        assert target.final_text == fixed
        assert target.decision == ProposalDecision.PENDING

        # The fabrication itself is still nowhere.
        for item in row.items:
            assert fabrication not in (item.proposed_text or "")
            assert fabrication not in (item.final_text or "")

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
        caught = [f for f in findings if f.kind == "ungrounded"]
        assert len(caught) == 1 and caught[0].attempt == 0, (
            "the pass-0 finding remains as the audit record of the catch"
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


# -- User Story 2: what the Reviewer caught, and where it is filed ----------


async def test_findings_attach_to_their_item(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T064, FR-042. A finding must be filed against the proposal it concerns.

    The alternative — a flat list on the run — reads on screen as a banner, and
    a banner is unattributable: eleven proposals and one note saying the wording
    is stronger than the profile shows leaves a person guessing which of the
    eleven it means, or re-reading all of them.

    **`uncovered` is the exception, and it must stay one.** An unaddressed
    requirement concerns the draft as a whole; there is no item for it to point
    at. Manufacturing one would repeat slice 004's `unverified`-shortfall
    mistake exactly: demanding a structured reference the model has no honest
    basis to fill. The schema enforces it with a check constraint, so this test
    is about the *use case* obeying it rather than the database refusing.

    Re-read through a second session (FR-047), because the attachment is only
    interesting once it has survived a round trip to storage.
    """
    seeded = await seed_tailorable(db_session, sub="us2-attach", email="us2-attach@example.com")
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [_draft(bullet)],
                    "tailor_review": [
                        _review(
                            88,
                            [
                                {
                                    "kind": "overstated",
                                    "source_item_id": str(bullet),
                                    "detail": "'Owned' inflates a team lead role.",
                                    "quoted_text": "Owned the payments platform",
                                },
                                {
                                    "kind": "uncovered",
                                    "source_item_id": None,
                                    "detail": "Kubernetes is never addressed.",
                                    "quoted_text": None,
                                },
                            ],
                        )
                    ],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        reloaded = (
            await session.execute(
                select(ResumeVersion)
                .where(ResumeVersion.id == version.id)
                .options(selectinload(ResumeVersion.items))
            )
        ).scalar_one()

        # The row the proposal was made against, found by its source rather
        # than by position — position is the agent's choice and may move.
        target = next(item for item in reloaded.items if item.source_item_id == bullet)

        findings = list(
            await session.scalars(select(ReviewerFinding).order_by(ReviewerFinding.kind))
        )
        by_kind = {finding.kind: finding for finding in findings}
        assert set(by_kind) == {"overstated", "uncovered"}

        assert by_kind["overstated"].resume_version_item_id == target.id
        assert by_kind["overstated"].quoted_text == "Owned the payments platform"

        # Draft level, and it must stay there.
        assert by_kind["uncovered"].resume_version_item_id is None

        # And nothing was filed against an item that had no proposal — a
        # finding on an untouched bullet would render a note beside wording the
        # agent never suggested changing.
        untouched = [item for item in reloaded.items if item.id != target.id]
        attached = {f.resume_version_item_id for f in findings}
        assert all(item.id not in attached for item in untouched)


async def test_clean_draft_still_reports_confidence(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T065. A clean result must be visibly a result.

    The failure this guards against is not a crash: it is a run that produces no
    findings and therefore leaves `confidence_score` null, so the interface has
    nothing to show and renders the same emptiness it shows for a draft that has
    not run. "The Reviewer found nothing wrong" and "the Reviewer has not looked
    yet" would then be the same screen, which is the FR-039 conflation pointed
    at the good outcome instead of the bad one.
    """
    seeded = await seed_tailorable(db_session, sub="us2-clean", email="us2-clean@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [_draft(seeded.bullet_ids[0])],
                    # No findings at all. The whole point of the case.
                    "tailor_review": [_review(94)],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        reloaded = await session.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert reloaded.confidence_score == 94, "a clean run must still carry a score"
        assert reloaded.status == VersionStatus.AWAITING_APPROVAL

        assert (await session.scalars(select(ReviewerFinding))).all() == []


# -- User Story 3: the owner's own words ------------------------------------


async def test_edited_item_is_distinguishable(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T074, FR-027, and the spec's US3 scenarios in the order it states them.

    Reject first, *then* correct the restored wording — the case where the agent
    was wrong about **how** to say it rather than **whether** to say it, and the
    owner's own line was not right either.

    The claim being tested is that three authorships stay separable after a
    round trip to storage: the master's original, the agent's proposal, and the
    owner's replacement. Collapsing any two is how a resume ends up containing a
    sentence nobody can account for — and `user_corrected` exists on the profile
    for exactly this reason. A correction nobody can identify later is
    indistinguishable from something the machine wrote.
    """
    seeded = await seed_tailorable(db_session, sub="us3-edit", email="us3-edit@example.com")
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [_draft(bullet)],
                    "tailor_review": [_review(91)],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    owners_words = "Led the payments platform, and grew the team from three to nine."

    # Scenario 1: reject, then replace the restored text.
    async with session_factory() as session:
        item = await session.scalar(
            select(ResumeVersionItem).where(
                ResumeVersionItem.resume_version_id == version.id,
                ResumeVersionItem.source_item_id == bullet,
            )
        )
        assert item is not None
        original = item.original_text
        proposal = item.proposed_text
        assert proposal is not None and proposal != original

        await decide_item(session, item=item, decision=ProposalDecision.REJECTED)
        # Rejection restores the owner's wording and nothing else (FR-026).
        assert item.final_text == original

        await decide_item(session, item=item, decision=ProposalDecision.EDITED, text=owners_words)
        await session.commit()

    # Scenario 2: reopen. Everything below is read through a session that did
    # not write any of it (FR-047).
    async with session_factory() as session:
        reopened = await session.scalar(
            select(ResumeVersionItem).where(
                ResumeVersionItem.resume_version_id == version.id,
                ResumeVersionItem.source_item_id == bullet,
            )
        )
        assert reopened is not None

        assert reopened.final_text == owners_words
        assert reopened.decision == ProposalDecision.EDITED

        # The other two authorships survive intact beside it. Overwriting
        # `original_text` with the edit would destroy the lineage the version
        # exists to record, and overwriting `proposed_text` would erase what the
        # agent actually suggested — which is what the run is audited against.
        assert reopened.original_text == original
        assert reopened.proposed_text == proposal
        assert reopened.final_text not in (original, proposal)


def _drop(bullet_id: uuid.UUID, position: int = 1) -> dict:
    """A pure drop: no text, so no finding can ever attach to it."""
    return {
        "source_item_id": str(bullet_id),
        "source_kind": "experience_bullet",
        "position": position,
        "included": False,
    }


async def _tailored_with_drop(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[uuid.UUID, uuid.UUID]:
    """One clean run whose draft rewrites bullet 1 and drops bullet 2."""
    seeded = await seed_tailorable(db_session)
    rewritten, dropped = seeded.bullet_ids
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    draft = _draft(rewritten, "Led payments for six years, matching the posting.")
    draft["items"].append(_drop(dropped))
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [draft],
            "tailor_review": [_review(90)],
        }
    )
    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()
    return version.id, dropped


async def _drop_row(session: AsyncSession, version_id: uuid.UUID, dropped: uuid.UUID) -> Any:
    version = (
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
    return next(i for i in version.items if i.source_item_id == dropped)


async def test_rejecting_a_drop_restores_the_item_to_the_document(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A drop is a proposed change to existing content, and rejecting a
    proposal restores the owner's original state (FR-026) — which, for a master
    item, is *present with the original wording*. Restoring the text while
    leaving `included=False` would record a rejection whose line is still
    missing from the exported document.
    """
    version_id, dropped = await _tailored_with_drop(db_session, session_factory)

    async with session_factory() as session:
        row = await _drop_row(session, version_id, dropped)
        assert row.included is False and row.proposed_text is None
        await decide_item(session, item=row, decision=ProposalDecision.REJECTED, text=None)
        await session.commit()

    async with session_factory() as session:
        row = await _drop_row(session, version_id, dropped)
        assert row.decision == ProposalDecision.REJECTED
        assert row.included is True, "rejecting a removal must put the line back"
        assert row.final_text == row.original_text


async def test_accepting_a_drop_keeps_it_out_of_the_document(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    version_id, dropped = await _tailored_with_drop(db_session, session_factory)

    async with session_factory() as session:
        row = await _drop_row(session, version_id, dropped)
        await decide_item(session, item=row, decision=ProposalDecision.ACCEPTED, text=None)
        await session.commit()

    async with session_factory() as session:
        row = await _drop_row(session, version_id, dropped)
        assert row.decision == ProposalDecision.ACCEPTED
        assert row.included is False, "accepting the removal keeps the line out"


async def test_editing_a_drop_keeps_the_line_with_the_owners_words(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Editing is the owner saying "keep it, worded my way". A line cannot be
    both excluded and carry the owner's replacement text — an edit that left
    `included=False` would store words no document will ever show.
    """
    version_id, dropped = await _tailored_with_drop(db_session, session_factory)

    async with session_factory() as session:
        row = await _drop_row(session, version_id, dropped)
        await decide_item(
            session, item=row, decision=ProposalDecision.EDITED, text="Kept, in my own words."
        )
        await session.commit()

    async with session_factory() as session:
        row = await _drop_row(session, version_id, dropped)
        assert row.decision == ProposalDecision.EDITED
        assert row.included is True
        assert row.final_text == "Kept, in my own words."


async def test_blanket_approval_accepts_a_pending_drop(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-025: an untouched confirm includes every proposal not explicitly
    rejected — a pending drop among them. Legitimate only because the drop now
    renders as a decidable entry; the guarantee that it stays excluded is what
    this pins.
    """
    version_id, dropped = await _tailored_with_drop(db_session, session_factory)

    async with session_factory() as session:
        version = (
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
        await approve_version(session, version=version)
        await session.commit()

    async with session_factory() as session:
        row = await _drop_row(session, version_id, dropped)
        assert row.decision == ProposalDecision.ACCEPTED
        assert row.included is False


async def test_an_edit_with_no_text_is_refused(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T075. Both shapes of empty, refused at the use case rather than the route.

    A blank `edited` item would write an empty string into `final_text` and
    silently delete a line from the resume — no error, no proposal, no original,
    just a bullet that is gone. The route returns 422 for this, but the rule
    belongs where the write happens: slice 006's export and any later caller
    reach `decide_item` without passing through the route.
    """
    seeded = await seed_tailorable(db_session, sub="us3-blank", email="us3-blank@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [_draft(seeded.bullet_ids[0])],
                    "tailor_review": [_review(91)],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        item = await session.scalar(
            select(ResumeVersionItem).where(
                ResumeVersionItem.resume_version_id == version.id,
                ResumeVersionItem.source_item_id == seeded.bullet_ids[0],
            )
        )
        assert item is not None
        before = item.final_text

        # Absent, and present-but-whitespace. The second is the one a text field
        # actually produces.
        for text in (None, "", "   \n  "):
            with pytest.raises(ValueError):
                await decide_item(session, item=item, decision=ProposalDecision.EDITED, text=text)

        # And nothing was written on the way to raising.
        assert item.final_text == before
        assert item.decision == ProposalDecision.PENDING


async def test_a_failed_run_still_records_what_it_was_billed_for(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The accounting loss the first real run took, as a test.

    Plan and draft succeeded and were billed; review was billed and failed
    validation. The run recorded `0 tokens, $0` for all three, because usage was
    only summed from the graph's return value and the graph raised instead of
    returning.

    FR-035 requires every run to record tokens and cost. A run that reports zero
    reads as free rather than as unrecorded — which is why nobody would ever go
    looking for the missing figure.
    """
    seeded = await seed_tailorable(db_session, sub="billed", email="billed@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    class _BilledFailure(RuntimeError):
        """Shaped like `ExtractionFailedError`: it carries what it cost."""

        def __init__(self) -> None:
            super().__init__("did not validate")
            self.usage = Usage(
                model="anthropic/claude-opus-5",
                input_tokens=9_000,
                output_tokens=800,
                cost=Decimal("0.14"),
            )

    class _FailsAtReview:
        """Plan and draft answer; review is billed and rejects."""

        def __init__(self) -> None:
            self.inner = ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [_draft(seeded.bullet_ids[0])],
                },
                input_tokens=1_000,
                output_tokens=500,
                cost_per_call=Decimal("0.01"),
            )

        async def complete(self, *, task: str, schema: object, prompt: str) -> object:
            if task == "tailor_review":
                raise _BilledFailure()
            return await self.inner.complete(task=task, schema=schema, prompt=prompt)  # type: ignore[arg-type]

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=_FailsAtReview(),  # type: ignore[arg-type]
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
        )
        assert run is not None
        assert run.status == RunStatus.FAILED

        # Two successful calls at 1,000 in / 500 out, plus the billed failure.
        assert run.input_tokens == 2_000 + 9_000
        assert run.output_tokens == 1_000 + 800
        assert run.cost == Decimal("0.02") + Decimal("0.14")
        assert run.is_fixture is False


# -- retry: into the same draft, not into a pile of them --------------------


def _failing_seam() -> ScriptedSeam:
    """An empty script: the first call raises, as a provider outage does."""
    return ScriptedSeam(script={})


def _clearing_seam(bullet: uuid.UUID) -> ScriptedSeam:
    return ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(bullet)],
            "tailor_review": [_review(88)],
        }
    )


async def test_retrying_a_failed_run_reuses_the_draft(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """data-model.md, twice, in its own words.

    *"the owner can retry into the same `draft` rather than accumulating
    abandoned versions"*, and *"There is no `failed` version status. ... Its
    absence is what keeps retry simple and stops abandoned versions
    accumulating."*

    The absence of a `failed` status only buys that if retry actually reuses the
    draft. Creating a new version each time gives the owner a Versions list
    filling with identical dead drafts — the exact outcome the missing status
    was designed to prevent, arrived at by another route.
    """
    seeded = await seed_tailorable(db_session, sub="retry-reuse", email="retry-reuse@example.com")
    version = await create_pending_version(db_session, seeded.application)
    first_id = version.id
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=first_id,
            completion=_failing_seam(),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    # "Try again" is a second POST, which lands here.
    async with session_factory() as session:
        application = await session.get(Application, seeded.application.id)
        assert application is not None
        retried = await create_pending_version(session, application)
        await session.commit()
        retried_id = retried.id

    assert retried_id == first_id, "a retry must reuse the failed draft"

    async with session_factory() as session:
        versions = (
            await session.scalars(
                select(ResumeVersion).where(ResumeVersion.application_id == seeded.application.id)
            )
        ).all()
        assert len(versions) == 1, f"retry accumulated {len(versions)} versions"
        assert versions[0].status == VersionStatus.TAILORING
        # The previous attempt's explanation is gone: it describes a run that is
        # no longer the current one, and leaving it would caption a live attempt
        # with a dead one's error.
        assert versions[0].failure_reason is None


async def test_the_retry_gets_a_fresh_run_and_the_version_points_at_it(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Reuse must not mean reusing the audit record.

    A `TailoringRun` is one execution (Principle V). Overwriting the failed
    one's columns would erase the evidence of the attempt that failed, which is
    the thing FR-006 keeps. So the version is reused and the run is not — and
    `tailoring_run_id` must name the new one, or every later read reports the
    failure that is no longer current.
    """
    seeded = await seed_tailorable(db_session, sub="retry-run", email="retry-run@example.com")
    version = await create_pending_version(db_session, seeded.application)
    version_id = version.id
    first_run_id = version.tailoring_run_id
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version_id,
            completion=_failing_seam(),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        application = await session.get(Application, seeded.application.id)
        assert application is not None
        await create_pending_version(session, application)
        await session.commit()

    async with session_factory() as session:
        reloaded = await session.get(ResumeVersion, version_id)
        assert reloaded is not None
        runs = (
            await session.scalars(
                select(TailoringRun).where(TailoringRun.resume_version_id == version_id)
            )
        ).all()

        assert len(runs) == 2, "each attempt is its own execution record"
        assert reloaded.tailoring_run_id != first_run_id
        # The failed attempt survives, with its reason, for inspection.
        failed = next(r for r in runs if r.id == first_run_id)
        assert failed.status == RunStatus.FAILED
        assert failed.failure_reason


async def test_the_retry_writes_to_its_own_run_not_an_arbitrary_one(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The unordered lookup, which reuse turns from harmless into wrong.

    `run_tailoring` found its run with `scalar(select(...).where(version_id))`
    and no ordering. That was safe only because every version had exactly one
    run. The moment a retry reuses a draft there are two, and `scalar()` returns
    whichever the database hands back first — so a successful retry could write
    its plan, tokens and cost onto the **failed** run, and leave the current one
    saying `running` forever.

    The version's own `tailoring_run_id` is the authoritative pointer, and it is
    what the read must follow.
    """
    seeded = await seed_tailorable(db_session, sub="retry-ptr", email="retry-ptr@example.com")
    version = await create_pending_version(db_session, seeded.application)
    version_id = version.id
    failed_run_id = version.tailoring_run_id
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version_id,
            completion=_failing_seam(),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        application = await session.get(Application, seeded.application.id)
        assert application is not None
        retried = await create_pending_version(session, application)
        await session.commit()
        current_run_id = retried.tailoring_run_id

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version_id,
            completion=_clearing_seam(seeded.bullet_ids[0]),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        current = await session.get(TailoringRun, current_run_id)
        failed = await session.get(TailoringRun, failed_run_id)
        assert current is not None and failed is not None

        # The success landed on the current run.
        assert current.status == RunStatus.SUCCEEDED
        assert current.plan is not None
        assert current.input_tokens > 0

        # And did not overwrite the failed one's record of what happened.
        assert failed.status == RunStatus.FAILED
        assert failed.plan is None

        reloaded = await session.get(ResumeVersion, version_id)
        assert reloaded is not None
        assert reloaded.status == VersionStatus.AWAITING_APPROVAL


async def test_a_reused_draft_starts_without_the_previous_attempt_s_items(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A retry must not show a diff assembled from two runs.

    Reachable: `run_tailoring` adds item rows and flushes them, and only then
    writes findings and the run's totals. An exception in that window leaves the
    version at `draft` with rows already persisted. Retrying into it without
    clearing would render last attempt's proposals beside this attempt's, with
    nothing saying which came from where.
    """
    seeded = await seed_tailorable(db_session, sub="retry-clean", email="retry-clean@example.com")
    version = await create_pending_version(db_session, seeded.application)
    version_id = version.id
    await db_session.commit()

    # Stand in for that window: a draft carrying rows from an attempt that died.
    async with session_factory() as session:
        stale = await session.get(ResumeVersion, version_id)
        assert stale is not None
        stale.status = VersionStatus.DRAFT
        stale.failure_reason = "RuntimeError"
        session.add(
            ResumeVersionItem(
                resume_version_id=version_id,
                source_kind=SourceKind.EXPERIENCE_BULLET,
                source_item_id=seeded.bullet_ids[0],
                position=0,
                original_text="From the attempt that died.",
                proposed_text="Stale proposal.",
                final_text="Stale proposal.",
                decision=ProposalDecision.PENDING,
            )
        )
        await session.commit()

    async with session_factory() as session:
        application = await session.get(Application, seeded.application.id)
        assert application is not None
        await create_pending_version(session, application)
        await session.commit()

    async with session_factory() as session:
        items = (
            await session.scalars(
                select(ResumeVersionItem).where(ResumeVersionItem.resume_version_id == version_id)
            )
        ).all()
        assert items == [], "a retry must start from a clean draft"


async def test_an_approved_version_is_never_reused(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Only a `draft` is a retry target.

    Tailoring the same job again after approving one version is a **new
    document**, not a second attempt at the old one — and overwriting an
    approved version would destroy something the owner explicitly confirmed
    (Principle IV, FR-029).
    """
    seeded = await seed_tailorable(db_session, sub="retry-ready", email="retry-ready@example.com")
    version = await create_pending_version(db_session, seeded.application)
    first_id = version.id
    await db_session.commit()

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=first_id,
            completion=_clearing_seam(seeded.bullet_ids[0]),
            guidelines=StaticGuidelines(),
        )
        approved = await session.get(ResumeVersion, first_id)
        assert approved is not None
        await session.refresh(approved, ["items"])
        await approve_version(session, version=approved)
        await session.commit()

    async with session_factory() as session:
        application = await session.get(Application, seeded.application.id)
        assert application is not None
        second = await create_pending_version(session, application)
        await session.commit()
        assert second.id != first_id

    async with session_factory() as session:
        first = await session.get(ResumeVersion, first_id)
        assert first is not None
        assert first.status == VersionStatus.READY, "an approved version must survive untouched"


async def test_the_reviewer_judged_the_same_resume_that_was_persisted(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The composed view and the saved version must agree, item for item.

    The Reviewer now judges a resume composed in `compose_resume`; the owner
    approves rows written by `run_tailoring`. Those are two renderings of one
    decision, and nothing structural stops them diverging — a different
    inclusion rule, or `final_text` materialised from a different branch, and
    the Reviewer would be clearing a document nobody ever sees.

    So this reads the persisted rows back through a fresh session and rebuilds
    the same view from them, asserting the two match line for line.
    """
    seeded = await seed_tailorable(db_session, sub="compose-eq", email="compose-eq@example.com")
    bullet = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    rewritten = "Owned the payments platform end to end for six years."
    captured: dict[str, str] = {}

    class _CapturesTheReviewPrompt:
        """Answers the workflow, and keeps the resume the Reviewer was shown."""

        async def complete(self, *, task: str, schema: Any, prompt: str) -> Any:
            from decimal import Decimal

            from careerhq.application.ports import Completion, Usage

            payload: dict[str, Any]
            if task == "tailor_plan":
                payload = _plan()
            elif task == "tailor_draft":
                payload = _draft(bullet, rewritten)
            else:
                captured["review"] = prompt
                payload = _review(91)
            return Completion(
                value=schema.model_validate(payload),
                usage=Usage(model="d", input_tokens=1, output_tokens=1, cost=Decimal("0")),
            )

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=_CapturesTheReviewPrompt(),  # type: ignore[arg-type]
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    assert "review" in captured

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(ResumeVersionItem).where(ResumeVersionItem.resume_version_id == version.id)
            )
        ).all()
        assert rows

        # **Scoped to the composed section, not the whole prompt.** The master
        # is also in that prompt and contains every unchanged line, so searching
        # the whole thing passes whether or not the composition works — which is
        # this project's recurring "assert an absence against the right scope"
        # mistake, and it survived the first drill of this very test.
        shown = captured["review"].split("## The resulting resume")[1].split("## What to report")[0]

        divergent = [row.final_text for row in rows if row.included and row.final_text not in shown]
        assert not divergent, (
            f"{len(divergent)} persisted lines were never shown to the Reviewer: {divergent[:2]}"
        )

        # And specifically the rewritten one, as the proposal rather than the
        # original — the Reviewer must not have cleared wording that was replaced.
        changed = next(row for row in rows if row.source_item_id == bullet)
        assert changed.final_text == rewritten
        assert changed.original_text not in shown
