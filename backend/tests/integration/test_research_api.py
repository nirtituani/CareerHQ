"""The company-research endpoints, over the real ASGI app.

Search, fetch and the completion seam are all overridden, so routing, ownership,
the reuse decision, the background task and response encoding are exercised while
nothing leaves the machine (FR-045's rule, applied to a slice that has two more
outbound edges than slice 005 did).

Three properties here are not ordinary endpoint hygiene:

* **Ownership is resolved from the session, never from the request.** The route
  takes an application id and derives the company from it; a client cannot name a
  company, so it cannot name someone else's.
* **A reused snapshot must not spend.** FR-013's whole economic argument is that
  Layer 1 is paid for once per employer. An endpoint that re-ran on every click
  would satisfy every other test and quietly bill on each one, so the count of
  model calls is asserted rather than the response body alone.
* **A run in flight is reported as such** (T093). Preferring the pointer
  unconditionally is what made slice 004's interface stop polling on its first
  poll and miss the result thirteen seconds later.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.api.deps import get_structured_completion
from careerhq.application.provision_user import provision_user
from careerhq.application.research_company import TASK_SYNTHESISE_COMPANY
from careerhq.domain.models import (
    Application,
    Company,
    CompanyResearchSnapshot,
    NormalizedStatus,
    ResearchStatus,
    User,
    normalize_company_name,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.scripted_seam import ScriptedSeam

pytestmark = pytest.mark.asyncio

PAGE = (
    "Acme Robotics builds warehouse automation for European retailers. "
    "The company was founded in 2019 and employs about two hundred people."
)


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


def _brief() -> dict[str, Any]:
    """One quotable fact, so the verbatim check has something real to pass."""
    empty = {"claims": [], "empty_reason": "No public source covered this."}
    return {
        "what_the_company_does": {
            "claims": [
                {
                    "id": "c1",
                    "text": "Acme builds warehouse automation.",
                    "tier": "fact",
                    "evidence": [{"source_id": "s1", "excerpt": "builds warehouse automation"}],
                }
            ]
        },
        "products_and_services": empty,
        "market_and_customers": empty,
        "practical_facts": empty,
        "interview_preparation": empty,
    }


class _Search:
    """A `WebSearch` double. Records every query so reuse can be proved."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, *, query: str, limit: int) -> list[Any]:
        from careerhq.application.ports import SearchHit

        self.queries.append(query)
        return [SearchHit(url="https://acme.example/about", title="About Acme", snippet="s")]


class _Fetcher:
    """A `SourceFetcher` double. `source_id` is assigned by the use case."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    async def fetch(self, *, url: str) -> Any:
        from careerhq.application.ports import FetchedSource

        self.requested.append(url)
        return FetchedSource(url=url, title="About Acme", text=PAGE, source_id="")


def _wire(app: Any, *, answers: int = 1) -> tuple[ScriptedSeam, _Search, _Fetcher]:
    from careerhq.api.routes import research as route

    seam = ScriptedSeam(script={TASK_SYNTHESISE_COMPANY: [_brief() for _ in range(answers)]})
    search, fetcher = _Search(), _Fetcher()
    app.dependency_overrides[get_structured_completion] = lambda: seam
    app.dependency_overrides[route.get_web_search] = lambda: search
    app.dependency_overrides[route.get_source_fetcher] = lambda: fetcher
    return seam, search, fetcher


async def _seed(session: AsyncSession, *, sub: str = "research-api") -> tuple[User, Application]:
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Research API"}
    )
    company = Company(
        user_id=user.id,
        name="Acme Robotics",
        normalized_name=normalize_company_name("Acme Robotics"),
    )
    session.add(company)
    await session.flush()
    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Backend Engineer",
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
    _wire(app)
    user, application = await _seed(db_session, sub="res-start")

    response = await _as(client, user).post(f"/api/applications/{application.id}/research")

    assert response.status_code == 202, response.text
    body = response.json()
    assert uuid.UUID(body["snapshot_id"])
    assert body["reused"] is False


async def test_the_run_completes_and_is_readable(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """The background task runs inline under the ASGI transport, so by the time
    the POST returns the work is done — which is what makes this a real
    end-to-end assertion rather than a check that a row was reserved."""
    _wire(app)
    user, application = await _seed(db_session, sub="res-complete")

    await _as(client, user).post(f"/api/applications/{application.id}/research")
    read = await _as(client, user).get(f"/api/applications/{application.id}/research")

    assert read.status_code == 200, read.text
    body = read.json()
    assert body["status"] == "succeeded"
    assert body["sections"]["what_the_company_does"]["claims"][0]["tier"] == "fact"
    assert body["sources"][0]["url"] == "https://acme.example/about"
    assert body["freshness"] == "fresh"


async def test_no_research_yet_is_an_answer_not_an_error(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """An employer nobody has researched is the normal starting state. A 404
    would make the tab render an error for every new application."""
    _wire(app)
    user, application = await _seed(db_session, sub="res-none")

    response = await _as(client, user).get(f"/api/applications/{application.id}/research")

    assert response.status_code == 200
    assert response.json() is None


# -- reuse: the economic argument, enforced ---------------------------------


async def test_a_second_request_reuses_and_spends_nothing(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """FR-013. Layer 1 is paid for once per employer and reused across every
    application to it. Asserted on the **call count**, because an endpoint that
    re-ran each time would return an identical body and pass every other test
    while billing on every click."""
    seam, search, _ = _wire(app, answers=2)
    user, application = await _seed(db_session, sub="res-reuse")

    first = await _as(client, user).post(f"/api/applications/{application.id}/research")
    second = await _as(client, user).post(f"/api/applications/{application.id}/research")

    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert second.json()["snapshot_id"] == first.json()["snapshot_id"]
    assert len(seam.calls) == 1, f"reuse still spent a completion: {len(seam.calls)} calls"
    assert len(search.queries) <= 6, "a reused run still searched the web"


# -- ownership ---------------------------------------------------------------


async def test_another_users_application_is_404_not_403(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """A 403 would confirm the id names something real."""
    _wire(app)
    _alice, application = await _seed(db_session, sub="res-alice")
    bob = await provision_user(
        db_session, {"sub": "res-bob", "email": "res-bob@example.com", "name": "Bob"}
    )
    await db_session.commit()

    for method in ("get", "post"):
        response = await getattr(_as(client, bob), method)(
            f"/api/applications/{application.id}/research"
        )
        assert response.status_code == 404, f"{method} leaked existence: {response.text}"


async def test_it_requires_a_session(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    _wire(app)
    _user, application = await _seed(db_session, sub="res-anon")
    client.cookies.clear()

    assert (await client.get(f"/api/applications/{application.id}/research")).status_code == 401
    assert (await client.post(f"/api/applications/{application.id}/research")).status_code == 401


# -- a run in flight (T093) --------------------------------------------------


async def test_a_run_in_flight_is_reported_as_running(
    client: httpx.AsyncClient,
    app: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Preferring the pointer unconditionally is what made slice 004's interface
    stop polling on its first poll."""
    _wire(app)
    user, application = await _seed(db_session, sub="res-inflight")
    company = await db_session.get(Company, application.company_id)
    assert company is not None
    db_session.add(
        CompanyResearchSnapshot(
            user_id=user.id,
            company_id=company.id,
            sections={},
            status=ResearchStatus.RUNNING,
        )
    )
    await db_session.commit()

    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()
    assert body["status"] == "running"


