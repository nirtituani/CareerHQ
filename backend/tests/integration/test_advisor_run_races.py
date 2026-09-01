"""B3/B4 regressions (code review 2026-09-01, executed reproductions).

The seam performs the concurrent action through its own committed session
mid-completion — exactly the window a slow provider call opens.

* B3: a run reaped `failed` while its task was still alive must **stay**
  failed; the zombie's writes are discarded, never resurrected to `ready`.
* B4: a user dismissal that lands mid-run must survive the run — the model's
  disposition for that memory is skipped, `user_dismissed` (FR-021's marker)
  is never overwritten, and the rest of the run still applies.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.advise_career import create_pending_run, run_advisor
from careerhq.application.ports import Completion, Usage
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    USER_DISMISSED,
    AdvisorRun,
    AdvisorRunStatus,
    Application,
    CareerMemory,
    Company,
    MemoryStatus,
    NormalizedStatus,
    User,
    normalize_company_name,
)

pytestmark = pytest.mark.asyncio

_MEMORY_LINE = re.compile(r"\[memory: ([0-9a-f-]{36})\]")


async def _seed(session: AsyncSession) -> User:
    sub = f"race-{uuid.uuid4().hex[:10]}"
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Race"}
    )
    company = Company(user_id=user.id, name="R", normalized_name=normalize_company_name(f"R{sub}"))
    session.add(company)
    await session.flush()
    for index in range(3):
        application = Application(
            user_id=user.id,
            company_id=company.id,
            job_title=f"T{index}",
            status="Rejected",
            normalized_status=NormalizedStatus.REJECTED,
        )
        application.date_added = datetime.now(UTC)
        session.add(application)
    await session.flush()
    return user


class MidCallSeam:
    """Commits `side_effect` through a second session before answering."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        side_effect: Callable[[AsyncSession], Awaitable[None]],
        answer: Callable[[str], dict[str, Any]],
    ) -> None:
        self._factory, self._side_effect, self._answer = factory, side_effect, answer

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        async with self._factory() as session:
            await self._side_effect(session)
            await session.commit()
        return Completion(
            value=schema.model_validate(self._answer(prompt)),
            usage=Usage(model="scripted", input_tokens=1, output_tokens=1, cost=Decimal("0.001")),
        )


async def test_b3_a_reaped_run_stays_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _seed(session)
        run = await create_pending_run(session, user)
        assert run is not None
        await session.commit()
        run_id, user_id = run.id, user.id

    async def reap(session: AsyncSession) -> None:  # what trigger_run's reaper does
        await session.execute(
            text("UPDATE advisor_runs SET status='failed', error='reaped' WHERE id=:i"),
            {"i": run_id},
        )

    def answer(prompt: str) -> dict[str, Any]:
        return {
            "created": [
                {
                    "claim": "3 of 3 applications ended rejected",
                    "kind": "outcome_pattern",
                    "scope_kind": "global",
                    "cited_fact_ids": ["outcome.rejection_rate.global"],
                    "tentative": False,
                }
            ],
            "dispositions": [],
        }

    seam = MidCallSeam(session_factory, reap, answer)
    async with session_factory() as session:
        await run_advisor(session, run_id=run_id, completion=seam)
        await session.commit()

    async with session_factory() as session:
        row = (
            await session.execute(
                text("SELECT status, error FROM advisor_runs WHERE id=:i"), {"i": run_id}
            )
        ).one()
        assert row[0] == "failed", "a terminal reaped run must never resurrect to ready"
        memories = await session.scalar(
            text("SELECT count(*) FROM career_memories WHERE user_id=:u"),
            {"u": str(user_id)},
        )
        assert memories == 0, "the zombie's memory writes must be discarded with it"


async def test_b4_a_mid_run_dismissal_survives_the_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _seed(session)
        anchor = AdvisorRun(
            user_id=user.id,
            status=AdvisorRunStatus.READY,
            rules_version="v",
            dispositions=[],
        )
        session.add(anchor)
        await session.flush()
        memory = CareerMemory(
            user_id=user.id,
            advisor_run_id=anchor.id,
            claim="2 of 3 applications ended rejected",
            kind="outcome_pattern",
            scope_kind="global",
            evidence={
                "facts": [
                    {
                        "fact_id": "outcome.rejection_rate.global",
                        "numerator": 2,
                        "denominator": 3,
                    }
                ]
            },
            status=MemoryStatus.ACTIVE,
        )
        session.add(memory)
        run = await create_pending_run(session, user)
        assert run is not None
        await session.commit()
        memory_id, run_id = memory.id, run.id

    async def dismiss(session: AsyncSession) -> None:  # the user's concurrent action
        await session.execute(
            text("UPDATE career_memories SET status='retired', retired_reason=:r WHERE id=:i"),
            {"i": memory_id, "r": USER_DISMISSED},
        )

    def answer(prompt: str) -> dict[str, Any]:
        rendered = _MEMORY_LINE.search(prompt)
        assert rendered is not None
        return {
            "created": [],
            "dispositions": [
                {
                    "memory_id": rendered.group(1),
                    "action": "retire",
                    "reason": "model decided to retire it",
                }
            ],
            "nothing_found_reason": "n",
        }

    seam = MidCallSeam(session_factory, dismiss, answer)
    async with session_factory() as session:
        await run_advisor(session, run_id=run_id, completion=seam)
        await session.commit()

    async with session_factory() as session:
        row = (
            await session.execute(
                text("SELECT status, retired_reason FROM career_memories WHERE id=:i"),
                {"i": memory_id},
            )
        ).one()
        assert row[0] == "retired"
        assert row[1] == USER_DISMISSED, (
            "the FR-021 dismissal marker must survive an in-flight run's disposition"
        )
        run_row = (
            await session.execute(
                text("SELECT status FROM advisor_runs WHERE id=:i"), {"i": run_id}
            )
        ).one()
        assert run_row[0] == "ready", "a legitimate user action must not fail the rest of the run"
