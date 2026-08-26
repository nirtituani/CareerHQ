"""Which analysis the Match endpoint reports, and when.

`_latest_analysis` preferred `current_match_analysis_id`, and `run_analysis`
writes that pointer **only on success, last of all** — deliberately, so a failed
run leaves the previous score standing (FR-015). The consequence was that for the
whole duration of a re-run the endpoint reported the *previous* analysis.

Measured on a real run: a click at 07:03:52 started a completion that finished at
07:04:16 with 84/strong. Two polls, at 07:03:54 and 07:04:03, both read the old
row. Neither said `running`, so the interface stopped polling within two seconds
and the result landed thirteen seconds after anything was watching. The owner
clicked again, got a correct 409, and saw the same thing.

**This was never specific to the zero-requirement row.** Before that rule existed
the same polls returned the previous *score* — also not `running`, so polling
also stopped, and a re-run also never appeared without a reload. Every re-run of
an already-scored job had it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.analyze_match import STALE_PENDING_AFTER
from careerhq.domain.models import MatchAnalysis, MatchRequirement, MatchStatus
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


async def _pending(session: AsyncSession, application_id, *, age: timedelta | None = None):
    """A second analysis, in flight, exactly as `trigger_match` reserves one."""
    row = MatchAnalysis(
        application_id=application_id,
        status=MatchStatus.PENDING,
        criteria_version="v3-earned",
        # Assigned at construction. A lazy load on a freshly added object is
        # MissingGreenlet the moment anything touches the collection.
        requirements=[],
    )
    session.add(row)
    await session.flush()
    if age is not None:
        row.created_at = datetime.now(UTC) - age
        await session.flush()
    return row


def _as(client: httpx.AsyncClient, user) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


async def test_a_rerun_in_flight_is_reported_as_running(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The general case, and the one that has always been broken.

    A job already carrying a good score is re-run. Until this fix the endpoint
    answered with the previous score — so the interface, which polls only while
    the state is `running`, stopped on its first poll and never saw the result.
    """
    seeded = await seed_tailorable(db_session, sub="cur-run", email="cur-run@example.com")
    assert seeded.application.current_match_analysis_id == seeded.analysis.id
    await _pending(db_session, seeded.application.id)
    await db_session.commit()

    body = (
        await _as(client, seeded.user).get(f"/api/applications/{seeded.application.id}/match")
    ).json()

    assert body["state"] == "running"


