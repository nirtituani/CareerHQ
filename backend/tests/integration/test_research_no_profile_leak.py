"""SC-007: nothing profile-shaped reaches a research provider (T034).

The port's signature has no parameter a profile could arrive through — but a
signature proves nothing about what a route *assembles into* the parameters it
does have. So this test plants a sentinel string in every profile surface a
careless context assembly might read (summary, contact, work experience,
title), runs research through the real route, and searches **every value of
every captured provider call** for it.

The sentinel is a nonsense token rather than realistic PII, so a hit can only
mean leakage — and the test first proves the sentinel is actually stored,
because a gate whose trap was never set passes forever.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    Company,
    ContactInformation,
    NormalizedStatus,
    ProfessionalProfile,
    ProfessionalTitle,
    SummaryBlock,
    User,
    WorkExperience,
    normalize_company_name,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.integration.test_research_api import ScriptedResearchProvider, _provider_outcome

pytestmark = pytest.mark.asyncio

SENTINEL = "XZQ-PROFILE-SENTINEL-9174"


async def _seed(session: AsyncSession) -> tuple[User, Application]:
    user = await provision_user(
        session,
        {"sub": "sc007", "email": "sc007@example.com", "name": "Sentinel"},
    )
    profile_id = await session.scalar(
        select(ProfessionalProfile.id).where(ProfessionalProfile.user_id == user.id)
    )
    assert profile_id is not None
    session.add_all(
        [
            SummaryBlock(profile_id=profile_id, text=f"A summary mentioning {SENTINEL}."),
            ContactInformation(profile_id=profile_id, full_name=SENTINEL, location=SENTINEL),
            ProfessionalTitle(profile_id=profile_id, title=SENTINEL),
            WorkExperience(profile_id=profile_id, company=SENTINEL, title=SENTINEL),
        ]
    )
    company = Company(
        user_id=user.id, name="Pango", normalized_name=normalize_company_name("Pango")
    )
    session.add(company)
    await session.flush()
    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Senior Backend - Parking",
        job_description="Join the Parking Domain at Pango.",
        requirements=[],
        status="Wishlist",
        normalized_status=NormalizedStatus.WISHLIST,
    )
    session.add(application)
    await session.commit()
    return user, application


async def test_no_profile_content_reaches_the_provider(
    client: httpx.AsyncClient, app: object, db_session: AsyncSession
) -> None:
    from careerhq.api.routes import research as route

    provider = ScriptedResearchProvider(_provider_outcome())
    app.dependency_overrides[route.get_research_provider] = lambda: provider  # type: ignore[attr-defined]
    app.dependency_overrides[route.get_research_fallback] = lambda: None  # type: ignore[attr-defined]

    user, application = await _seed(db_session)

    # The trap must be set before it can be trusted: the sentinel is really in
    # the profile tables this user owns.
    stored = await db_session.scalar(
        select(SummaryBlock.text).where(SummaryBlock.text.contains(SENTINEL))
    )
    assert stored is not None, "the sentinel never reached the profile; the trap is unset"

    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    response = await client.post(f"/api/applications/{application.id}/research")
    assert response.status_code == 202, response.text

    assert len(provider.calls) == 1, "the provider must have been called for this to prove anything"
    for call in provider.calls:
        for name, value in call.items():
            assert value is None or SENTINEL not in str(value), (
                f"profile content leaked into the provider input {name!r} (SC-007/FR-002)"
            )
