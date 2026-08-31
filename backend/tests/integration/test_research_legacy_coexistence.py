"""008-era snapshots coexist with the reshaped world (US4, FR-014, SC-005).

Three claims, each independently checkable: a legacy company snapshot renders
through the same GET as `shape: "tiered"` / `produced_by: "legacy-company"` —
but **only when the application has no snapshot of its own**; a new run takes
precedence the moment it exists; and the legacy row's stored bytes are
untouched by everything above — asserted by hashing `sections::text` in the
database before and after, not by comparing Python objects.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    Company,
    CompanyResearchSnapshot,
    NormalizedStatus,
    ResearchSource,
    User,
    normalize_company_name,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.integration.test_research_api import (
    ScriptedResearchProvider,
    _provider_outcome,
    _tiered_research,
)

pytestmark = pytest.mark.asyncio


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


def _wire(app: object, provider: ScriptedResearchProvider) -> None:
    from careerhq.api.routes import research as route

    app.dependency_overrides[route.get_research_provider] = lambda: provider  # type: ignore[attr-defined]
    app.dependency_overrides[route.get_research_fallback] = lambda: None  # type: ignore[attr-defined]


async def _seed_with_legacy(
    session: AsyncSession, *, sub: str
) -> tuple[User, Application, CompanyResearchSnapshot]:
    """A user, an application, and a real 008-shaped company snapshot with its
    pointer set and one source row — history as 008 actually wrote it."""
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Legacy"}
    )
    company = Company(
        user_id=user.id, name="Pango", normalized_name=normalize_company_name("Pango")
    )
    session.add(company)
    await session.flush()
    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Backend",
        job_description="Parking Domain at Pango.",
        requirements=[],
        status="Wishlist",
        normalized_status=NormalizedStatus.WISHLIST,
    )
    legacy = CompanyResearchSnapshot(
        user_id=user.id,
        company_id=company.id,
        sections=_tiered_research(),
        status="succeeded",
        prompt_version="v2-dense",
    )
    session.add_all([application, legacy])
    await session.flush()
    session.add(
        ResearchSource(
            company_snapshot_id=legacy.id,
            source_id="s1",
            url="https://pango.co.il/about",
            title="About",
            excerpt="mobile parking payments",
            fetch_status="retrieved",
        )
    )
    company.current_research_snapshot_id = legacy.id
    await session.commit()
    return user, application, legacy


async def _sections_hash(session: AsyncSession, snapshot_id: object) -> str:
    result = await session.execute(
        text("SELECT md5(sections::text) FROM company_research_snapshots WHERE id = :id"),
        {"id": snapshot_id},
    )
    return result.scalar_one()


async def test_a_legacy_snapshot_renders_when_the_application_has_none(
    client: httpx.AsyncClient, app: object, db_session: AsyncSession
) -> None:
    _wire(app, ScriptedResearchProvider())
    user, application, legacy = await _seed_with_legacy(db_session, sub="legacy-render")

    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()

    assert body["shape"] == "tiered"
    assert body["produced_by"] == "legacy-company"
    assert body["snapshot_id"] == str(legacy.id)
    assert body["research"]["what_the_company_does"]["claims"][0]["tier"] == "fact"
    assert body["sources"][0]["excerpt"] == "mobile parking payments"
    # Legacy rows recorded exact seam usage — saying "estimate" would launder
    # a recorded figure into a vaguer one.
    assert body["cost_basis"] == "recorded"


async def test_a_new_run_takes_precedence_and_leaves_the_legacy_bytes_alone(
    client: httpx.AsyncClient, app: object, db_session: AsyncSession
) -> None:
    """US4 acceptance 2 plus SC-005 in one ordered scenario: the hash is taken
    before the run and compared after it, so the assertion is about stored
    bytes rather than about any object this process holds."""
    _wire(app, ScriptedResearchProvider(_provider_outcome()))
    user, application, legacy = await _seed_with_legacy(db_session, sub="legacy-precede")
    before = await _sections_hash(db_session, legacy.id)

    await _as(client, user).post(f"/api/applications/{application.id}/research")
    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()

    assert body["shape"] == "sections"
    assert body["produced_by"] == "provider:tavily-research"
    assert body["snapshot_id"] != str(legacy.id)

    after = await _sections_hash(db_session, legacy.id)
    assert after == before, "the legacy snapshot's stored sections changed byte-for-byte"


async def test_a_failed_only_application_row_does_not_hide_legacy_research(
    client: httpx.AsyncClient, app: object, db_session: AsyncSession
) -> None:
    """Review fix: a failed refresh must not make still-valid 008-era research
    vanish — the legacy body is served with the failure riding along."""
    from careerhq.application.research_persistence import (
        create_pending_application_research,
        fail_research,
    )

    _wire(app, ScriptedResearchProvider())
    user, application, legacy = await _seed_with_legacy(db_session, sub="legacy-failonly")
    bad = await create_pending_application_research(
        db_session, application, produced_by="provider:tavily-research"
    )
    await fail_research(db_session, bad, "ResearchProviderUnavailable")
    await db_session.commit()

    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()
    assert body["status"] == "succeeded"
    assert body["produced_by"] == "legacy-company"
    assert body["snapshot_id"] == str(legacy.id)
    assert body["last_failure"]["failure_reason"] == "ResearchProviderUnavailable"


async def test_a_stuck_legacy_running_row_is_not_served_as_live(
    client: httpx.AsyncClient, app: object, db_session: AsyncSession
) -> None:
    """Review fix: a pre-010 company row stuck at 'running' has no write path
    left to finish it — serving it as live would pin the tab on 'Researching…'
    forever with recovery disabled. It reads as nothing instead."""
    from careerhq.domain.models import CompanyResearchSnapshot

    _wire(app, ScriptedResearchProvider())
    user, application, legacy = await _seed_with_legacy(db_session, sub="legacy-stuck")
    stuck = await db_session.get(CompanyResearchSnapshot, legacy.id)
    assert stuck is not None
    stuck.status = "running"
    company_id = stuck.company_id
    from sqlalchemy import text

    await db_session.execute(
        text("UPDATE companies SET current_research_snapshot_id = NULL WHERE id = :id"),
        {"id": company_id},
    )
    await db_session.commit()

    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()
    assert body["status"] == "none"