async def test_a_rerun_over_a_zero_requirement_analysis_is_reported_as_running(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The Voyantis shape.

    The previous analysis is `ready` with no requirement rows, which the state
    rule correctly reports as `nothing_to_score`. Handed *that* row during a
    re-run, the interface showed "has not been scored yet" beside a Score
    button — indistinguishable from a job nobody had ever scored, which is why
    the owner clicked twice.
    """
    seeded = await seed_tailorable(db_session, sub="cur-zero", email="cur-zero@example.com")
    for row in list(seeded.analysis.requirements):
        await db_session.delete(row)
    seeded.analysis.overall_score = 0
    seeded.analysis.band = "low_probability"
    await db_session.flush()

    await _pending(db_session, seeded.application.id)
    await db_session.commit()

    body = (
        await _as(client, seeded.user).get(f"/api/applications/{seeded.application.id}/match")
    ).json()

    assert body["state"] == "running"


async def test_a_failed_rerun_leaves_the_previous_score_standing(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-015, which the fix must not trade away.

    The pointer is written only on success precisely so this holds. A failed row
    is not pending, so it falls through to the pointer and the last good score
    survives.
    """
    seeded = await seed_tailorable(db_session, sub="cur-fail", email="cur-fail@example.com")
    good = seeded.analysis.overall_score

    failed = await _pending(db_session, seeded.application.id)
    failed.status = MatchStatus.FAILED
    failed.error = "The analysis stopped before it finished."
    failed.completed_at = datetime.now(UTC)
    await db_session.commit()

    body = (
        await _as(client, seeded.user).get(f"/api/applications/{seeded.application.id}/match")
    ).json()

    assert body["state"] == "ready"
    assert body["analysis"]["overall_score"] == good


async def test_an_abandoned_run_also_leaves_the_previous_score_standing(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The subtler half of FR-015.

    A run that stops without finishing stays `pending` forever — it is the
    reaper, on the next request to score, that marks it failed. Returning it
    here because it is technically in flight would replace a good score with
    `failed` for a run nobody will finish. So an in-flight row is preferred only
    while it is *plausibly* in flight.
    """
    seeded = await seed_tailorable(db_session, sub="cur-aband", email="cur-aband@example.com")
    good = seeded.analysis.overall_score

    await _pending(
        db_session, seeded.application.id, age=STALE_PENDING_AFTER + timedelta(minutes=5)
    )
    await db_session.commit()

    body = (
        await _as(client, seeded.user).get(f"/api/applications/{seeded.application.id}/match")
    ).json()

    assert body["state"] == "ready"
    assert body["analysis"]["overall_score"] == good


async def test_a_ready_row_is_never_chosen_while_one_is_genuinely_in_flight(
    db_session: AsyncSession,
) -> None:
    """The invariant, stated directly against the selector.

    The endpoint tests above could pass for the wrong reason — a state rule that
    happened to say `running`. This asserts the selection itself.
    """
    from careerhq.api.routes.applications import _latest_analysis

    seeded = await seed_tailorable(db_session, sub="cur-inv", email="cur-inv@example.com")
    pending = await _pending(db_session, seeded.application.id)
    await db_session.flush()

    chosen = await _latest_analysis(db_session, seeded.application)

    assert chosen is not None
    assert chosen.id == pending.id
    assert chosen.status != MatchStatus.READY


async def test_the_pointer_is_still_preferred_when_nothing_is_in_flight(
    db_session: AsyncSession,
) -> None:
    """The fallback order is unchanged: pointer, then newest."""
    from careerhq.api.routes.applications import _latest_analysis

    seeded = await seed_tailorable(db_session, sub="cur-ptr", email="cur-ptr@example.com")

    chosen = await _latest_analysis(db_session, seeded.application)

    assert chosen is not None
    assert chosen.id == seeded.application.current_match_analysis_id


async def test_creating_a_pending_analysis_does_not_move_the_pointer(
    db_session: AsyncSession,
) -> None:
    """The pointer names only ready rows, and that is what makes FR-015 work.

    Repointing on creation would be the obvious alternative fix and would break
    the failure guarantee: a run that died would leave the pointer naming a row
    with no score.
    """
    from careerhq.application.analyze_match import create_pending_analysis

    seeded = await seed_tailorable(db_session, sub="cur-nomove", email="cur-nomove@example.com")
    before = seeded.application.current_match_analysis_id

    created = await create_pending_analysis(db_session, seeded.application)
    await db_session.flush()

    assert created is not None
    assert seeded.application.current_match_analysis_id == before
    assert created.id != before


async def test_the_state_walks_running_to_ready_as_a_rerun_completes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The sequence the interface actually polls, end to end.

    Before the fix this read `ready`/`nothing_to_score` on the first poll and
    the interface stopped watching. The result then landed unobserved.
    """
    seeded = await seed_tailorable(db_session, sub="cur-walk", email="cur-walk@example.com")
    rerun = await _pending(db_session, seeded.application.id)
    await db_session.commit()

    first = (
        await _as(client, seeded.user).get(f"/api/applications/{seeded.application.id}/match")
    ).json()
    assert first["state"] == "running"

    # The background task finishing: requirements written, then the pointer
    # moved last, exactly as `run_analysis` does it.
    rerun.status = MatchStatus.READY
    rerun.overall_score = 84
    rerun.band = "strong"
    rerun.completed_at = datetime.now(UTC)
    # Fresh rows rather than moving the other analysis's: reassigning a loaded
    # relationship lazy-loads the existing collection, which async SQLAlchemy
    # answers with MissingGreenlet.
    rerun.requirements = [
        MatchRequirement(
            ordinal=0,
            text_="5+ years backend services",
            kind="must_have",
            importance=90,
            verdict="confirmed",
            evidence="Led the payments platform team for six years.",
        )
    ]
    await db_session.flush()
    seeded.application.current_match_analysis_id = rerun.id
    await db_session.commit()

    second = (
        await _as(client, seeded.user).get(f"/api/applications/{seeded.application.id}/match")
    ).json()
    assert second["state"] == "ready"
    assert second["analysis"]["overall_score"] == 84

    remaining = await db_session.scalars(
        select(MatchAnalysis).where(MatchAnalysis.application_id == seeded.application.id)
    )
    assert len(list(remaining)) == 2, "both runs survive; nothing was overwritten"
