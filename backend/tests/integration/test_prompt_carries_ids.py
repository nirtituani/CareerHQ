"""The ids the workflow demands back must be in the prompt it sends.

**This is the invariant both real provider failures violated**, and neither the
suite nor a code review caught it, because every scripted fixture was handed the
ids by a test author who already knew the mapping.

`_render_master` returns two things: a text rendering for the prompt, and a list
of items carrying their database ids. Only the text went into the prompt. So the
Draft node was instructed to return the items it changed *by id* while being
shown no ids at all — 2,801 characters of profile and zero UUIDs. It could not
comply, returned nulls, and the Reviewer then had nothing to copy either.

The louder consequence was a `ValidationError` on the Reviewer's findings. The
quieter one was worse: with no ids, **no drafted item maps back to a master
item**, so a run that passed review would have persisted a diff with zero
proposed changes — a tailoring feature that silently does nothing.

So the tests here deliberately never write an id by hand. They read them out of
the prompt, exactly as a model must.
"""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.agents.tailoring.prompts import build_draft_prompt, build_review_prompt
from careerhq.application.agents.tailoring.state import TailoringState
from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import (
    _render_master,
    create_pending_version,
    run_tailoring,
)
from careerhq.domain.models import ResumeVersion, ResumeVersionItem, VersionStatus
from careerhq.domain.schemas.tailoring import DraftedItem
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

#: The marker every proposable line carries. A model copies from this.
_ID = re.compile(r"\[id: ([0-9a-f-]{36})\]")


def _ids_in(prompt: str) -> set[str]:
    return set(_ID.findall(prompt))


async def test_every_master_item_id_appears_in_the_draft_prompt(
    db_session: AsyncSession,
) -> None:
    """The gate. If an id is not in the prompt, no model can return it."""
    seeded = await seed_tailorable(db_session, sub="ids-draft", email="ids-draft@example.com")

    master_text, items = await _render_master(db_session, seeded.profile.id)
    required = {str(item["source_item_id"]) for item in items}
    assert required, "the fixture must have something to tailor"

    prompt = build_draft_prompt(
        TailoringState(job={"title": "x"}, master=master_text, match={}, plan={"strategy": "y"})
    )

    missing = required - _ids_in(prompt)
    assert not missing, (
        f"{len(missing)} of {len(required)} master item ids never reach the Draft node, "
        "which is asked to return the items it changed by id"
    )


async def test_the_reviewer_sees_the_ids_it_is_told_to_copy(
    db_session: AsyncSession,
) -> None:
    """The second link in the same chain.

    The Reviewer is told to copy `source_item_id` from the draft it is shown. If
    the draft carries nulls, that instruction asks it to copy a null — which is
    precisely what produced two `overstated` findings with no item and killed the
    second real run.
    """
    seeded = await seed_tailorable(db_session, sub="ids-review", email="ids-review@example.com")
    master_text, items = await _render_master(db_session, seeded.profile.id)
    a_real_id = items[0]["source_item_id"]

    state = TailoringState(
        job={"title": "x"},
        master=master_text,
        match={},
        items=[
            DraftedItem(
                source_item_id=a_real_id,
                source_kind="experience_bullet",
                position=0,
                text="Rewritten.",
                reason="Because.",
            )
        ],
    )

    assert str(a_real_id) in build_review_prompt(state)


