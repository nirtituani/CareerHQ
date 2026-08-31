"""The application-research endpoints, over the real ASGI app (slice 010).

The research provider and its fallback are overridden at the dependency
boundary, so routing, ownership, the reuse decision, the background task, the
fallback decision and response encoding are exercised while nothing leaves the
machine.

Three properties here are not ordinary endpoint hygiene:

* **Ownership is resolved from the session, never from the request.** The
  route takes an application id; a client cannot name a company or a provider.
* **A reused snapshot must not spend.** Asserted on the provider's **call
  count**, because an endpoint that re-ran on every click would return an
  identical body and pass every body-shape test while billing each time.
* **`produced_by` is always truthful** (FR-005/FR-017): a fallback-produced
  result says `builtin` and arrives in the tiered shape with its verified
  excerpts, and a provider result says so with attribution-only sources.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.ports import (
    ProviderSource,
    ResearchOutcome,
    ResearchProviderRejected,
    ResearchProviderUnavailable,
    Usage,
)
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    Company,
    NormalizedStatus,
    User,
    normalize_company_name,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

pytestmark = pytest.mark.asyncio

JD = "Join our Parking Domain at Pango. Python, AWS, DynamoDB. Petah Tikva."


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


def _sections_research() -> dict[str, Any]:
    return {
        "company_identification": {
            "official_name": "Pango Pay & Go Ltd.",
            "website": "https://www.pango.co.il",
            "headquarters": "Petah Tikva, Israel",
            "how_identified": "Matched the posting's location and parking domain.",
        },
        "company_overview": "An Israeli smart-mobility company.",
        "products_and_services": "Mobile parking payments.",
        "business_and_market": "Transaction-fee SaaS.",
        "relevant_to_your_role": "Python and AWS at scale on the Parking team.",
        "what_to_know_before_the_interview": ["Owned by Milgam and Unicell."],
        "questions_worth_asking": ["How is DynamoDB scaled for peak traffic?"],
    }


def _tiered_research() -> dict[str, Any]:
    empty = {"claims": [], "empty_reason": "No public source covered this."}
    return {
        "what_the_company_does": {
            "claims": [
                {
                    "id": "c1",
                    "text": "Pango operates mobile parking payments.",
                    "tier": "fact",
                    "evidence": [{"source_id": "s1", "excerpt": "mobile parking payments"}],
                }
            ]
        },
        "products_and_services": empty,
        "market_and_customers": empty,
        "practical_facts": empty,
        "interview_preparation": empty,
    }


def _provider_outcome() -> ResearchOutcome:
    from careerhq.domain.schemas.research import ApplicationResearch

    return ResearchOutcome(
        research=ApplicationResearch.model_validate(_sections_research()),
        sources=(
            ProviderSource(source_id="s1", url="https://www.pango.co.il", title="Pango"),
            ProviderSource(source_id="s2", url="https://linkedin.com/company/pango", title="LI"),
        ),
        produced_by="provider:tavily-research",
        prompt_version="app-v1",
        cost_estimate=Decimal("0.456"),
        run_facts={"provider": "tavily-research", "model": "mini"},
    )


def _builtin_outcome() -> ResearchOutcome:
    from careerhq.domain.schemas.research import CompanyResearch

    return ResearchOutcome(
        research=CompanyResearch.model_validate(_tiered_research()),
        sources=(
            ProviderSource(
                source_id="s1",
                url="https://pango.co.il/about",
                title="About",
                excerpt="mobile parking payments",
            ),
        ),
        produced_by="builtin",
        prompt_version="v2-dense",
        usage=Usage(
            model="gemini/gemini-3.6-flash",
            input_tokens=100,
            output_tokens=50,
            cost=Decimal("0.01"),
        ),
    )


class ScriptedResearchProvider:
    """Answers from a finite script and **raises when it runs dry** — a double
    that repeats its last answer would make reuse look like spend and a retry
    loop look convergent (testing rule 8)."""

    def __init__(self, *answers: ResearchOutcome | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, str | None]] = []

    async def research(self, **kwargs: str | None) -> ResearchOutcome:
        self.calls.append(kwargs)
        if not self.answers:
            raise AssertionError("provider called more times than the script allows")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _wire(
    app: Any,
    provider: ScriptedResearchProvider,
    fallback: ScriptedResearchProvider | None = None,
) -> None:
    from careerhq.api.routes import research as route

    app.dependency_overrides[route.get_research_provider] = lambda: provider
    app.dependency_overrides[route.get_research_fallback] = lambda: fallback


async def _seed(
    session: AsyncSession, *, sub: str = "research-api", with_posting: bool = True
) -> tuple[User, Application]:
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Research API"}
    )
    company = Company(
        user_id=user.id,
        name="Pango",
        normalized_name=normalize_company_name("Pango"),
        domain="pango.co.il",
    )
    session.add(company)
    await session.flush()
    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Senior Back End Developer - Parking Team",
        job_description=JD if with_posting else None,
        requirements=[],
        status="Wishlist",
        normalized_status=NormalizedStatus.WISHLIST,
    )
    session.add(application)
    await session.commit()
    return user, application


# -- starting a run ----------------------------------------------------------


async def test_it_starts_research_and_returns_a_pollable_id(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    _wire(app, ScriptedResearchProvider(_provider_outcome()))
    user, application = await _seed(db_session, sub="res-start")

    response = await _as(client, user).post(f"/api/applications/{application.id}/research")

    assert response.status_code == 202, response.text
    body = response.json()
    assert uuid.UUID(body["snapshot_id"])
    assert body["reused"] is False


async def test_the_run_completes_with_the_sections_shape(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """The background task runs inline under the ASGI transport, so by the time
    the POST returns the work is done — an end-to-end assertion, not a check
    that a row was reserved."""
    provider = ScriptedResearchProvider(_provider_outcome())
    _wire(app, provider)
    user, application = await _seed(db_session, sub="res-complete")

    await _as(client, user).post(f"/api/applications/{application.id}/research")
    read = await _as(client, user).get(f"/api/applications/{application.id}/research")

    assert read.status_code == 200, read.text
    body = read.json()
    assert body["status"] == "succeeded"
    assert body["shape"] == "sections"
    assert body["produced_by"] == "provider:tavily-research"
    assert body["cost_basis"] == "estimate"
    assert body["research"]["company_identification"]["how_identified"]
    assert body["freshness"] == "fresh"
    # Provider sources are attribution, never verification (FR-010).
    assert [s["excerpt"] for s in body["sources"]] == [None, None]


async def test_the_provider_receives_the_posting_context_not_the_profile(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """FR-002: role and posting from the application; company from its row."""
    provider = ScriptedResearchProvider(_provider_outcome())
    _wire(app, provider)
    user, application = await _seed(db_session, sub="res-context")

    await _as(client, user).post(f"/api/applications/{application.id}/research")

    (call,) = provider.calls
    assert call["company_name"] == "Pango"
    assert call["domain"] == "pango.co.il"
    assert call["role_title"] == "Senior Back End Developer - Parking Team"
    assert call["posting_text"] == JD


async def test_no_research_yet_is_an_answer_not_an_error(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    _wire(app, ScriptedResearchProvider())
    user, application = await _seed(db_session, sub="res-none")

    response = await _as(client, user).get(f"/api/applications/{application.id}/research")

    assert response.status_code == 200
    assert response.json() == {"status": "none"}


# -- reuse spends nothing ----------------------------------------------------


async def test_a_second_request_reuses_and_spends_nothing(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """FR-013, asserted on the call count. The script holds exactly one answer,
    so a second spend would also blow up the double."""
    provider = ScriptedResearchProvider(_provider_outcome())
    _wire(app, provider)
    user, application = await _seed(db_session, sub="res-reuse")

    first = await _as(client, user).post(f"/api/applications/{application.id}/research")
    second = await _as(client, user).post(f"/api/applications/{application.id}/research")

    assert second.json()["reused"] is True
    assert second.json()["snapshot_id"] == first.json()["snapshot_id"]
    assert len(provider.calls) == 1


# -- ownership and sessions --------------------------------------------------


async def test_another_users_application_is_404_not_403(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    _wire(app, ScriptedResearchProvider())
    _, application = await _seed(db_session, sub="res-victim")
    intruder = await provision_user(
        db_session, {"sub": "res-intruder", "email": "res-intruder@example.com", "name": "I"}
    )
    await db_session.commit()

    response = await _as(client, intruder).post(f"/api/applications/{application.id}/research")
    assert response.status_code == 404


async def test_it_requires_a_session(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    _wire(app, ScriptedResearchProvider())
    _, application = await _seed(db_session, sub="res-anon")
    response = await client.post(f"/api/applications/{application.id}/research")
    assert response.status_code == 401


# -- concurrency -------------------------------------------------------------


async def test_a_second_request_while_one_is_running_is_refused(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    from careerhq.application.research_persistence import create_pending_application_research

    _wire(app, ScriptedResearchProvider())
    user, application = await _seed(db_session, sub="res-conflict")
    await create_pending_application_research(
        db_session, application, produced_by="provider:tavily-research"
    )
    await db_session.commit()

    response = await _as(client, user).post(f"/api/applications/{application.id}/research")
    assert response.status_code == 409


async def test_a_run_in_flight_is_reported_as_running(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    from careerhq.application.research_persistence import create_pending_application_research

    _wire(app, ScriptedResearchProvider())
    user, application = await _seed(db_session, sub="res-running")
    await create_pending_application_research(
        db_session, application, produced_by="provider:tavily-research"
    )
    await db_session.commit()

    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()
    assert body["status"] == "running"


# -- failure honesty ---------------------------------------------------------


async def test_a_failed_run_is_recorded_with_the_kind_not_the_detail(
    client: httpx.AsyncClient,
    app: Any,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The class name reaches the browser; anything more goes to the operator
    log — asserted on the record the ROUTE emitted, filtered by logger name
    (testing rule 11), not on whatever some layer underneath also logged."""
    _wire(app, ScriptedResearchProvider(ResearchProviderUnavailable("internal detail")))
    user, application = await _seed(db_session, sub="res-fail")

    with caplog.at_level("WARNING", logger="careerhq.api.routes.research"):
        await _as(client, user).post(f"/api/applications/{application.id}/research")

    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()
    assert body["status"] == "failed"
    assert body["failure_reason"] == "ResearchProviderUnavailable"
    assert "internal detail" not in body["failure_reason"]
    # SC-006: even a failed run carries a non-null cost basis.
    assert body["cost_basis"] in {"recorded", "estimate"}

    route_records = [r for r in caplog.records if r.name == "careerhq.api.routes.research"]
    assert len(route_records) == 1
    assert route_records[0].error == "ResearchProviderUnavailable"  # type: ignore[attr-defined]


