"""Invariant 2, proven at the boundary (T026, spec FR-013/FR-014, SC-002).

A memory counts as agent-managed only if a later run **retrieved** it,
**received it as reasoning input**, and **dispositioned** it. This file proves
the middle step from what the run actually did: the seam captures the exact
rendered input it was called with, and the assertions read that capture —
never the plumbing that could have supplied it.

The count assertions are the teeth: a run with zero prior memories fails
here rather than passing vacuously, and the G3 exclusion is asserted against
the `[memory:]` marker specifically, in the captured input.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.advise_career import create_pending_run, run_advisor
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    USER_DISMISSED,
    AdvisorRun,
    AdvisorRunStatus,
    Application,
    CareerMemory,
    Company,
    MemoryDisposition,
    MemoryStatus,
    NormalizedStatus,
    User,
    normalize_company_name,
)
from tests.support.advisor_seam import ParsedPrompt, PromptReadingAdvisorSeam

pytestmark = pytest.mark.asyncio

_REJECTION_FACT = "outcome.rejection_rate.global"
_MEMORY_LINE = re.compile(r"^\[memory: (?P<id>[0-9a-f-]{36})\]", re.M)
_DISMISSED_LINE = re.compile(r"^\[dismissed: (?P<id>[0-9a-f-]{36})\]", re.M)


async def _seed_user(session: AsyncSession) -> User:
    sub = f"retrieval-{uuid.uuid4().hex[:10]}"
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Retrieval"}
    )
    company = Company(
        user_id=user.id, name="Seeded", normalized_name=normalize_company_name("Seeded")
    )
    session.add(company)
    await session.flush()
    for index in range(4):
        application = Application(
            user_id=user.id,
            company_id=company.id,
            job_title=f"Role {index}",
            status="Rejected" if index < 2 else "Applied",
            normalized_status=(
                NormalizedStatus.REJECTED if index < 2 else NormalizedStatus.APPLIED
            ),
        )
        application.date_added = datetime.now(UTC) - timedelta(days=30 + index)
        session.add(application)
    await session.flush()
    return user


def _first_run_answer(task: str, parsed: ParsedPrompt) -> dict[str, Any]:
    num, den = parsed.facts[_REJECTION_FACT]
    applied_num, applied_den = parsed.facts["status.distribution.applied"]
    return {
        "created": [
            {
                "claim": f"{num} of {den} applications ended rejected",
                "kind": "outcome_pattern",
                "scope_kind": "global",
                "cited_fact_ids": [_REJECTION_FACT],
                "tentative": False,
            },
            {
                "claim": f"{applied_num} of {applied_den} applications are currently applied",
                "kind": "status_pattern",
                "scope_kind": "status",
                "scope_value": "applied",
                "cited_fact_ids": ["status.distribution.applied"],
                "tentative": False,
            },
        ],
        "dispositions": [],
    }


async def _terminal_memory(
    session: AsyncSession,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    status: MemoryStatus,
    reason: str | None,
) -> CareerMemory:
    memory = CareerMemory(
        user_id=user_id,
        advisor_run_id=run_id,
        claim=f"an old {status} claim over 1 of 4",
        kind=f"old_{status}",
        scope_kind="global",
        evidence={"facts": [{"fact_id": _REJECTION_FACT, "numerator": 1, "denominator": 4}]},
        status=status,
        retired_reason=reason,
    )
    session.add(memory)
    await session.flush()
    return memory


async def test_prior_memories_are_retrieved_reasoned_over_and_dispositioned(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # -- run 1: two memories come to exist -----------------------------------
    async with session_factory() as session:
        user = await _seed_user(session)
        run1 = await create_pending_run(session, user)
        assert run1 is not None
        await session.commit()
        user_id = user.id

    seam1 = PromptReadingAdvisorSeam(answer=_first_run_answer)
    async with session_factory() as session:
        await run_advisor(session, run_id=run1.id, completion=seam1)
        await session.commit()

    # -- between runs: history rows in every non-active state ----------------
    async with session_factory() as session:
        prior = list(
            (
                await session.scalars(
                    select(CareerMemory).where(
                        CareerMemory.user_id == user_id,
                        CareerMemory.status.in_([MemoryStatus.ACTIVE, MemoryStatus.TENTATIVE]),
                    )
                )
            ).all()
        )
        assert len(prior) == 2, "run 1 must have produced the prior state"
        prior_ids = {str(memory.id) for memory in prior}
        prior_claims = {memory.id: memory.claim for memory in prior}

        anchor = AdvisorRun(
            user_id=user_id,
            status=AdvisorRunStatus.READY,
            rules_version="v1-advisor",
            dispositions=[],
        )
        session.add(anchor)
        await session.flush()
        superseded = await _terminal_memory(
            session, user_id, anchor.id, MemoryStatus.SUPERSEDED, None
        )
        retired = await _terminal_memory(
            session, user_id, anchor.id, MemoryStatus.RETIRED, "mooted"
        )
        dismissed = await _terminal_memory(
            session, user_id, anchor.id, MemoryStatus.RETIRED, USER_DISMISSED
        )
        await session.commit()
        terminal_ids = {str(superseded.id), str(retired.id)}
        dismissed_id = str(dismissed.id)

    # -- run 2: the double answers from the captured input only --------------
    def second_run_answer(task: str, parsed: ParsedPrompt) -> dict[str, Any]:
        # (c) the ids the dispositions name are read out of the prompt — the
        # double is given nothing else to work from.
        return {
            "created": [],
            "dispositions": [
                {
                    "memory_id": memory_id,
                    "action": "confirm",
                    "fresh_fact_ids": [_REJECTION_FACT],
                }
                for memory_id in parsed.memory_ids
            ],
            "nothing_found_reason": "the evidence supports no new claim this run",
        }

    async with session_factory() as session:
        fresh_user = await session.get(User, user_id)
        assert fresh_user is not None
        run2 = await create_pending_run(session, fresh_user)
        assert run2 is not None
        await session.commit()

    seam2 = PromptReadingAdvisorSeam(answer=second_run_answer)
    async with session_factory() as session:
        await run_advisor(session, run_id=run2.id, completion=seam2)
        await session.commit()

    # -- the boundary assertions, against the captured input -----------------
    assert len(seam2.prompts) == 1, "the run made exactly one reasoning call"
    captured = seam2.prompts[0]

    rendered_ids = {match.group("id") for match in _MEMORY_LINE.finditer(captured)}
    # (a) every prior active memory is in the reasoning input, and (b) N is
    # asserted — a zero-memory prompt cannot pass this vacuously.
    assert rendered_ids == prior_ids
    assert len(rendered_ids) == 2
    for memory_id, claim in prior_claims.items():
        assert claim in captured, f"memory {memory_id} travelled without its claim"

    # (d) G3 at the boundary: terminal rows appear in no [memory:] entry;
    # the dismissed one appears only via [dismissed:].
    assert not (terminal_ids & rendered_ids)
    for terminal in terminal_ids:
        assert f"[memory: {terminal}]" not in captured
    dismissed_rendered = {m.group("id") for m in _DISMISSED_LINE.finditer(captured)}
    assert dismissed_rendered == {dismissed_id}
    assert "dismissed by the user" in captured

    # -- and the dispositions landed: retrieve -> reason -> disposition ->
    # persist, closed end to end ---------------------------------------------
    async with session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(MemoryDisposition).where(MemoryDisposition.run_id == run2.id)
                )
            ).all()
        )
        assert {str(row.memory_id) for row in rows} == prior_ids
        assert all(row.action == "confirmed" for row in rows)
        assert len(rows) == 2
