"""Reuse and freshness, per application (slice 010, decision 1A).

This file replaces the 008-era company-scoped reuse suite wholesale: the axis
changed, and the most important new claim is the **negative** one — two
applications at the same employer no longer share a snapshot. That independence
was the entire cost of decision 1A (measured at ~3% of research calls), so it
is asserted on the provider's call count, not inferred from response bodies.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    Company,
    NormalizedStatus,
    User,
    normalize_company_name,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.integration.test_research_api import ScriptedResearchProvider, _provider_outcome

pytestmark = pytest.mark.asyncio


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


def _wire(app: Any, provider: ScriptedResearchProvider) -> None:
    from careerhq.api.routes import research as route

    app.dependency_overrides[route.get_research_provider] = lambda: provider
    app.dependency_overrides[route.get_research_fallback] = lambda: None


async def _seed_two_applications(
    session: AsyncSession, *, sub: str
) -> tuple[User, Application, Application]:
    """One employer, two applications — the decision 1A scenario."""
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Reuse"}
    )
    company = Company(
        user_id=user.id, name="Pango", normalized_name=normalize_company_name("Pango")
    )
    session.add(company)
    await session.flush()
    first = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Senior Backend - Parking",
        job_description="Parking Domain at Pango.",
        requirements=[],
        status="Wishlist",
        normalized_status=NormalizedStatus.WISHLIST,
    )
    second = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Data Engineer - Fuelling",
        job_description="Fuelling Domain at Pango.",
        requirements=[],
        status="Wishlist",
        normalized_status=NormalizedStatus.WISHLIST,
    )
    session.add_all([first, second])
    await session.commit()
    return user, first, second


async def _age_snapshots(session: AsyncSession, *, days: int) -> None:
    await session.execute(
        text(
            "UPDATE application_research_snapshots SET retrieved_at = "
            "now() - make_interval(days => :days)"
        ),
        {"days": days},
    )
    await session.commit()


async def test_two_applications_at_one_employer_research_independently(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """Decision 1A's whole meaning: the second application is NOT a reuse of
    the first — each pays for and owns role-aware research. The script holds
    exactly two answers, so any third spend blows up too."""
    provider = ScriptedResearchProvider(_provider_outcome(), _provider_outcome())
    _wire(app, provider)
    user, first, second = await _seed_two_applications(db_session, sub="reuse-indep")

    a = await _as(client, user).post(f"/api/applications/{first.id}/research")
    b = await _as(client, user).post(f"/api/applications/{second.id}/research")

    assert a.json()["reused"] is False
    assert b.json()["reused"] is False, "company-level reuse was retired (1A)"
    assert a.json()["snapshot_id"] != b.json()["snapshot_id"]
    assert len(provider.calls) == 2
    # And each call carried its own application's posting, which is the point
    # of paying twice.
    postings = {call["posting_text"] for call in provider.calls}
    assert postings == {"Parking Domain at Pango.", "Fuelling Domain at Pango."}


async def test_inside_the_window_the_same_application_reuses(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    provider = ScriptedResearchProvider(_provider_outcome())
    _wire(app, provider)
    user, first, _ = await _seed_two_applications(db_session, sub="reuse-same")
    path = f"/api/applications/{first.id}/research"

    await _as(client, user).post(path)
    again = await _as(client, user).post(path)

    assert again.json()["reused"] is True
    assert len(provider.calls) == 1


async def test_past_the_reuse_window_a_refresh_actually_runs(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    provider = ScriptedResearchProvider(_provider_outcome(), _provider_outcome())
    _wire(app, provider)
    user, first, _ = await _seed_two_applications(db_session, sub="reuse-aged")
    path = f"/api/applications/{first.id}/research"

    await _as(client, user).post(path)
    await _age_snapshots(db_session, days=31)
    again = await _as(client, user).post(path)

    assert again.json()["reused"] is False
    assert len(provider.calls) == 2


@pytest.mark.parametrize(
    ("days", "label"),
    [(0, "fresh"), (35, "aging"), (100, "stale")],
    ids=["fresh", "aging", "stale"],
)
async def test_the_three_freshness_states_are_derived_at_read_time(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession, days: int, label: str
) -> None:
    """FR-013: inside the reuse window `fresh`; between the windows `aging`
    (still shown, age visible); past the stale window `stale` (flagged). The
    label is derived from the row's age at read time, never stored."""
    provider = ScriptedResearchProvider(_provider_outcome())
    _wire(app, provider)
    user, first, _ = await _seed_two_applications(db_session, sub=f"reuse-fresh-{days}")
    path = f"/api/applications/{first.id}/research"

    await _as(client, user).post(path)
    if days:
        await _age_snapshots(db_session, days=days)

    body = (await _as(client, user).get(path)).json()
    assert body["freshness"] == label
