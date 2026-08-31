"""A career memory's content is frozen at insert (T025, spec FR-012).

The lock is about content, not the row (the resume-version reading of
Principle IV): `status` still moves forward, `last_confirmed_at` advances,
priority may re-rank — but the claim, the frozen evidence and the lineage
links never change after insert, because editing a persisted claim silently
reinterprets what a person was told.

Enforced by an ORM guard rather than by care, and drilled: each frozen column
is written after commit and the guard must name it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    AdvisorRun,
    AdvisorRunStatus,
    CareerMemory,
    MemoryContentFrozen,
    MemoryStatus,
)

pytestmark = pytest.mark.asyncio


async def _memory(session: AsyncSession) -> CareerMemory:
    sub = f"immutable-{uuid.uuid4().hex[:10]}"
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Frozen"}
    )
    run = AdvisorRun(
        user_id=user.id,
        status=AdvisorRunStatus.READY,
        rules_version="v1-advisor",
        dispositions=[],
    )
    session.add(run)
    await session.flush()
    memory = CareerMemory(
        user_id=user.id,
        advisor_run_id=run.id,
        claim="2 of 5 applications ended rejected",
        kind="outcome_pattern",
        scope_kind="global",
        evidence={"facts": []},
        status=MemoryStatus.ACTIVE,
    )
    session.add(memory)
    await session.commit()
    return memory


FROZEN_WRITES = (
    ("claim", "a different claim"),
    ("kind", "different_kind"),
    ("scope_kind", "role_family"),
    ("scope_value", "Backend"),
    ("evidence", {"facts": [{"tampered": True}]}),
    ("advisor_run_id", uuid.uuid4()),
    ("supersedes_id", uuid.uuid4()),
    ("recreates_dismissed_id", uuid.uuid4()),
)


@pytest.mark.parametrize(("column", "value"), FROZEN_WRITES, ids=[c for c, _ in FROZEN_WRITES])
async def test_every_frozen_column_refuses_a_write(
    session_factory: async_sessionmaker[AsyncSession], column: str, value: object
) -> None:
    async with session_factory() as session:
        memory = await _memory(session)
        setattr(memory, column, value)
        with pytest.raises(MemoryContentFrozen) as refusal:
            await session.flush()
        assert column in str(refusal.value), "the guard must name the frozen column"
        await session.rollback()


async def test_the_lifecycle_columns_stay_writable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The mutable remainder — a guard that refused every write would make
    the lifecycle impossible, which is worse than what it prevents."""
    async with session_factory() as session:
        memory = await _memory(session)
        memory.status = MemoryStatus.RETIRED
        memory.retired_reason = "no longer relevant"
        memory.priority = 10
        memory.priority_reason = "re-ranked by a confirming run"
        await session.flush()
        await session.commit()