async def test_a_second_request_while_one_is_running_is_refused(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """409, not 202. The partial unique index is the real enforcement; this is
    its surface. Returning success would let five clicks queue five paid runs."""
    _wire(app)
    user, application = await _seed(db_session, sub="res-conflict")
    company = await db_session.get(Company, application.company_id)
    assert company is not None
    db_session.add(
        CompanyResearchSnapshot(
            user_id=user.id,
            company_id=company.id,
            sections={},
            status=ResearchStatus.RUNNING,
        )
    )
    await db_session.commit()

    response = await _as(client, user).post(f"/api/applications/{application.id}/research")
    assert response.status_code == 409, response.text


# -- failure is recorded, not hidden ----------------------------------------


async def test_a_failed_run_is_recorded_and_readable(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """Slice 005 lost $0.50 to runs that recorded nothing and read as free."""
    from careerhq.api.routes import research as route

    seam = ScriptedSeam(script={TASK_SYNTHESISE_COMPANY: []})  # raises: no answers
    app.dependency_overrides[get_structured_completion] = lambda: seam
    app.dependency_overrides[route.get_web_search] = lambda: _Search()
    app.dependency_overrides[route.get_source_fetcher] = lambda: _Fetcher()
    user, application = await _seed(db_session, sub="res-fail")

    await _as(client, user).post(f"/api/applications/{application.id}/research")
    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()

    assert body["status"] == "failed"
    assert body["failure_reason"]


async def test_a_failed_run_does_not_become_the_current_pointer(
    client: httpx.AsyncClient,
    app: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-014. A failed re-run must leave the previous research standing."""
    from careerhq.api.routes import research as route

    _wire(app)
    user, application = await _seed(db_session, sub="res-failafter")
    await _as(client, user).post(f"/api/applications/{application.id}/research")

    good = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()
    assert good["status"] == "succeeded"

    # Age it past the reuse window so the next request runs rather than reuses.
    async with session_factory() as s:
        from sqlalchemy import text as sql

        await s.execute(
            sql("UPDATE company_research_snapshots SET retrieved_at = now() - interval '60 days'")
        )
        await s.commit()

    broken = ScriptedSeam(script={TASK_SYNTHESISE_COMPANY: []})
    app.dependency_overrides[get_structured_completion] = lambda: broken
    app.dependency_overrides[route.get_web_search] = lambda: _Search()
    app.dependency_overrides[route.get_source_fetcher] = lambda: _Fetcher()
    await _as(client, user).post(f"/api/applications/{application.id}/research")

    async with session_factory() as s:
        company = await s.get(Company, application.company_id)
        assert company is not None
        assert company.current_research_snapshot_id == uuid.UUID(good["snapshot_id"]), (
            "a failed re-run moved the pointer away from good research"
        )


# -- the response is what the interface needs -------------------------------


async def test_the_response_carries_the_citation_evidence(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """Every claim is shown with what backs it, which is the point of the
    feature — a brief the reader cannot check is worth less than none."""
    _wire(app)
    user, application = await _seed(db_session, sub="res-evidence")
    await _as(client, user).post(f"/api/applications/{application.id}/research")

    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()
    claim = body["sections"]["what_the_company_does"]["claims"][0]
    assert claim["evidence"][0]["excerpt"] == "builds warehouse automation"
    assert claim["evidence"][0]["source_id"] == "s1"
    assert {s["source_id"] for s in body["sources"]} >= {"s1"}


async def test_the_snapshot_is_dated_so_the_reader_can_weigh_it(
    client: httpx.AsyncClient, app: Any, db_session: AsyncSession
) -> None:
    """US3: the retrieval timestamp is displayed prominently, and staleness is a
    derived label rather than a stored one."""
    _wire(app)
    user, application = await _seed(db_session, sub="res-dated")
    await _as(client, user).post(f"/api/applications/{application.id}/research")

    body = (await _as(client, user).get(f"/api/applications/{application.id}/research")).json()
    assert body["retrieved_at"]
    assert body["freshness"] in ("fresh", "stale")
