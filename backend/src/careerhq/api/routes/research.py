"""Company research: start a run, and read the current one.

Two endpoints, both keyed on an **application** even though the research itself
is company-scoped. That is deliberate: the interface reaches this from a job's
"Company research" tab, and — more importantly — **ownership comes from the
session, never from the request**. A client that could name a company could name
someone else's; a client that names an application it does not own gets a 404.

**Where the outward-facing adapters are chosen.** `get_web_search` and
`get_source_fetcher` are declared here, in the API layer, for the same reason
`build_guideline_source` is: `application/` must import no infrastructure. The
use case receives `WebSearch` and `SourceFetcher` protocols and never learns that
one of them is Tavily. Swapping the provider is a change to two lines in this
file — which is how five different search and synthesis backends were compared
without touching the pipeline.

**Reuse is the economics of the whole slice** (FR-013, OQ-E). Layer 1 is paid for
**once per employer** and reused by every application to it inside the 30-day
window. So `POST` answers `reused: true` and spends nothing when a fresh snapshot
exists. An endpoint that re-ran on every click would return an identical body,
pass every functional test, and bill on each one.

**The read path is T093's**, inherited from slice 004 including its correction: an
in-flight run is preferred *while it is plausibly in flight*, then the pointer,
then the newest row. Preferring the pointer unconditionally made slice 004's
interface stop polling on its first poll and miss the result thirteen seconds
later.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select

from careerhq.api.deps import CompletionClient, CurrentUser, DbSession
from careerhq.application.ports import SourceFetcher, StructuredCompletion, WebSearch
from careerhq.application.research_company import research_company
from careerhq.application.research_persistence import (
    ConcurrentResearchRun,
    complete_company_research,
    create_pending_company_research,
    current_company_research,
    fail_research,
    reusable_company_research,
)
from careerhq.application.research_windows import freshness
from careerhq.domain.models import Application, Company, CompanyResearchSnapshot, ResearchSource
from careerhq.infrastructure.database import get_session_factory
from careerhq.infrastructure.research import TavilySearch, WebSourceFetcher

logger = logging.getLogger(__name__)

router = APIRouter(tags=["research"])


def get_web_search() -> WebSearch:
    """The search provider. Overridden in tests; never reached by `application/`."""
    return TavilySearch()


def get_source_fetcher() -> SourceFetcher:
    """Page retrieval, through the shared SSRF guard in `infrastructure/jobs/fetch.py`."""
    return WebSourceFetcher()


#: Declared here rather than in `deps.py` so the search and fetch adapters stay
#: next to the one route that uses them; `deps.py` holds what several routers
#: share.
SearchClient = Annotated[WebSearch, Depends(get_web_search)]
FetcherClient = Annotated[SourceFetcher, Depends(get_source_fetcher)]


async def _owned_application(
    session: DbSession, user: CurrentUser, application_id: uuid.UUID
) -> Application:
    record = await session.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return record


async def _research_in_background(
    snapshot_id: uuid.UUID,
    company_name: str,
    domain: str | None,
    search: WebSearch,
    fetcher: SourceFetcher,
    completion: StructuredCompletion,
) -> None:
    """Own session: the request's is closed by the time this runs.

    **A failure is recorded, never swallowed.** Slice 005 lost $0.506821 to three
    runs that recorded nothing and therefore reported `$0`, which reads as free
    when the calls had already been billed. `fail_research` deliberately does not
    touch the pointer, so a failed re-run leaves the previous research standing.
    """
    async with get_session_factory()() as session:
        snapshot = await session.get(CompanyResearchSnapshot, snapshot_id)
        if snapshot is None:  # pragma: no cover - the row was just committed
            return
        try:
            result = await research_company(
                company_name=company_name,
                domain=domain,
                search=search,
                fetcher=fetcher,
                completion=completion,
            )
        except Exception as exc:
            logger.warning(
                "company research failed",
                extra={"snapshot_id": str(snapshot_id), "error": exc.__class__.__name__},
            )
            await fail_research(session, snapshot, exc.__class__.__name__)
            await session.commit()
            return

        await complete_company_research(
            session,
            snapshot,
            research=result.research,
            sources=result.sources,
            failed_urls=result.failed_urls,
            usages=(result.usage,),
        )
        await session.commit()


@router.post(
    "/applications/{application_id}/research",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Research this company",
)
async def start_research(
    application_id: uuid.UUID,
    background: BackgroundTasks,
    session: DbSession,
    user: CurrentUser,
    completion: CompletionClient,
    search: SearchClient,
    fetcher: FetcherClient,
) -> dict[str, Any]:
    """Start Layer 1, or answer with the snapshot already worth reusing (FR-013).

    **No request body.** A company name, model or source budget accepted from the
    client would put both cost and *whose data this is* under the browser's
    control.
    """
    application = await _owned_application(session, user, application_id)
    company = await session.get(Company, application.company_id)
    if company is None:  # pragma: no cover - a company row is required by the FK
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found.")

    existing = await reusable_company_research(session, company)
    if existing is not None:
        return {"snapshot_id": str(existing.id), "status": existing.status, "reused": True}

    try:
        snapshot = await create_pending_company_research(session, company)
    except ConcurrentResearchRun as exc:
        # 409 rather than 202. The partial unique index is the real enforcement;
        # this is its surface. Success here would let five clicks bill five runs.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await session.commit()
    background.add_task(
        _research_in_background,
        snapshot.id,
        company.name,
        company.domain,
        search,
        fetcher,
        completion,
    )
    return {"snapshot_id": str(snapshot.id), "status": snapshot.status, "reused": False}


@router.get(
    "/applications/{application_id}/research",
    summary="The current research for this job's company",
)
async def read_research(
    application_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any] | None:
    """What to show, in T093's order. `None` for a company nobody has researched.

    **`None` is an answer, not an error.** A 404 would make the tab render a
    failure for every application whose employer has not been researched yet,
    which is the normal starting state.
    """
    application = await _owned_application(session, user, application_id)
    company = await session.get(Company, application.company_id)
    if company is None:  # pragma: no cover
        return None

    snapshot = await current_company_research(session, company)
    if snapshot is None:
        return None

    sources = (
        await session.scalars(
            select(ResearchSource)
            .where(ResearchSource.company_snapshot_id == snapshot.id)
            .order_by(ResearchSource.source_id)
        )
    ).all()

    return {
        "snapshot_id": str(snapshot.id),
        "company": company.name,
        "status": snapshot.status,
        "failure_reason": snapshot.failure_reason,
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        # Derived at read time, never stored: a row keeps ageing, so a label
        # frozen at write time would be wrong the day after it was written.
        "freshness": freshness(snapshot.retrieved_at).value,
        "sections": snapshot.sections,
        "sources": [
            {
                "source_id": s.source_id,
                "url": s.url,
                "title": s.title,
                "fetch_status": s.fetch_status,
                # The excerpt is what makes a claim checkable, which is the
                # feature: a brief the reader cannot verify is worth less than
                # none.
                "excerpt": s.excerpt,
            }
            for s in sources
        ],
    }


__all__ = ["get_source_fetcher", "get_web_search", "router"]
