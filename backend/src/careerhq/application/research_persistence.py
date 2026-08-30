"""Writing research to the database — one write path, shared by both layers.

**No repository abstraction, deliberately.** This codebase has none: every use
case in slices 003, 004 and 005 takes an `AsyncSession` and writes through the
ORM. Introducing a `Repository` for this slice alone would put slice 008 behind
an interface nothing else uses, which is the asymmetry the shared write path
exists to prevent, not a cure for it. What is shared here is *mechanics* —
`_write_sources`, `_record_usage`, `_fail` — so neither layer invents its own.

**The pure use cases stay pure.** `research_company()` and `research_role()` take
doubles, return a result and touch no session. This module wraps them. That
separation is what keeps the whole pipeline testable with no database and no
provider, and it is why the doubles-based tests did not have to change.

**Two phases, because a status change is not observable until it commits.** A
`pending` row is created and committed first, then the work runs, then the result
is written. Slice 005 skipped this and its concern #6 is the consequence: the
interface showed "Writing" for an entire run because the only commit was at the
end, so `REVIEWING` was never visible to another session.

**The pointer is written last and only on success** (FR-014), copying
`analyze_match.py:420` including its T093 correction. A failed re-run must leave
the previous research standing rather than blanking it.

**Layer 2 never triggers Layer 1** (FR-001). `prepare_role_research` refuses with
a typed reason when no company research exists; it does not quietly escalate a
warm run into a cold one the user did not ask for.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.ports import FetchedSource, Usage
from careerhq.application.research_company import COMPANY_PROMPT_VERSION
from careerhq.application.research_role import ROLE_PROMPT_VERSION
from careerhq.application.research_windows import is_reusable
from careerhq.config import get_settings
from careerhq.domain.models import (
    Application,
    Company,
    CompanyResearchSnapshot,
    FetchStatus,
    ResearchSource,
    ResearchStatus,
    RoleResearchSnapshot,
)
from careerhq.domain.schemas.research import Claim, CompanyResearch, RoleResearch


class ConcurrentResearchRun(RuntimeError):
    """A run for this company or application is already in flight.

    **Raised from the database's refusal, not from a prior read.** A
    read-then-write check cannot be made safe here: two requests are two
    transactions, and the window between the check and the insert is exactly
    where a double-click lands. The partial unique indexes in `0019` are the
    guard; this type is how the refusal reaches a caller.

    A distinct type because "one is already running" is an ordinary state a route
    should answer as such — not a 500, and not a reason to start a second paid
    run. Slice 005's lesson applies to whatever answers it: a guard that refuses
    the one action which would recover a stuck run needs hand-written SQL to
    clear, so the caller must let an *abandoned* run be replaced.
    """


class NoCompanyResearch(RuntimeError):
    """Layer 2 was asked for, and no Layer 1 exists to build it on.

    **A refusal, not a trigger.** FR-001 keeps research on explicit request, so
    the answer is to tell the caller to run Layer 1 rather than to run it for
    them — which would also turn a ~$0.05 warm run into a ~$0.15 cold one the
    user never asked for.

    A distinct type so a route can answer it as "nothing to build on yet", which
    is an ordinary state and not an error.
    """


def _is_running_conflict(exc: IntegrityError, index_name: str) -> bool:
    """Whether this violation is the in-flight guard rather than another one.

    Matched by index name so an unrelated constraint — the one-of-two source
    ownership check, a foreign key — is re-raised rather than reported as a
    concurrent run. Answering every `IntegrityError` with "already running" would
    turn a genuine bug into a message telling the user to wait for a run that
    does not exist.
    """
    return index_name in str(getattr(exc, "orig", exc))


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def is_abandoned(
    snapshot: CompanyResearchSnapshot | RoleResearchSnapshot, *, now: datetime | None = None
) -> bool:
    """Whether a `running` row has outlived any run that could finish it.

    **Bounded by `research_max_duration_seconds`**, which is FR-004's second half
    — a run is bounded by a maximum duration as well as a maximum number of
    sources, and both are configured constants rather than prompt instructions.
    The same number governs both because a run past its own bound is exactly a
    run nothing will finish; two constants would eventually disagree and either
    reap a live run or block a retry forever.

    Only `running` rows can be abandoned; a finished row is simply finished.
    """
    if snapshot.status != ResearchStatus.RUNNING:
        return False
    moment = now or datetime.now(UTC)
    limit = get_settings().research_max_duration_seconds
    return (moment - _aware(snapshot.retrieved_at)).total_seconds() > limit


# -- shared write mechanics --------------------------------------------------


def _claims(research: CompanyResearch | RoleResearch) -> Iterable[Claim]:
    """Every claim in a brief, whichever layer it came from.

    The two layers differ only in traversal — Layer 1 has five named sections,
    Layer 2 a list whose length the model chose — so flattening here is what lets
    everything below be written once.
    """
    if isinstance(research, CompanyResearch):
        for name in CompanyResearch.model_fields:
            yield from getattr(research, name).claims
        return
    for finding in research.findings:
        yield from finding.claims
    yield from research.interview_preparation.claims


def _excerpts_by_source(research: CompanyResearch | RoleResearch) -> dict[str, str]:
    """The first surviving excerpt citing each source.

    First rather than all: the per-claim excerpts are already stored in full
    inside the brief's own JSONB, so this is the source row's representative
    passage, not the record of the evidence. Duplicating every excerpt here would
    give slice 007 two copies to disagree with each other.

    Only *surviving* claims are walked, because a claim rejected by the verbatim
    check has been removed by then — so a rejected excerpt can never become a
    source row's evidence.
    """
    found: dict[str, str] = {}
    for claim in _claims(research):
        for evidence in claim.evidence:
            found.setdefault(evidence.source_id, evidence.excerpt)
    return found


def _write_sources(
    session: AsyncSession,
    *,
    company_snapshot_id: uuid.UUID | None = None,
    role_snapshot_id: uuid.UUID | None = None,
    research: CompanyResearch | RoleResearch,
    sources: tuple[FetchedSource, ...],
    failed_urls: tuple[str, ...],
) -> int:
    """Record what was consulted. Returns how many rows were written.

    **A source that could not be retrieved is still a row** (FR-009). An absent
    row cannot be told apart from a source nobody tried, and "three of eight
    refused" is a fact about the research rather than an implementation detail.

    **A retrieved source that no surviving claim cites is also still a row**, with
    a NULL excerpt. That is the ordinary case, not an anomaly: a run reads several
    pages and the model draws on some of them. Recording only the cited ones would
    understate how much of the web was consulted, and would make a thin brief
    built on eight pages indistinguishable from one built on three — which is
    exactly the judgement a reader needs. `0019` briefly forbade this row via
    `ck_research_sources_retrieved_has_excerpt`; the constraint was removed before
    the migration shipped, because it made a legitimate state unwritable.
    """
    excerpts = _excerpts_by_source(research)
    written = 0

    for source in sources:
        session.add(
            ResearchSource(
                company_snapshot_id=company_snapshot_id,
                role_snapshot_id=role_snapshot_id,
                source_id=source.source_id,
                url=source.url,
                title=source.title,
                #: NULL where nothing surviving cites it — see the docstring.
                excerpt=excerpts.get(source.source_id),
                fetch_status=FetchStatus.RETRIEVED,
            )
        )
        written += 1

    for index, url in enumerate(failed_urls):
        session.add(
            ResearchSource(
                company_snapshot_id=company_snapshot_id,
                role_snapshot_id=role_snapshot_id,
                #: Namespaced so a failed source cannot collide with a retrieved
                #: one on the per-snapshot unique index.
                source_id=f"f{index + 1}",
                url=url,
                title=None,
                excerpt=None,
                fetch_status=FetchStatus.FAILED,
            )
        )
        written += 1

    return written


def _record_usage(
    snapshot: CompanyResearchSnapshot | RoleResearchSnapshot, usages: tuple[Usage, ...]
) -> None:
    """Principle V, written in the same transaction as the work it paid for.

    Totals are stored because that is what `0019` has room for; the per-call
    breakdown lives in `Layer2Result.usages` and is deliberately not flattened
    before it reaches here, so a future column can capture it without changing
    any caller.
    """
    snapshot.input_tokens = sum(usage.input_tokens for usage in usages)
    snapshot.output_tokens = sum(usage.output_tokens for usage in usages)
    snapshot.cost = sum((usage.cost for usage in usages), start=snapshot.cost.__class__(0))
    snapshot.model_config_used = {
        "models": [usage.model for usage in usages],
        "calls": len(usages),
    }


async def fail_research(
    session: AsyncSession,
    snapshot: CompanyResearchSnapshot | RoleResearchSnapshot,
    reason: str,
) -> None:
    """A failed run is a recorded run, not an absent one.

    Slice 005 lost $0.506821 to three runs that recorded nothing and therefore
    reported `$0` — which reads as free when the calls had already been billed.
    The pointer is deliberately **not** touched here: FR-014's guarantee is that a
    failure leaves the previous research standing.
    """
    snapshot.status = ResearchStatus.FAILED
    snapshot.failure_reason = reason
    await session.flush()


# -- Layer 1 -----------------------------------------------------------------


async def reusable_company_research(
    session: AsyncSession, company: Company, *, now: datetime | None = None
) -> CompanyResearchSnapshot | None:
    """The Layer 1 snapshot fresh enough to skip a re-run, or `None`.

    **Reads the FR-014 pointer**, which only ever names a succeeded row — that is
    what the pointer is for, and it is why this needs no ordering query. T093's
    in-flight-first rule does *not* apply here: this is a spend decision, and a
    run still in flight is not something to reuse.
    """
    if company.current_research_snapshot_id is None:
        return None
    snapshot = await session.get(CompanyResearchSnapshot, company.current_research_snapshot_id)
    if snapshot is None or snapshot.status != ResearchStatus.SUCCEEDED:
        return None
    return snapshot if is_reusable(snapshot.retrieved_at, now=now) else None


async def current_company_research(
    session: AsyncSession, company: Company, *, now: datetime | None = None
) -> CompanyResearchSnapshot | None:
    """What to show for this company, in order of what matters (T093).

    **A run in flight comes first** — but only while it is plausibly in flight.
    Preferring the pointer unconditionally meant slice 004's interface reported
    the previous result for the whole duration of a re-run, and since the previous
    result is never `running`, polling stopped on the first poll and the real
    result arrived unobserved.

    **An abandoned row falls through to the pointer**, or a run nobody will finish
    replaces good research with a failure — the same guarantee lost by the other
    route.
    """
    in_flight = await session.scalar(
        select(CompanyResearchSnapshot)
        .where(
            CompanyResearchSnapshot.company_id == company.id,
            CompanyResearchSnapshot.status == ResearchStatus.RUNNING,
        )
        .order_by(CompanyResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    if in_flight is not None and not is_abandoned(in_flight, now=now):
        return in_flight

    if company.current_research_snapshot_id is not None:
        pointed: CompanyResearchSnapshot | None = await session.get(
            CompanyResearchSnapshot, company.current_research_snapshot_id
        )
        if pointed is not None:
            return pointed

    latest: CompanyResearchSnapshot | None = await session.scalar(
        select(CompanyResearchSnapshot)
        .where(CompanyResearchSnapshot.company_id == company.id)
        .order_by(CompanyResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    return latest


async def create_pending_company_research(
    session: AsyncSession, company: Company
) -> CompanyResearchSnapshot:
    """Reserve a row for a Layer 1 run. Committing it is the caller's job.

    Creating unconditionally: whether to reuse instead is
    `reusable_company_research`, and keeping the two apart means the spend
    decision is visible at the call site rather than buried in a constructor.

    Raises `ConcurrentResearchRun` when one is already in flight for this
    company. The refusal comes from the database's partial unique index, not from
    a prior read, because a read-then-write check loses to a double-click.
    """
    snapshot = CompanyResearchSnapshot(
        user_id=company.user_id,
        company_id=company.id,
        sections={},
        status=ResearchStatus.RUNNING,
        prompt_version=COMPANY_PROMPT_VERSION,
    )
    session.add(snapshot)
    try:
        await session.flush()
    except IntegrityError as exc:
        if _is_running_conflict(exc, "uq_company_research_one_running_per_company"):
            raise ConcurrentResearchRun(
                "company research is already running for this employer"
            ) from exc
        raise
    return snapshot


async def complete_company_research(
    session: AsyncSession,
    snapshot: CompanyResearchSnapshot,
    *,
    research: CompanyResearch,
    sources: tuple[FetchedSource, ...],
    failed_urls: tuple[str, ...],
    usages: tuple[Usage, ...],
) -> None:
    """Write a finished Layer 1 run, then move the pointer — in that order."""
    snapshot.sections = research.model_dump(mode="json")
    snapshot.status = ResearchStatus.SUCCEEDED
    _record_usage(snapshot, usages)
    _write_sources(
        session,
        company_snapshot_id=snapshot.id,
        research=research,
        sources=sources,
        failed_urls=failed_urls,
    )

    # Last, and only now: a failed run must leave the previous research standing.
    company = await session.get(Company, snapshot.company_id)
    if company is not None:
        company.current_research_snapshot_id = snapshot.id
    await session.flush()


# -- Layer 2 -----------------------------------------------------------------


async def prepare_role_research(
    session: AsyncSession, application: Application
) -> CompanyResearchSnapshot:
    """The Layer 1 snapshot a Layer 2 run will rest on, or a refusal.

    **Never triggers Layer 1** (FR-001). Raises `NoCompanyResearch` so the caller
    can offer to run it.

    **Deliberately does not apply the reuse window.** The 30-day window governs
    Layer 1's own spend decision, not Layer 2's right to build on what already
    exists — refusing a 31-day-old Layer 1 here would force a cold run nobody
    asked for, which is FR-001 broken by the back door. The age travels with the
    lineage instead, and the staleness label carries the warning (FR-033).
    """
    company = await session.get(Company, application.company_id)
    if company is None or company.current_research_snapshot_id is None:
        raise NoCompanyResearch(
            "no company research exists for this employer yet; run Layer 1 first"
        )
    snapshot = await session.get(CompanyResearchSnapshot, company.current_research_snapshot_id)
    if snapshot is None or snapshot.status != ResearchStatus.SUCCEEDED:
        raise NoCompanyResearch(
            "the company research for this employer did not complete; run Layer 1 again"
        )
    return snapshot


async def create_pending_role_research(
    session: AsyncSession, application: Application, company_snapshot: CompanyResearchSnapshot
) -> RoleResearchSnapshot:
    """Reserve a row for a Layer 2 run, with its lineage already recorded.

    The lineage is set at creation rather than at completion because FR-023 is
    what makes the row interpretable at all — a `running` Layer 2 row that could
    not say what it rests on would be unreadable exactly while someone is
    watching it.
    """
    snapshot = RoleResearchSnapshot(
        user_id=application.user_id,
        application_id=application.id,
        company_research_snapshot_id=company_snapshot.id,
        findings=[],
        status=ResearchStatus.RUNNING,
        prompt_version=ROLE_PROMPT_VERSION,
    )
    session.add(snapshot)
    try:
        await session.flush()
    except IntegrityError as exc:
        if _is_running_conflict(exc, "uq_role_research_one_running_per_application"):
            raise ConcurrentResearchRun(
                "role research is already running for this application"
            ) from exc
        raise
    return snapshot


async def complete_role_research(
    session: AsyncSession,
    snapshot: RoleResearchSnapshot,
    *,
    research: RoleResearch,
    sources: tuple[FetchedSource, ...],
    failed_urls: tuple[str, ...],
    usages: tuple[Usage, ...],
) -> None:
    """Write a finished Layer 2 run.

    **No pointer.** FR-014's pointer is a company-level fact; Layer 2 is found by
    its application, so a second pointer would be a second thing to keep correct
    for no read it enables.
    """
    dumped = research.model_dump(mode="json")
    snapshot.findings = dumped["findings"]
    snapshot.status = ResearchStatus.SUCCEEDED
    _record_usage(snapshot, usages)
    _write_sources(
        session,
        role_snapshot_id=snapshot.id,
        research=research,
        sources=sources,
        failed_urls=failed_urls,
    )
    await session.flush()


async def current_role_research(
    session: AsyncSession, application: Application, *, now: datetime | None = None
) -> RoleResearchSnapshot | None:
    """What to show for this application. The same T093 ordering as Layer 1."""
    in_flight = await session.scalar(
        select(RoleResearchSnapshot)
        .where(
            RoleResearchSnapshot.application_id == application.id,
            RoleResearchSnapshot.status == ResearchStatus.RUNNING,
        )
        .order_by(RoleResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    if in_flight is not None and not is_abandoned(in_flight, now=now):
        return in_flight

    latest: RoleResearchSnapshot | None = await session.scalar(
        select(RoleResearchSnapshot)
        .where(
            RoleResearchSnapshot.application_id == application.id,
            RoleResearchSnapshot.status == ResearchStatus.SUCCEEDED,
        )
        .order_by(RoleResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    if latest is not None:
        return latest

    any_row: RoleResearchSnapshot | None = await session.scalar(
        select(RoleResearchSnapshot)
        .where(RoleResearchSnapshot.application_id == application.id)
        .order_by(RoleResearchSnapshot.retrieved_at.desc())
        .limit(1)
    )
    return any_row


__all__ = [
    "ConcurrentResearchRun",
    "NoCompanyResearch",
    "complete_company_research",
    "complete_role_research",
    "create_pending_company_research",
    "create_pending_role_research",
    "current_company_research",
    "current_role_research",
    "fail_research",
    "is_abandoned",
    "prepare_role_research",
    "reusable_company_research",
]
