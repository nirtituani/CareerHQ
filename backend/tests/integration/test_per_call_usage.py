"""Per-call usage persistence (T092).

`tailoring_runs` stores totals, and totals cannot answer the question a real
failure asked: run `cd27b092` was billed $0.36 across several calls and the
record could not say which node spent it, whether the escalated revision ran,
or what the call that failed had already cost. Each `complete()` call a run
makes is therefore persisted as its own labelled row — on the failure path too,
because the calls a failed run made were billed whether or not the run
finished.

Driven end to end through `run_tailoring` with scripted seams, never a
provider (FR-045).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.ports import Completion, Usage
from careerhq.application.tailor_resume import create_pending_version, run_tailoring
from careerhq.domain.models import (
    ResumeVersion,
    RunStatus,
    TailoringRun,
    TailoringRunCall,
    VersionStatus,
)
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

# -- script fragments, the same shapes test_tailoring_workflow.py drives ------


def _plan() -> dict[str, object]:
    return {
        "emphasise": [
            {
                "action": "keep",
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


def _draft(bullet_id: uuid.UUID, text: str) -> dict:
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


async def _rows_for(
    session: AsyncSession, version_id: uuid.UUID
) -> tuple[TailoringRun, list[TailoringRunCall]]:
    run = await session.scalar(
        select(TailoringRun).where(TailoringRun.resume_version_id == version_id)
    )
    assert run is not None
    rows = (
        (
            await session.execute(
                select(TailoringRunCall)
                .where(TailoringRunCall.tailoring_run_id == run.id)
                .order_by(TailoringRunCall.sequence)
            )
        )
        .scalars()
        .all()
    )
    return run, list(rows)


async def test_a_successful_run_persists_one_labelled_record_per_call(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The full seven-call revision budget, one row each, in call order.

    The escalated revision appears under its own task name — the breakdown is
    what makes "the escalation ran and this is what it cost" answerable from
    the record, which totals never could.
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

    assert seam.call_count == 7, "the workflow under test must actually have made seven calls"

    async with session_factory() as session:
        run, rows = await _rows_for(session, version.id)
        assert run.status == RunStatus.SUCCEEDED

        # The count first: a gate examining zero rows passes forever.
        assert len(rows) == 7, f"seven calls were made; {len(rows)} records persisted"

        assert [row.task for row in rows] == [
            "tailor_plan",
            "tailor_draft",
            "tailor_review",
            "tailor_revise",
            "tailor_review",
            "tailor_revise_escalated",
            "tailor_review",
        ], "each record must carry the task that made the call, in call order"
        assert [row.sequence for row in rows] == list(range(7))

        for row in rows:
            assert row.model == f"scripted/{row.task}"
            assert row.input_tokens == seam.input_tokens
            assert row.output_tokens == seam.output_tokens
            assert row.cost == seam.cost_per_call
            assert row.is_fixture is False

        # The rows and the totals are two representations of the same bill.
        assert run.input_tokens == sum(row.input_tokens for row in rows)
        assert run.output_tokens == sum(row.output_tokens for row in rows)
        assert run.cost == sum((row.cost for row in rows), start=Decimal("0"))


class _BilledFailure(RuntimeError):
    """Stands in for `ExtractionFailedError`: billed, then failed validation."""

    def __init__(self, usage: Usage) -> None:
        super().__init__("the model's output failed validation")
        self.usage = usage


@dataclass
class _FailsBilledAt:
    """Delegates to a script until `fail_task`, which is billed and then raises.

    This is run `cd27b092`'s shape exactly: real calls succeeded, one more was
    paid for and returned something unusable, and the graph never returned.
    """

    inner: ScriptedSeam
    fail_task: str
    billed: Usage

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        if task == self.fail_task:
            raise _BilledFailure(self.billed)
        return await self.inner.complete(task=task, schema=schema, prompt=prompt)


async def test_a_run_that_raises_still_persists_the_calls_it_was_billed_for(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Plan and draft succeed, review is billed and fails: three rows, not zero.

    The failed call's own row carries what *it* was billed — distinct numbers,
    so a sum that happened to match could not fake it — and `is_fixture` is
    per call: the one marked call is marked, the two real ones are not.
    """
    seeded = await seed_tailorable(db_session)
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    inner = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(seeded.bullet_ids[0], "Attempt one.")],
        }
    )
    seam = _FailsBilledAt(
        inner=inner,
        fail_task="tailor_review",
        billed=Usage(
            model="scripted/tailor_review",
            input_tokens=4_000,
            output_tokens=222,
            cost=Decimal("0.054321"),
            is_fixture=True,
        ),
    )

    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        run, rows = await _rows_for(session, version.id)
        assert run.status == RunStatus.FAILED
        version_row = await session.get(ResumeVersion, version.id)
        assert version_row is not None
        assert version_row.status == VersionStatus.DRAFT

        assert len(rows) == 3, (
            f"three calls were billed before the run died; {len(rows)} records persisted. "
            "A failed run must keep the itemised record of what it spent (T092)"
        )
        assert [row.task for row in rows] == ["tailor_plan", "tailor_draft", "tailor_review"]

        failed_call = rows[2]
        assert failed_call.input_tokens == 4_000
        assert failed_call.output_tokens == 222
        assert failed_call.cost == Decimal("0.054321")
        assert [row.is_fixture for row in rows] == [False, False, True], (
            "is_fixture is tracked per call, not smeared across the run"
        )

        # The totals still agree with the itemised rows on the failure path.
        assert run.input_tokens == 1_000 + 1_000 + 4_000
        assert run.cost == Decimal("0.02") + Decimal("0.054321")
        assert run.is_fixture is True


async def test_a_call_that_never_reached_the_provider_gets_no_row(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A transport-style failure carrying no usage was never billed.

    Inventing a zero-token row for it would make the call count wrong in the
    other direction — the recorder's rule, proved here all the way down to the
    table.
    """
    seeded = await seed_tailorable(db_session)
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    # The script covers plan and draft only; the review call raises
    # ScriptExhausted, which carries no `.usage` — a call that died before the
    # provider's accounting saw it.
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [_draft(seeded.bullet_ids[0], "Attempt one.")],
        }
    )

    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        run, rows = await _rows_for(session, version.id)
        assert run.status == RunStatus.FAILED
        assert len(rows) == 2, (
            f"two calls were billed, the third never reached the provider; "
            f"{len(rows)} records persisted"
        )
        assert [row.task for row in rows] == ["tailor_plan", "tailor_draft"]
        assert run.cost == Decimal("0.02")
