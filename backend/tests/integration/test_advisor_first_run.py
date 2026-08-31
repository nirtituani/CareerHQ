"""US1 end to end: a first run turns history into grounded memories (T016/T017).

The double reads every id and figure out of the rendered prompt (testing rule
4). The SC-001 audit at the bottom recomputes each persisted memory's frozen
facts from the database rows the evidence names — and asserts how many
memories it audited, so an empty audit cannot pass.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.advise_career import create_pending_run, run_advisor
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    AdvisorRun,
    Application,
    CareerMemory,
    Company,
    DispositionAction,
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

_REJECTION_FACT = "outcome.rejection_rate.global"
_COVERAGE_FACT = "coverage.analysed.global"


async def _seed_history(session: AsyncSession) -> User:
    sub = f"advisor-us1-{uuid.uuid4().hex[:12]}"
    user = await provision_user(session, {"sub": sub, "email": f"{sub}@example.com", "name": "US1"})
    company = Company(
        user_id=user.id, name="Seeded", normalized_name=normalize_company_name("Seeded")
    )
    session.add(company)
    await session.flush()
    now = datetime.now(UTC)
    for index, status in enumerate(
        (
            NormalizedStatus.REJECTED,
            NormalizedStatus.REJECTED,
            NormalizedStatus.REJECTED,
            NormalizedStatus.APPLIED,
            NormalizedStatus.INTERVIEWING,
            NormalizedStatus.WISHLIST,
        )
    ):
        application = Application(
            user_id=user.id,
            company_id=company.id,
            job_title=f"Backend Engineer {index}",
            status=status.value.title(),
            normalized_status=status,
            imported_match_rating=4 if index == 0 else 0,
        )
        application.date_added = now - timedelta(days=90 - index * 10)
        if status != NormalizedStatus.WISHLIST:
            application.date_applied = application.date_added + timedelta(days=3)
        session.add(application)
    await session.flush()
    return user


def _first_run_answer(task: str, parsed: ParsedPrompt) -> dict[str, Any]:
    """Build the answer from what the prompt actually said — the claim's
    numbers are the parsed fact's numbers, not the test author's."""
    assert task == "advisor_reason"
    num, den = parsed.facts[_REJECTION_FACT]
    return {
        "created": [
            {
                "claim": f"{num} of {den} of your applications ended rejected",
                "kind": "outcome_pattern",
                "scope_kind": "global",
                "cited_fact_ids": [_REJECTION_FACT],
                "priority": 60,
                "priority_reason": "outcomes are the pattern most worth watching",
                "tentative": False,
            },
            {
                # Fabricated on purpose: a digit no fact contains. The gate
                # must discard it and the run must still succeed.
                "claim": "99 of 100 recruiters ignored you",
                "kind": "fabrication",
                "scope_kind": "global",
                "cited_fact_ids": [_REJECTION_FACT],
                "tentative": False,
            },
        ],
        "dispositions": [],
    }


async def test_a_first_run_persists_grounded_memories_and_discards_the_rest(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _seed_history(session)
        run = await create_pending_run(session, user)
        assert run is not None
        await session.commit()
        run_id, user_id = run.id, user.id

    seam = PromptReadingAdvisorSeam(answer=_first_run_answer)
    async with session_factory() as session:
        await run_advisor(session, run_id=run_id, completion=seam)
        await session.commit()
    assert seam.tasks == ["advisor_reason"], "grouping must not have been called"

    async with session_factory() as session:
        finished = await session.get(AdvisorRun, run_id)
        assert finished is not None
        assert finished.status == "ready"
        assert finished.ops_proposed == 2
        assert finished.ops_applied == 1
        assert finished.ops_discarded == 1, (
            "found-nothing and discarded-everything must stay distinguishable"
        )
        assert finished.reason_model == "scripted/advisor_reason"
        assert finished.grouping_model is None, (
            "no analysed application exists, so the grouping step must be skipped "
            "— a run must not spend a completion to learn nothing (T031)"
        )
        assert finished.cost == Decimal("0.01")
        assert finished.evidence_pack is not None

        memories = list(
            (
                await session.scalars(select(CareerMemory).where(CareerMemory.user_id == user_id))
            ).all()
        )
        assert len(memories) == 1
        memory = memories[0]
        assert memory.status == "active"
        assert "3 of 6" in memory.claim
        assert memory.priority == 60 and memory.priority_reason

        # The creation is journalled.
        dispositions = list(
            (
                await session.scalars(
                    select(MemoryDisposition).where(MemoryDisposition.run_id == run_id)
                )
            ).all()
        )
        assert [d.action for d in dispositions] == [DispositionAction.CREATED]

        # -- SC-001: recompute every frozen fact from the rows it names ------
        audited = 0
        for memory in memories:
            for fact in memory.evidence["facts"]:
                record_ids = [uuid.UUID(value) for value in fact["record_ids"]]
                rows = list(
                    (
                        await session.scalars(
                            select(Application).where(Application.id.in_(record_ids))
                        )
                    ).all()
                )
                assert len(rows) == len(record_ids), "evidence names rows that do not exist"
                if fact["fact_id"] == _REJECTION_FACT:
                    assert all(row.normalized_status == "rejected" for row in rows)
                    assert fact["numerator"] == len(rows) == 3
                    total = await session.scalar(
                        select(text("count(*)"))
                        .select_from(Application)
                        .where(Application.user_id == user_id)
                    )
                    assert fact["denominator"] == total == 6
                audited += 1
            claim_numbers = set(re.findall(r"\d+", memory.claim))
            evidence_numbers: set[str] = set()
            for fact in memory.evidence["facts"]:
                evidence_numbers |= {str(fact["numerator"]), str(fact["denominator"])}
                evidence_numbers |= set(re.findall(r"\d+", fact["value"]))
            assert claim_numbers <= evidence_numbers
        assert audited >= 1, "the audit examined nothing"
        assert len(memories) == (finished.ops_applied or 0)


async def test_a_failed_run_is_billed_and_touches_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """T017 / SC-005: cost recorded from the exception's usage, zero memory
    rows, and the error is a kind, never provider detail."""
    async with session_factory() as session:
        user = await _seed_history(session)
        run = await create_pending_run(session, user)
        assert run is not None
        await session.commit()
        run_id, user_id = run.id, user.id

    seam = FailingAdvisorSeam()
    async with session_factory() as session:
        await run_advisor(session, run_id=run_id, completion=seam)
        await session.commit()

    async with session_factory() as session:
        failed = await session.get(AdvisorRun, run_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.cost == Decimal("0.007"), "a failed run must record what it spent"
        assert failed.input_tokens == 900
        assert failed.error == "The analysis could not be completed."
        assert "BilledFailure" not in (failed.error or "")

        count = await session.scalar(
            select(text("count(*)"))
            .select_from(CareerMemory)
            .where(CareerMemory.user_id == user_id)
        )
        assert count == 0
