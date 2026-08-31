"""Application research: start a run, and read the current one (slice 010).

Two endpoints, keyed on an **application**, and since slice 010 the research
itself is application-scoped too (decision 1A) — the role and posting come from
the job, never from the person (FR-002). Ownership still comes from the
session, never from the request: a client that names an application it does
not own gets a 404, and there is no request body a company name, model or
budget could arrive through.

**Where the outward-facing adapters are chosen.** `get_research_provider` and
`get_research_fallback` are declared here, in the API layer, for the same
reason `build_guideline_source` and 008's `get_web_search` were: `application/`
must import no infrastructure. The use case receives `ResearchProvider`
protocols and never learns that one of them is Tavily. Swapping the provider
is a configuration change surfacing as two lines in this file (FR-005).

**Reuse is per application** (FR-013): `POST` answers `reused: true` and
spends nothing when this application already has a fresh snapshot. Two
applications at the same employer each pay for and own their research — the
~3%-of-calls cost of that independence was measured before it was accepted
(specs/010 research.md D6).

**The read path serves three shapes** (FR-014): the new sections shape
(`app-v1`), the tiered fallback shape (`v2-dense`), and 008-era company
snapshots — served only when the application has no snapshot of its own, as
`produced_by: "legacy-company"`, a value derived here and never stored.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select

from careerhq.api.deps import CurrentUser, DbSession
from careerhq.application.ports import ResearchProvider
from careerhq.application.research_application import (
    ResearchContext,
    context_for,
    perform_research,
)
from careerhq.application.research_persistence import (
    ConcurrentResearchRun,
    complete_application_research,
    create_pending_application_research,
    current_application_research,
    current_company_research,
    fail_research,
    reusable_application_research,
)
from careerhq.application.research_windows import freshness
from careerhq.config import get_settings
from careerhq.domain.models import (
    Application,
    ApplicationResearchSnapshot,
    Company,
    CompanyResearchSnapshot,
    ResearchSource,
)
from careerhq.infrastructure.database import get_session_factory
from careerhq.infrastructure.research.builtin_provider import BuiltinResearch
from careerhq.infrastructure.research.tavily_research import TavilyResearch

logger = logging.getLogger(__name__)

router = APIRouter(tags=["research"])

#: prompt_version → the `shape` the response declares. The frontend dispatches
#: renderers on this field and never sniffs the payload (api-research.md).
_SHAPES = {"app-v1": "sections", "v2-dense": "tiered"}


def get_research_provider() -> ResearchProvider:
    """The primary research producer, from configuration. Overridden in tests."""
    if get_settings().research_provider == "builtin":
        return BuiltinResearch()
    return TavilyResearch()


def get_research_fallback() -> ResearchProvider | None:
    """What a provider failure runs, or `None` for an honest failure (D8).

    `None` when the builtin pipeline *is* the primary — falling back to
    yourself would retry a failure while claiming to have degraded.
    """
    settings = get_settings()
    if settings.research_provider == "builtin" or not settings.research_fallback_enabled:
        return None
    return BuiltinResearch()


ProviderClient = Annotated[ResearchProvider, Depends(get_research_provider)]
FallbackClient = Annotated[ResearchProvider | None, Depends(get_research_fallback)]


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
    context: ResearchContext,
    provider: ResearchProvider,
    fallback: ResearchProvider | None,
) -> None:
    """Own session: the request's is closed by the time this runs.

    **A failure is recorded, never swallowed**, and it carries whatever cost
    basis the exception did (SC-006) — slice 005's $0.506821 of invisible spend
    is why. The read path never prefers a failed row over a success, so failing
    here cannot evict the previous research.
    """
    async with get_session_factory()() as session:
        snapshot = await session.get(ApplicationResearchSnapshot, snapshot_id)
        if snapshot is None:  # pragma: no cover - the row was just committed
            return
        try:
            outcome = await perform_research(context, provider=provider, fallback=fallback)
        except Exception as exc:
            logger.warning(
                "application research failed",
                extra={"snapshot_id": str(snapshot_id), "error": exc.__class__.__name__},
            )
            estimate = getattr(exc, "cost_estimate", None)
            await fail_research(
                session,
                snapshot,
                exc.__class__.__name__,
                cost_estimate=estimate if isinstance(estimate, Decimal) else None,
            )
            await session.commit()
            return

        await complete_application_research(session, snapshot, outcome=outcome)
        await session.commit()


@router.post(
    "/applications/{application_id}/research",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Research this company for this application",
)
async def start_research(
    application_id: uuid.UUID,
    background: BackgroundTasks,
    session: DbSession,
    user: CurrentUser,
    provider: ProviderClient,
    fallback: FallbackClient,
) -> dict[str, Any]:
    """Start a run, or answer with the snapshot already worth reusing (FR-013).

    **No request body.** A company name, model or source budget accepted from
    the client would put both cost and *whose data this is* under the
    browser's control.
    """
    application = await _owned_application(session, user, application_id)
    company = await session.get(Company, application.company_id)
    if company is None:  # pragma: no cover - a company row is required by the FK
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found.")

    existing = await reusable_application_research(session, application)
    if existing is not None:
        return {"snapshot_id": str(existing.id), "status": existing.status, "reused": True}

    settings = get_settings()
    intended = "builtin" if settings.research_provider == "builtin" else "provider:tavily-research"
    try:
        snapshot = await create_pending_application_research(
            session, application, produced_by=intended
        )
    except ConcurrentResearchRun as exc:
        # 409 rather than 202. The partial unique index is the real enforcement;
        # this is its surface. Success here would let five clicks bill five runs.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # The context is assembled while the entities are in session — the
    # background task must not lazy-load anything (MissingGreenlet).
    context = context_for(application, company)

    await session.commit()
    background.add_task(_research_in_background, snapshot.id, context, provider, fallback)
    return {"snapshot_id": str(snapshot.id), "status": snapshot.status, "reused": False}


def _payload(
    snapshot: ApplicationResearchSnapshot | CompanyResearchSnapshot,
    *,
    shape: str,
    produced_by: str,
    cost_basis: str,
    sources: list[ResearchSource],
) -> dict[str, Any]:
    return {
        "snapshot_id": str(snapshot.id),
        "status": snapshot.status,
        "shape": shape,
        "produced_by": produced_by,
        # The kind of failure reaches the browser; the detail went to the log
        # where it was recorded (the project's error-disclosure rule).
        "failure_reason": snapshot.failure_reason,
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        # Derived at read time, never stored: a row keeps ageing.
        "freshness": freshness(snapshot.retrieved_at).value,
        "cost": str(snapshot.cost),
        "cost_basis": cost_basis,
        "research": snapshot.sections,
        "sources": [
            {
                "source_id": s.source_id,
                "url": s.url,
                "title": s.title,
                "fetch_status": s.fetch_status,
                #: Non-null means verified verbatim against a fetched page;
                #: provider sources carry null and render as attribution
                #: (FR-010).
                "excerpt": s.excerpt,
            }
            for s in sources
        ],
    }


@router.get(
    "/applications/{application_id}/research",
    summary="The current research for this application",
)
async def read_research(
    application_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """What to show, in T093's order; `{"status": "none"}` for a blank slate.

    An explicit "none" rather than a 404: an application nobody has researched
    is the normal starting state, not a failure.
    """
    application = await _owned_application(session, user, application_id)

    snapshot = await current_application_research(session, application)
    if snapshot is not None:
        sources = (
            await session.scalars(
                select(ResearchSource)
                .where(ResearchSource.application_snapshot_id == snapshot.id)
                .order_by(ResearchSource.source_id)
            )
        ).all()
        return _payload(
            snapshot,
            shape=_SHAPES.get(snapshot.prompt_version or "", "tiered"),
            produced_by=snapshot.produced_by,
            cost_basis=snapshot.cost_basis,
            sources=list(sources),
        )

    # Legacy leg (FR-014): an 008-era company snapshot is shown only when the
    # application has no snapshot of its own — never over one.
    company = await session.get(Company, application.company_id)
    if company is not None:
        legacy = await current_company_research(session, company)
        if legacy is not None:
            sources = (
                await session.scalars(
                    select(ResearchSource)
                    .where(ResearchSource.company_snapshot_id == legacy.id)
                    .order_by(ResearchSource.source_id)
                )
            ).all()
            return _payload(
                legacy,
                shape="tiered",
                produced_by="legacy-company",
                #: Legacy rows recorded exact seam usage; saying "estimate"
                #: would launder a recorded figure into a vaguer one.
                cost_basis="recorded",
                sources=list(sources),
            )

    return {"status": "none"}


__all__ = ["get_research_fallback", "get_research_provider", "router"]
