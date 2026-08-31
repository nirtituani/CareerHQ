"""Writing research to the database — application-scoped since slice 010.

**No repository abstraction, deliberately.** This codebase has none: every use
case takes an `AsyncSession` and writes through the ORM. What is shared here is
*mechanics*, so no caller invents its own.

**The pure use cases stay pure.** The provider adapters return a
`ResearchOutcome` and touch no session; this module is what turns one into
rows. That separation keeps the pipeline testable with no database and no
provider.

**Two phases, because a status change is not observable until it commits.** A
`running` row is created and committed first, then the work runs, then the
result is written. Slice 005 skipped this and its interface showed "Writing"
for an entire run.

**Slice 010 reshape.** Research is per application (decision 1A): the write
path targets `ApplicationResearchSnapshot`, the reuse question is asked against
the application's own newest success, and there is **no pointer column** —
unlike 008's company pointer, which arbitrated reuse *across* applications, a
per-application scope has exactly one candidate ordering, so `retrieved_at`
plus the one-running guard answer it. `CompanyResearchSnapshot` is read-only
from this slice: its write path is gone, and `current_company_research`
remains only so 008-era history keeps rendering (FR-014).

**Failure never evicts the last success**, structurally: the read path prefers
a live in-flight row, then the newest *succeeded* row — a `failed` row is
reachable only when nothing ever succeeded, which is exactly when it is the
honest thing to show.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.ports import ResearchOutcome, Usage
from careerhq.application.research_windows import is_reusable
from careerhq.config import get_settings
from careerhq.domain.models import (
    Application,
    ApplicationResearchSnapshot,
    Company,
    CompanyResearchSnapshot,
    ResearchSource,
    ResearchStatus,
)

logger = logging.getLogger(__name__)


class ConcurrentResearchRun(RuntimeError):
    """A run for this application is already in flight.

    **Raised from the database's refusal, not from a prior read.** Two requests
    are two transactions, and the window between a check and an insert is
    exactly where a double-click lands; the partial unique index in `0020` is
    the guard, and this type is how its refusal reaches a caller.

    A distinct type because "one is already running" is an ordinary state a
    route should answer as such — not a 500, and not a reason to start a second
    paid run. An *abandoned* run must not raise this: `create_pending` treats a
    row past the duration bound as replaceable, or a stuck run would need
    hand-written SQL to clear (the slice 005 lesson, three times over).
    """


def _is_running_conflict(exc: IntegrityError, index_name: str) -> bool:
    """Whether this violation is the in-flight guard rather than another one.

    Matched by index name so an unrelated constraint — the one-of-two source
    ownership check, a foreign key — is re-raised rather than reported as a
    concurrent run.
    """
    return index_name in str(getattr(exc, "orig", exc))


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def is_abandoned(
    snapshot: ApplicationResearchSnapshot | CompanyResearchSnapshot,
    *,
    now: datetime | None = None,
) -> bool:
    """Whether a `running` row has outlived any run that could finish it.

    Bounded by `research_max_duration_seconds` — the same number that bounds
    the run itself, because a run past its own bound is precisely a run nothing
    will finish; two constants would eventually disagree and either reap a live
    run or block a retry forever. The row itself is never rewritten by a
    reader: abandonment is a judgement made at read time (FR-016).
    """
    if snapshot.status != ResearchStatus.RUNNING:
        return False
    moment = now or datetime.now(UTC)
    limit = get_settings().research_max_duration_seconds
    return (moment - _aware(snapshot.retrieved_at)).total_seconds() > limit


# -- application-scoped research (slice 010) ---------------------------------


async def reusable_application_research(
    session: AsyncSession,
    application: Application,
    *,
    context_fingerprint: str | None = None,
    now: datetime | None = None,
) -> ApplicationResearchSnapshot | None:
    """The snapshot fresh enough — and about the same job — to skip a re-run.

    Per application (decision 1A): the newest *succeeded* row inside the reuse
    window. A run still in flight is not reusable — this is a spend decision,
    and the caller answers an in-flight run with a conflict, not a reuse.

    When `context_fingerprint` is given, the stored fingerprint must match it
    (review fix, US2 acceptance 2): research produced for a different posting
    context — company-only before a JD was pasted, or an edited JD — is not a
    reuse candidate, whatever its age. A snapshot that stored no fingerprint
    never matches one, because "unknown context" cannot honestly answer
    "same context".
    """
    latest = await session.scalar(
        select(ApplicationResearchSnapshot)
        .where(
            ApplicationResearchSnapshot.application_id == application.id,
            ApplicationResearchSnapshot.status == ResearchStatus.SUCCEEDED,
        )
        .order_by(ApplicationResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    if latest is None:
        return None
    if not is_reusable(latest.retrieved_at, now=now):
        return None
    if context_fingerprint is not None:
        stored = (latest.model_config_used or {}).get("context_fingerprint")
        if stored != context_fingerprint:
            return None
    return latest


async def create_pending_application_research(
    session: AsyncSession,
    application: Application,
    *,
    produced_by: str,
    abandoned_cost_estimate: Decimal | None = None,
    now: datetime | None = None,
) -> ApplicationResearchSnapshot:
    """Reserve a row for a run. Committing it is the caller's job.

    `produced_by` records the *configured intent* at creation and is finalised
    at completion — a provider run that fell back to the builtin pipeline must
    end up saying so (FR-005/FR-017). `cost_basis` starts as `estimate` for the
    same reason: it is corrected by what the outcome actually carried, and a
    `running` row's figure is a placeholder either way.

    Raises `ConcurrentResearchRun` when one is already in flight — unless that
    row is abandoned, in which case it is marked failed and the new run takes
    its place, because a guard that refuses the one action that recovers a
    stuck run is worse than the stuck run.
    """
    in_flight = await session.scalar(
        select(ApplicationResearchSnapshot)
        .where(
            ApplicationResearchSnapshot.application_id == application.id,
            ApplicationResearchSnapshot.status == ResearchStatus.RUNNING,
        )
        # The identity map would happily answer with a stale copy of this row —
        # the abandonment judgement reads `retrieved_at`, so it must see what
        # the database holds, not what this session last saw (the "is against
        # an enum" family of gotcha, pointed at a timestamp).
        .execution_options(populate_existing=True)
    )
    if in_flight is not None and is_abandoned(in_flight, now=now):
        # The stuck run plausibly billed before it died; the caller supplies
        # the documented estimate so the failed row does not read as free
        # (review fix). None when the attempt's spend is unknowable.
        await fail_research(
            session, in_flight, "AbandonedRun", cost_estimate=abandoned_cost_estimate
        )

    snapshot = ApplicationResearchSnapshot(
        user_id=application.user_id,
        application_id=application.id,
        sections={},
        produced_by=produced_by,
        cost_basis="estimate",
        status=ResearchStatus.RUNNING,
    )
    session.add(snapshot)
    try:
        await session.flush()
    except IntegrityError as exc:
        if _is_running_conflict(exc, "uq_application_research_one_running_per_application"):
            raise ConcurrentResearchRun("research is already running for this application") from exc
        raise
    return snapshot


async def complete_application_research(
    session: AsyncSession,
    snapshot: ApplicationResearchSnapshot,
    *,
    outcome: ResearchOutcome,
    context_fingerprint: str | None = None,
) -> None:
    """Write a finished run — sections, provenance, accounting, sources.

    `cost_basis` is derived from which cost the outcome carried, never passed
    by a caller: exactly one of `usage`/`cost_estimate` is set (the outcome's
    own invariant), so the derivation cannot be wrong without the outcome being
    invalid first (D5).
    """
    # Terminal is terminal (Principle IV, review fix). The caller's ORM copy
    # can be stale — the abandoned-run replacement may have marked this row
    # failed from another session while the original task was still running —
    # so the status is re-read from the database, not trusted from memory.
    await session.refresh(snapshot)
    if snapshot.status != ResearchStatus.RUNNING:
        logger.warning(
            "stale research completion discarded",
            extra={"snapshot_id": str(snapshot.id), "status": snapshot.status},
        )
        return

    snapshot.sections = outcome.research.model_dump(mode="json")
    snapshot.produced_by = outcome.produced_by
    snapshot.prompt_version = outcome.prompt_version
    snapshot.status = ResearchStatus.SUCCEEDED

    facts: dict[str, object] = dict(outcome.run_facts)
    if context_fingerprint is not None:
        #: What this research was produced from — the reuse decision's other
        #: half (review fix, US2 acceptance 2).
        facts["context_fingerprint"] = context_fingerprint
    if outcome.usage is not None:
        snapshot.input_tokens = outcome.usage.input_tokens
        snapshot.output_tokens = outcome.usage.output_tokens
        snapshot.cost = outcome.usage.cost
        snapshot.cost_basis = "recorded"
        facts.setdefault("models", [outcome.usage.model])
    else:
        snapshot.input_tokens = 0
        snapshot.output_tokens = 0
        assert outcome.cost_estimate is not None  # the outcome's own invariant
        snapshot.cost = outcome.cost_estimate
        snapshot.cost_basis = "estimate"
    snapshot.model_config_used = facts or None

    for source in outcome.sources:
        session.add(
            ResearchSource(
                application_snapshot_id=snapshot.id,
                source_id=source.source_id,
                url=source.url,
                title=source.title,
                #: None for provider sources — attribution, not verification
                #: (FR-010). The builtin path fills it from its verbatim check.
                excerpt=source.excerpt,
                fetch_status=source.fetch_status,
            )
        )
    await session.flush()


async def fail_research(
    session: AsyncSession,
    snapshot: ApplicationResearchSnapshot | CompanyResearchSnapshot,
    reason: str,
    *,
    cost_estimate: Decimal | None = None,
    usage: Usage | None = None,
) -> None:
    """A failed run is a recorded run, not an absent one.

    Slice 005 lost $0.506821 to runs that recorded nothing and therefore read
    as free. `cost_estimate`, when the failure carried one, lands with its
    basis — an estimate of what was spent before the failure — so SC-006 holds
    on failures too. The read path never prefers a failed row over a success,
    which is what "failure never evicts the last research" means structurally.
    """
    await session.refresh(snapshot)
    if snapshot.status != ResearchStatus.RUNNING:
        logger.warning(
            "stale research failure discarded",
            extra={"snapshot_id": str(snapshot.id), "status": snapshot.status},
        )
        return

    snapshot.status = ResearchStatus.FAILED
    snapshot.failure_reason = reason
    if isinstance(snapshot, ApplicationResearchSnapshot):
        if usage is not None:
            # An exception that carries exact seam usage (the builtin path's
            # ExtractionFailedError) records it as `recorded` — a billed
            # synthesis must never read as free (review fix, slice-005 lesson).
            snapshot.input_tokens = usage.input_tokens
            snapshot.output_tokens = usage.output_tokens
            snapshot.cost = usage.cost
            snapshot.cost_basis = "recorded"
        elif cost_estimate is not None:
            snapshot.cost = cost_estimate
            snapshot.cost_basis = "estimate"
    await session.flush()


async def current_application_research(
    session: AsyncSession, application: Application, *, now: datetime | None = None
) -> ApplicationResearchSnapshot | None:
    """What to show for this application, in order of what matters (T093's rule).

    A run in flight comes first — but only while it is plausibly in flight; an
    abandoned row falls through. Then the newest success; a failed row is
    reachable only when nothing ever succeeded.
    """
    in_flight = await session.scalar(
        select(ApplicationResearchSnapshot)
        .where(
            ApplicationResearchSnapshot.application_id == application.id,
            ApplicationResearchSnapshot.status == ResearchStatus.RUNNING,
        )
        .order_by(ApplicationResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    if in_flight is not None and not is_abandoned(in_flight, now=now):
        return in_flight

    latest = await session.scalar(
        select(ApplicationResearchSnapshot)
        .where(
            ApplicationResearchSnapshot.application_id == application.id,
            ApplicationResearchSnapshot.status == ResearchStatus.SUCCEEDED,
        )
        .order_by(ApplicationResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    if latest is not None:
        return latest

    # Terminal rows only (review fix): the sole way a RUNNING row reaches this
    # leg is by being abandoned, and serving it as live would pin the tab on
    # "Researching…" with the recovering POST disabled. An abandoned-only
    # history reads as nothing, so the start button comes back and the next
    # request replaces the stuck row.
    terminal: ApplicationResearchSnapshot | None = await session.scalar(
        select(ApplicationResearchSnapshot)
        .where(
            ApplicationResearchSnapshot.application_id == application.id,
            ApplicationResearchSnapshot.status != ResearchStatus.RUNNING,
        )
        .order_by(ApplicationResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    return terminal


# -- legacy company research (008-era, read-only) ----------------------------


async def current_company_research(
    session: AsyncSession, company: Company, *, now: datetime | None = None
) -> CompanyResearchSnapshot | None:
    """The 008-era snapshot to show **when no application snapshot exists**.

    Read-only since slice 010: no new rows are written to
    `company_research_snapshots`, so the in-flight leg of the old T093 ordering
    is gone — nothing can be in flight there any more. The pointer, then the
    newest row, unchanged, so history keeps rendering exactly as it did
    (FR-014).
    """
    del now  # kept for signature symmetry with the application read path
    if company.current_research_snapshot_id is not None:
        pointed: CompanyResearchSnapshot | None = await session.get(
            CompanyResearchSnapshot, company.current_research_snapshot_id
        )
        if pointed is not None and pointed.status == ResearchStatus.SUCCEEDED:
            return pointed

    # SUCCEEDED only (review fix): with the legacy write path gone, a pre-010
    # row stuck at 'running' can never be finished or failed — serving it as
    # live would freeze the tab forever with recovery disabled, and a legacy
    # failure has nothing left to retry. History means finished history.
    newest: CompanyResearchSnapshot | None = await session.scalar(
        select(CompanyResearchSnapshot)
        .where(
            CompanyResearchSnapshot.company_id == company.id,
            CompanyResearchSnapshot.status == ResearchStatus.SUCCEEDED,
        )
        .order_by(CompanyResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    return newest


def source_rows_for(
    snapshot: ApplicationResearchSnapshot | CompanyResearchSnapshot,
) -> list[ResearchSource]:
    """The snapshot's sources, ordered stably for display."""
    return sorted(snapshot.sources, key=lambda source: source.source_id)


__all__ = [
    "ConcurrentResearchRun",
    "complete_application_research",
    "create_pending_application_research",
    "current_application_research",
    "current_company_research",
    "fail_research",
    "is_abandoned",
    "reusable_application_research",
    "source_rows_for",
]