async def test_ids_read_out_of_the_prompt_map_back_to_their_master_items(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """End to end, with the double reading the prompt instead of being told.

    Every previous fixture hardcoded `source_item_id=str(bullet_id)`, handed over
    by a test author who knew the mapping. That proves the plumbing works when
    ids are supplied and never once checks that a model *can* supply them —
    which is exactly how two paid runs were spent discovering it could not.

    This seam behaves like a model: it is given a prompt, it finds the ids in it,
    and it answers with one. If the ids are not in the prompt it produces
    nothing, and the assertions below fail.
    """
    seeded = await seed_tailorable(db_session, sub="ids-map", email="ids-map@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    rewritten = "Rewritten from an id the model found in its own prompt."

    class _ReadsThePrompt:
        """Answers only from what it was shown."""

        def __init__(self) -> None:
            self.chosen: str | None = None

        async def complete(self, *, task: str, schema: object, prompt: str) -> object:
            from decimal import Decimal

            from careerhq.application.ports import Completion, Usage

            found = sorted(_ids_in(prompt))
            payload: dict[str, object]
            if task == "tailor_plan":
                payload = {
                    "emphasise": [
                        {
                            "action": "keep",
                            "what": "Platform ownership",
                            "serves_requirement": "backend",
                        }
                    ],
                    "de_emphasise": [],
                    "protected_gaps": [],
                    "strategy": "Lead with the platform work.",
                }
            elif task == "tailor_draft":
                assert found, "the draft prompt carried no ids for a model to return"
                self.chosen = found[0]
                payload = {
                    "items": [
                        {
                            "source_item_id": self.chosen,
                            "source_kind": "experience_bullet",
                            "position": 0,
                            "included": True,
                            "text": rewritten,
                            "reason": "Serves the posting's first requirement.",
                        }
                    ]
                }
            else:
                # The Reviewer copies an id out of the draft it was shown, the
                # way the real one is instructed to.
                assert self.chosen and self.chosen in prompt
                payload = {
                    "confidence": 84,
                    "findings": [
                        {
                            "kind": "overstated",
                            "source_item_id": self.chosen,
                            "detail": "Slightly stronger than the profile states.",
                            "quoted_text": rewritten[:20],
                        }
                    ],
                }
            return Completion(
                value=schema.model_validate(payload),  # type: ignore[attr-defined]
                usage=Usage(
                    model="double", input_tokens=10, output_tokens=5, cost=Decimal("0.001")
                ),
            )

    seam = _ReadsThePrompt()
    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=seam,  # type: ignore[arg-type]
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    assert seam.chosen is not None

    async with session_factory() as session:
        reloaded = await session.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert reloaded.status == VersionStatus.AWAITING_APPROVAL

        rows = (
            await session.scalars(
                select(ResumeVersionItem).where(ResumeVersionItem.resume_version_id == version.id)
            )
        ).all()

        # The proposal landed on the master row the model named, and on no other.
        proposed = [row for row in rows if row.proposed_text is not None]
        assert len(proposed) == 1, "the drafted item did not map back to its master item"
        assert str(proposed[0].source_item_id) == seam.chosen
        assert proposed[0].proposed_text == rewritten
        assert proposed[0].final_text == rewritten

        # And the Reviewer's finding attached to that same row.
        await session.refresh(proposed[0], ["findings"])
        assert [f.kind for f in proposed[0].findings] == ["overstated"]


async def test_a_fabricated_id_changes_nothing_and_is_reported(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """An id that names no master item must not quietly disappear.

    It cannot reach the resume — the mapping is keyed by real master ids — so
    nothing fabricated is ever persisted. But a proposal silently vanishing is
    indistinguishable from a model that proposed nothing, and the two need very
    different responses from whoever is reading the logs.
    """
    seeded = await seed_tailorable(db_session, sub="ids-fake", email="ids-fake@example.com")
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    invented = str(uuid.uuid4())

    class _Invents:
        async def complete(self, *, task: str, schema: object, prompt: str) -> object:
            from decimal import Decimal

            from careerhq.application.ports import Completion, Usage

            payload: dict[str, object]
            if task == "tailor_plan":
                payload = {
                    "emphasise": [{"action": "keep", "what": "x", "serves_requirement": "y"}],
                    "de_emphasise": [],
                    "protected_gaps": [],
                    "strategy": "s",
                }
            elif task == "tailor_draft":
                payload = {
                    "items": [
                        {
                            "source_item_id": invented,
                            "source_kind": "experience_bullet",
                            "position": 0,
                            "included": True,
                            "text": "A claim against an item that does not exist.",
                            "reason": "r",
                        }
                    ]
                }
            else:
                payload = {"confidence": 90, "findings": []}
            return Completion(
                value=schema.model_validate(payload),  # type: ignore[attr-defined]
                usage=Usage(model="d", input_tokens=1, output_tokens=1, cost=Decimal("0")),
            )

    async with session_factory() as session:
        await run_tailoring(
            session,
            version_id=version.id,
            completion=_Invents(),  # type: ignore[arg-type]
            guidelines=StaticGuidelines(),
        )
        await session.commit()

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(ResumeVersionItem).where(ResumeVersionItem.resume_version_id == version.id)
            )
        ).all()
        assert rows, "the version still holds the master's own items"
        assert all(row.proposed_text is None for row in rows)
        assert all(str(row.source_item_id) != invented for row in rows)