async def test_a_failure_never_evicts_the_last_success(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    provider = ScriptedResearchProvider(_provider_outcome(), ResearchProviderRejected("bad output"))
    _wire(app, provider)
    user, application = await _seed(db_session, sub="res-evict")
    path = f"/api/applications/{application.id}/research"

    await _as(client, user).post(path)
    first = (await _as(client, user).get(path)).json()
    assert first["status"] == "succeeded"

    # Age the snapshot past the reuse window so the second POST actually runs.
    from sqlalchemy import text

    await db_session.execute(
        text("UPDATE application_research_snapshots SET retrieved_at = now() - interval '31 days'")
    )
    await db_session.commit()

    await _as(client, user).post(path)
    after = (await _as(client, user).get(path)).json()
    assert after["status"] == "succeeded", "the failed re-run must not evict the success"
    assert after["snapshot_id"] == first["snapshot_id"]


async def test_a_rejected_provider_never_falls_back(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """Bad output is a fact about the run; the fallback is for unavailability
    only (contract invariant 4). The fallback double's empty script would blow
    up if the route called it."""
    fallback = ScriptedResearchProvider()
    _wire(app, ScriptedResearchProvider(ResearchProviderRejected("schema")), fallback)
    user, application = await _seed(db_session, sub="res-noflbk")

    await _as(client, user).post(f"/api/applications/{application.id}/research")
    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()

    assert body["status"] == "failed"
    assert fallback.calls == []


# -- the fallback path -------------------------------------------------------


async def test_an_unavailable_provider_falls_back_and_says_so(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """FR-017: the degraded mode is recorded, tiered, and keeps its verified
    excerpts — the one thing the builtin path does better (FR-010)."""
    _wire(
        app,
        ScriptedResearchProvider(ResearchProviderUnavailable("down")),
        ScriptedResearchProvider(_builtin_outcome()),
    )
    user, application = await _seed(db_session, sub="res-fallback")

    await _as(client, user).post(f"/api/applications/{application.id}/research")
    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()

    assert body["status"] == "succeeded"
    assert body["shape"] == "tiered"
    assert body["produced_by"] == "builtin"
    assert body["cost_basis"] == "recorded"
    assert body["research"]["what_the_company_does"]["claims"][0]["tier"] == "fact"
    assert body["sources"][0]["excerpt"] == "mobile parking payments"
