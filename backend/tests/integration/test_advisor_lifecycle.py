"""The SC-002 walk: understanding evolves with evidence (T027, US2).

Run 1 creates three memories; the history then moves in three directions;
run 2 confirms one (fresh delta, frozen evidence untouched), supersedes one
(lineage link, old row readable), retires one (reason recorded), and the
disposition log covers every pre-run-2 active memory exactly once.

Then the two failure arms:
* the omission drill — a reasoning output that forgets one active memory
  fails the run with the omission named, and nothing is synthesised
  (invariant 1);
* the A2 arm — a run whose seam raises leaves the existing memory set
  **byte-for-byte** unchanged (full row serialisation compared, not counts)
  while still recording its reason and cost (SC-005 on the run that matters:
  the one with memories at stake).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.advise_career import create_pending_run, run_advisor
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    AdvisorRun,
    CareerMemory,
    Company,
    MemoryDisposition,
    NormalizedStatus,
    User,
    normalize_company_name,
)
from tests.support.advisor_seam import (
    FailingAdvisorSeam,
    ParsedPrompt,
    PromptReadingAdvisorSeam,
)

pytestmark = pytest.mark.asyncio

_REJECTION = "outcome.rejection_rate.global"
_APPLIED = "status.distribution.applied"
_WISHLIST = "status.distribution.wishlist"


async def _seed(session: AsyncSession) -> User:
    sub = f"lifecycle-{uuid.uuid4().hex[:10]}"
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Lifecycle"}
    )
    company = Company(
        user_id=user.id, name="Seeded", normalized_name=normalize_company_name("Seeded")
    )
    session.add(company)
    await session.flush()
    statuses = [
        NormalizedStatus.REJECTED,
        NormalizedStatus.REJECTED,
        NormalizedStatus.APPLIED,
        NormalizedStatus.APPLIED,
        NormalizedStatus.WISHLIST,
    ]
    for index, status in enumerate(statuses):
        application = Application(
            user_id=user.id,
            company_id=company.id,
            job_title=f"Role {index}",
            status=status.value.title(),
            normalized_status=status,
        )
        application.date_added = datetime.now(UTC) - timedelta(days=60 + index)
        session.add(application)
    await session.flush()
    return user


def _run1_answer(task: str, parsed: ParsedPrompt) -> dict[str, Any]:
    def claim(fact_id: str, template: str) -> dict[str, Any]:
        num, den = parsed.facts[fact_id]
        return {
            "claim": template.format(num=num, den=den),
            "kind": "pattern_" + fact_id.replace(".", "_"),
            "scope_kind": "global",
            "cited_fact_ids": [fact_id],
            "tentative": False,
        }

    return {
        "created": [
            claim(_REJECTION, "{num} of {den} applications ended rejected"),
            claim(_APPLIED, "{num} of {den} applications are in flight as applied"),
            claim(_WISHLIST, "{num} of {den} applications sit unactioned on the wishlist"),
        ],
        "dispositions": [],
    }


def _serialise_memories(rows: list[CareerMemory]) -> list[tuple]:  # type: ignore[type-arg]
    """Every column that exists — the byte-for-byte comparison A2 requires."""
    return sorted(
        (
            str(m.id),
            m.claim,
            m.kind,
            m.scope_kind,
            m.scope_value,
            str(m.evidence),
            m.priority,
            m.priority_reason,
            str(m.status),
            str(m.supersedes_id),
            str(m.recreates_dismissed_id),
            m.retired_reason,
            m.created_at.isoformat(),
            m.last_confirmed_at.isoformat(),
        )
        for m in rows
    )


async def _execute(session_factory, user: User, answer) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with session_factory() as session:
        fresh = await session.get(User, user.id)
        run = await create_pending_run(session, fresh)
        assert run is not None
        await session.commit()
        run_id = run.id
    seam = PromptReadingAdvisorSeam(answer=answer)
    async with session_factory() as session:
        await run_advisor(session, run_id=run_id, completion=seam)
        await session.commit()
    return run_id


async def test_the_lifecycle_walk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _seed(session)
        await session.commit()
        user_id = user.id
    await _execute(session_factory, user, _run1_answer)

    # -- the world moves: two more rejections land ---------------------------
    async with session_factory() as session:
        company_id = (
            await session.scalars(
                select(Company.id).where(Company.user_id == user_id)
            )
        ).first()
        for index in range(2):
            application = Application(
                user_id=user_id,
                company_id=company_id,
                job_title=f"Late role {index}",
                status="Rejected",
                normalized_status=NormalizedStatus.REJECTED,
            )
            application.date_added = datetime.now(UTC) - timedelta(days=3)
            session.add(application)
        await session.commit()

    async with session_factory() as session:
        rows = list(
            (await session.scalars(select(CareerMemory).where(CareerMemory.user_id == user_id))).all()
        )
        rejection = next(m for m in rows if "rejected" in m.claim)
        applied = next(m for m in rows if "in flight" in m.claim)
        wishlist = next(m for m in rows if "wishlist" in m.claim)
        frozen_before = dict(rejection.evidence)
        confirmed_at_before = rejection.last_confirmed_at
        active_before_run2 = {str(m.id) for m in rows if m.status in ("active", "tentative")}
        assert len(active_before_run2) == 3

    def run2_answer(task: str, parsed: ParsedPrompt) -> dict[str, Any]:
        num, den = parsed.facts[_REJECTION]
        return {
            "created": [
                {
                    "claim": f"now {num} of {den} applications ended rejected — the rate moved",
                    "kind": "pattern_status",
                    "scope_kind": "global",
                    "cited_fact_ids": [_REJECTION],
                    "tentative": False,
                }
            ],
            "dispositions": [
                {
                    "memory_id": str(rejection.id),
                    "action": "confirm",
                    "fresh_fact_ids": [_REJECTION],
                },
                {
                    "memory_id": str(applied.id),
                    "action": "supersede",
                    "superseding_index": 0,
                },
                {
                    "memory_id": str(wishlist.id),
                    "action": "retire",
                    "reason": "the wishlist share stopped being a pattern worth tracking",
                },
            ],
        }

    run2_id = await _execute(session_factory, user, run2_answer)

    async with session_factory() as session:
        rows = list(
            (await session.scalars(select(CareerMemory).where(CareerMemory.user_id == user_id))).all()
        )
        confirmed = next(m for m in rows if m.id == rejection.id)
        superseded = next(m for m in rows if m.id == applied.id)
        retired = next(m for m in rows if m.id == wishlist.id)
        replacement = next(m for m in rows if m.supersedes_id == applied.id)

        # Confirmed: date advanced, frozen evidence byte-identical.
        assert confirmed.status == "active"
        assert confirmed.last_confirmed_at > confirmed_at_before
        assert confirmed.evidence == frozen_before

        # Superseded: forward transition, content intact, lineage links back.
        assert superseded.status == "superseded"
        assert "in flight" in superseded.claim
        assert replacement.status == "active"
        assert "4 of 7" in replacement.claim  # 4 rejected of 7 — recomputed evidence

        # Retired: the reason travels.
        assert retired.status == "retired"
        assert retired.retired_reason and "wishlist" in retired.retired_reason

        # The journal covers every pre-run-2 active memory exactly once,
        # plus the creation entry.
        dispositions = list(
            (
                await session.scalars(
                    select(MemoryDisposition).where(MemoryDisposition.run_id == run2_id)
                )
            ).all()
        )
        by_action = {str(d.memory_id): str(d.action) for d in dispositions if d.action != "created"}
        assert set(by_action) == active_before_run2
        assert sorted(by_action.values()) == ["confirmed", "retired", "superseded"]
        delta = next(d for d in dispositions if str(d.action) == "confirmed").evidence_delta
        assert delta and delta["facts"][0]["numerator"] == 4

        # -- run 3a: the omission drill (invariant 1) ------------------------
        actives_now = [m for m in rows if m.status in ("active", "tentative")]
        assert len(actives_now) == 2

    def omitting_answer(task: str, parsed: ParsedPrompt) -> dict[str, Any]:
        return {
            "created": [],
            "dispositions": [
                {
                    "memory_id": parsed.memory_ids[0],
                    "action": "confirm",
                    "fresh_fact_ids": [_REJECTION],
                }
                # …and the second active memory is simply forgotten.
            ],
            "nothing_found_reason": "forgot one on purpose",
        }

    async with session_factory() as session:
        snapshot_rows = list(
            (await session.scalars(select(CareerMemory).where(CareerMemory.user_id == user_id))).all()
        )
        before_bytes = _serialise_memories(snapshot_rows)

    run3_id = await _execute(session_factory, user, omitting_answer)

    async with session_factory() as session:
        run3 = await session.get(AdvisorRun, run3_id)
        assert run3 is not None and run3.status == "failed"
        assert run3.error == "The reasoning step returned an incomplete answer."
        after_rows = list(
            (await session.scalars(select(CareerMemory).where(CareerMemory.user_id == user_id))).all()
        )
        assert _serialise_memories(after_rows) == before_bytes, (
            "an omission must fail the run and synthesise nothing"
        )

    # -- run 3b: the A2 arm — a raising seam, byte-for-byte unchanged --------
    async with session_factory() as session:
        fresh = await session.get(User, user_id)
        run4 = await create_pending_run(session, fresh)
        assert run4 is not None
        await session.commit()
        run4_id = run4.id

    async with session_factory() as session:
        await run_advisor(session, run_id=run4_id, completion=FailingAdvisorSeam())
        await session.commit()

    async with session_factory() as session:
        run4_row = await session.get(AdvisorRun, run4_id)
        assert run4_row is not None
        assert run4_row.status == "failed"
        assert run4_row.cost == Decimal("0.007"), "the failed run still records its spend"
        after_rows = list(
            (await session.scalars(select(CareerMemory).where(CareerMemory.user_id == user_id))).all()
        )
        assert _serialise_memories(after_rows) == before_bytes, (
            "SC-005: a failed run leaves the memory set byte-for-byte unchanged"
        )
