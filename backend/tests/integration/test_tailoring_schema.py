"""Two absences, asserted against the database rather than against intent.

An invariant enforced by something *not existing* has nothing to catch its
return. Nobody reviews a pull request looking for a column that should not be
there, and the code keeps working when one appears — it just quietly starts
meaning something else.

Slice 003 proved this the expensive way: its equivalent test passed against a
deliberately added `rejected` column until `conftest.py` began dropping the
schema before creating it, because `create_all` skips existing tables rather
than reconciling them. **Both tests below were watched failing** before being
trusted.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_there_is_no_failed_version_status(db_session: AsyncSession) -> None:
    """A failed run leaves a `draft`, not a `failed`.

    The check constraint is the whole enforcement. If a `failed` status is ever
    added, retry stops being "run it again on the existing draft" and starts
    needing a transition nobody designed — and abandoned versions accumulate,
    one per failure, each looking like a real document.
    """
    definition = await db_session.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_resume_versions_status'"
        )
    )

    assert definition is not None, "the status check constraint is missing entirely"
    assert "failed" not in definition, (
        "a 'failed' version status has appeared. A failed run must leave the version at "
        f"'draft' with a reason on the run — see data-model.md. Constraint: {definition}"
    )
    for expected in ("draft", "tailoring", "reviewing", "awaiting_approval", "ready"):
        assert expected in definition, f"status '{expected}' is missing from {definition}"


async def test_no_table_stores_staleness_as_a_column(db_session: AsyncSession) -> None:
    """Staleness is computed, never stored.

    `match.py` established the rule and the reason: a stored flag is a second
    source of truth that goes wrong the moment a profile is edited without every
    dependent row being visited. Tailoring depends on the same comparison to
    decide whether it may run at all (FR-001), so a cached copy here would be
    wrong in exactly the situation the precondition exists to catch.
    """
    columns = (
        (
            await db_session.execute(
                text(
                    "SELECT table_name || '.' || column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name IN ('is_stale', 'stale')"
                )
            )
        )
        .scalars()
        .all()
    )

    assert list(columns) == [], f"staleness must be computed at read time, not stored: {columns}"


async def test_awaiting_approval_is_a_state_of_its_own(db_session: AsyncSession) -> None:
    """The amendment to `docs/03` §10.1, asserted so it cannot quietly regress.

    `reviewing` meant both "the agent is working" and "it is your turn". If
    `awaiting_approval` disappears, the interface loses the only way to tell a
    person which of those they are waiting on — and the two have completely
    different expected durations.
    """
    definition = await db_session.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_resume_versions_status'"
        )
    )

    assert definition is not None
    assert "awaiting_approval" in definition
    assert "reviewing" in definition, "both halves must exist, or the split bought nothing"


async def test_an_ungrounded_finding_cannot_be_stored_without_its_quote(
    db_session: AsyncSession,
) -> None:
    """The constraint that makes the grounding rule checkable.

    A finding saying "this is unsupported" without saying *which words* cannot
    be tested, cannot be displayed, and cannot be checked by a person. It also
    lets the model assert an absence it has no basis for — the same fabrication
    AI-008 forbids, pointed the other way.
    """
    definition = await db_session.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_reviewer_findings_ungrounded_quotes'"
        )
    )

    assert definition is not None, (
        "the constraint requiring an ungrounded finding to quote its evidence is gone"
    )
    assert "quoted_text" in definition
