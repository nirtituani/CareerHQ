"""What the persistence layer records about a proposal's position (T095).

`position` holds the proposed value when a proposal arrives and the master's
value when none does, which meant the master's ordering was destroyed for
exactly the items the Draft touched. `displaced_position` records what the
proposal displaced, so the master's ordering at creation is
`COALESCE(displaced_position, position)` for **every** item — the FR-030
obligation that is currently unmet for any item carrying a proposal.

NULL means no proposal arrived. Nothing is backfilled: rows written before the
column existed keep NULL and are read as unknown, never as untouched.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import (
    _render_master,
    create_pending_version,
    run_tailoring,
)
from careerhq.domain.models import ResumeVersionItem
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


def _plan() -> dict[str, object]:
    return {
        "emphasise": [{"what": "Lead with platform ownership", "serves_requirement": "5+ years"}],
        "de_emphasise": [],
        "protected_gaps": [],
        "strategy": "Lead with platform ownership.",
    }


def _review(confidence: int = 90) -> dict[str, object]:
    return {"confidence": confidence, "findings": []}


def _revert(item_id: uuid.UUID, position: int) -> dict[str, object]:
    """A revision that drops the claim and keeps the placement it proposed."""
    return {
        "items": [
            {
                "source_item_id": str(item_id),
                "source_kind": "experience_bullet",
                "position": position,
                "included": True,
            }
        ]
    }


async def _items(
    session_factory: async_sessionmaker[AsyncSession], version_id: uuid.UUID
) -> dict[str, ResumeVersionItem]:
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ResumeVersionItem).where(
                        ResumeVersionItem.resume_version_id == version_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return {str(row.source_item_id): row for row in rows}


async def _master_positions(
    session_factory: async_sessionmaker[AsyncSession], profile_id: uuid.UUID
) -> dict[str, int]:
    """The master's own ordering, from the same walk the prompt is built from.

    Read from the renderer rather than from the version, because version items
    do not exist until `run_tailoring` writes them — there is no "before".
    """
    async with session_factory() as session:
        _, items = await _render_master(session, profile_id)
        return {str(item["source_item_id"]): int(item["position"]) for item in items}


async def test_a_position_only_proposal_records_the_position_it_displaced(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The Voyantis shape: `text` null, a new position, nothing else. Before this
    task the row was indistinguishable from one the Draft never named."""
    seeded = await seed_tailorable(db_session, sub="pos-only", email="pos-only@example.com")
    moved, untouched = seeded.bullet_ids[0], seeded.bullet_ids[1]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    master = await _master_positions(session_factory, seeded.profile.id)
    master_position = master[str(moved)]

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [
                        {
                            "items": [
                                {
                                    "source_item_id": str(moved),
                                    "source_kind": "experience_bullet",
                                    "position": master_position + 5,
                                    "included": True,
                                }
                            ]
                        }
                    ],
                    "tailor_review": [_review()],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    rows = await _items(session_factory, version.id)
    assert len(rows) == len(master) > 0, (
        f"expected every master item persisted, found {len(rows)} of {len(master)}"
    )

    row = rows[str(moved)]
    assert row.proposed_text is None, "a position-only proposal carries no text"
    assert row.position == master_position + 5, "the proposed position is what the resume uses"
    assert row.displaced_position == master_position, (
        "the master position it displaced must be recorded, or a reorder is "
        "indistinguishable from an item the draft never named (T095)"
    )

    other = rows[str(untouched)]
    assert other.displaced_position is None, (
        "an item no proposal named must record no displaced position"
    )


async def test_coalesce_reconstructs_the_master_position_for_every_item(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-030: the version records the state of the master at creation, and
    ordering is part of that state. `COALESCE(displaced_position, position)`
    must reproduce it for items the draft moved *and* items it left alone."""
    seeded = await seed_tailorable(db_session, sub="coalesce", email="coalesce@example.com")
    moved = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    master = await _master_positions(session_factory, seeded.profile.id)

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [
                        {
                            "items": [
                                {
                                    "source_item_id": str(moved),
                                    "source_kind": "experience_bullet",
                                    "position": 31,
                                    "included": True,
                                    "text": "Rewritten and moved.",
                                    "reason": "Leads with the posting's requirement.",
                                }
                            ]
                        }
                    ],
                    "tailor_review": [_review()],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    rows = await _items(session_factory, version.id)
    assert len(rows) == len(master) > 0, (
        f"expected every master item persisted, found {len(rows)} of {len(master)}"
    )
    reconstructed = {
        item_id: (row.displaced_position if row.displaced_position is not None else row.position)
        for item_id, row in rows.items()
    }
    assert reconstructed == master, (
        "COALESCE(displaced_position, position) must reproduce the master ordering "
        "for every item, including the one the draft moved"
    )
    assert rows[str(moved)].position == 31, "and the resume still uses the proposed position"


async def test_a_dropped_item_records_that_a_proposal_arrived(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    seeded = await seed_tailorable(db_session, sub="drop-pos", email="drop-pos@example.com")
    dropped = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    master = await _master_positions(session_factory, seeded.profile.id)
    master_position = master[str(dropped)]

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [
                        {
                            "items": [
                                {
                                    "source_item_id": str(dropped),
                                    "source_kind": "experience_bullet",
                                    "position": master_position,
                                    "included": False,
                                }
                            ]
                        }
                    ],
                    "tailor_review": [_review()],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    row = (await _items(session_factory, version.id))[str(dropped)]
    assert row.included is False
    assert row.displaced_position == master_position, (
        "a drop is a proposal arriving, and must record that it did"
    )


async def test_a_discarded_ungrounded_proposal_still_records_the_action(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`finalise` nulls the text and leaves the position. The proposal still
    arrived, and the record of the attempt is what makes the guardrail visible."""
    seeded = await seed_tailorable(db_session, sub="disc-pos", email="disc-pos@example.com")
    invented = seeded.bullet_ids[0]
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    master = await _master_positions(session_factory, seeded.profile.id)
    master_position = master[str(invented)]

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=ScriptedSeam(
                script={
                    "tailor_plan": [_plan()],
                    "tailor_draft": [
                        {
                            "items": [
                                {
                                    "source_item_id": str(invented),
                                    "source_kind": "experience_bullet",
                                    "position": master_position + 2,
                                    "included": True,
                                    "text": "Invented a qualification.",
                                    "reason": "Serves the posting.",
                                }
                            ]
                        }
                    ],
                    # An `ungrounded` finding fails review regardless of
                    # confidence, so the workflow revises. The reviser drops the
                    # claim and keeps the placement it proposed.
                    # `findings` accumulates across passes and `clears_review`
                    # scans the whole list, so a pass-0 `ungrounded` can never
                    # be cleared: the run always spends the full budget. Both
                    # revisions are scripted for that reason.
                    "tailor_revise": [_revert(invented, master_position + 2)],
                    "tailor_revise_escalated": [_revert(invented, master_position + 2)],
                    "tailor_review": [
                        {
                            "confidence": 90,
                            "findings": [
                                {
                                    "kind": "ungrounded",
                                    "source_item_id": str(invented),
                                    "detail": "The profile contains no such qualification.",
                                    "quoted_text": "Invented a qualification.",
                                }
                            ],
                        },
                        _review(),
                        _review(),
                    ],
                }
            ),
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    row = (await _items(session_factory, version.id))[str(invented)]
    assert row.proposed_text is None, "the fabrication was discarded"
    assert row.final_text == row.original_text, "and the owner's wording stands"
    assert row.displaced_position == master_position, (
        "but the attempt still happened, and the record of it must survive"
    )
