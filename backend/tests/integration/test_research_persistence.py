"""Application-research persistence: what PostgreSQL enforces and what the
write path guarantees (slice 010, T011).

`tests/unit/test_application_research_model.py` asserts what the models
*declare*; this file asserts what the database *refuses* and what the
persistence functions *do*. Constraint tests write rows that must fail —
a test that only writes valid rows proves nothing about a constraint — and
each refusal happens in its own transaction, because a failed statement
poisons the enclosing one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.ports import ProviderSource, ResearchOutcome, Usage
from careerhq.application.provision_user import provision_user
from careerhq.application.research_persistence import (
    ConcurrentResearchRun,
    complete_application_research,
    create_pending_application_research,
    current_application_research,
    fail_research,
    reusable_application_research,
)
from careerhq.domain.models import (
    Application,
    ApplicationResearchSnapshot,
    Company,
    NormalizedStatus,
    ResearchSource,
    ResearchStatus,
    normalize_company_name,
)
from careerhq.domain.schemas.research import ApplicationResearch

pytestmark = pytest.mark.asyncio


def _research() -> ApplicationResearch:
    return ApplicationResearch.model_validate(
        {
            "company_identification": {
                "official_name": "Pango",
                "website": "https://pango.co.il",
                "how_identified": "posting location and domain",
            },
            "company_overview": "o",
            "products_and_services": "p",
            "business_and_market": "b",
            "relevant_to_your_role": "r",
            "what_to_know_before_the_interview": ["k"],
            "questions_worth_asking": ["q"],
        }
    )


def _estimate_outcome() -> ResearchOutcome:
    return ResearchOutcome(
        research=_research(),
        sources=(
            ProviderSource(source_id="s1", url="https://pango.co.il", title="Pango"),
            ProviderSource(source_id="f1", url="https://dead.example", fetch_status="failed"),
        ),
        produced_by="provider:tavily-research",
        prompt_version="app-v1",
        cost_estimate=Decimal("0.456"),
        run_facts={"posting_truncated": True, "posting_chars_sent": 20000},
    )


def _recorded_outcome() -> ResearchOutcome:
    return ResearchOutcome(
        research=_research(),
        sources=(),
        produced_by="provider:tavily-research",
        prompt_version="app-v1",
        usage=Usage(model="m", input_tokens=10, output_tokens=5, cost=Decimal("0.02")),
    )


async def _seed_application(session: AsyncSession, *, sub: str) -> Application:
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Persistence"}
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
        status="Wishlist",
        normalized_status=NormalizedStatus.WISHLIST,
    )
    session.add(application)
    await session.flush()
    return application


async def _backdate(
    session: AsyncSession, snapshot_id: uuid.UUID, *, days: int = 0, seconds: int = 0
) -> None:
    await session.execute(
        text(
            "UPDATE application_research_snapshots SET retrieved_at = "
            "now() - make_interval(days => :days, secs => :seconds) WHERE id = :id"
        ),
        {"days": days, "seconds": seconds, "id": snapshot_id},
    )


# -- constraints, proved by refusal ------------------------------------------


async def test_a_source_owned_by_neither_snapshot_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_application(session, sub="prs-neither")
        session.add(
            ResearchSource(source_id="s1", url="https://x.example", fetch_status="retrieved")
        )
        with pytest.raises(IntegrityError, match="ck_research_sources_exactly_one_snapshot"):
            await session.flush()


async def test_an_unknown_cost_basis_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-basis")
        session.add(
            ApplicationResearchSnapshot(
                user_id=application.user_id,
                application_id=application.id,
                sections={},
                produced_by="provider:tavily-research",
                cost_basis="vibes",
                status=ResearchStatus.RUNNING,
            )
        )
        with pytest.raises(IntegrityError, match="ck_application_research_snapshots_cost_basis"):
            await session.flush()


# -- the concurrency guard ---------------------------------------------------


async def test_a_second_pending_run_is_refused_as_concurrent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-conflict")
        await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        with pytest.raises(ConcurrentResearchRun):
            await create_pending_application_research(
                session, application, produced_by="provider:tavily-research"
            )


async def test_an_abandoned_run_is_replaced_not_defended(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-016: a `running` row past the duration bound stops blocking new runs.
    The stuck row is marked failed by the new request — never left needing
    hand-written SQL, which is the slice 005 lesson three times over."""
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-abandon")
        stuck = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await session.flush()
        await _backdate(session, stuck.id, seconds=901)

        replacement = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        assert replacement.id != stuck.id
        await session.refresh(stuck)
        assert stuck.status == ResearchStatus.FAILED
        assert stuck.failure_reason == "AbandonedRun"


async def test_an_abandoned_run_stops_being_reported_as_in_flight(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-016's read half: the reader treats the row as abandoned without
    rewriting it — the row stays `running` in storage, and simply stops being
    the answer."""
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-abandon-read")
        done = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await complete_application_research(session, done, outcome=_recorded_outcome())
        stuck = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await session.flush()
        await _backdate(session, stuck.id, seconds=901)
        session.expunge_all()

        application = (await session.scalars(select(Application))).one()
        current = await current_application_research(session, application)
        assert current is not None
        assert current.id == done.id, "an abandoned run must fall through to the success"
        stored = await session.get(ApplicationResearchSnapshot, stuck.id)
        assert stored is not None and stored.status == ResearchStatus.RUNNING, (
            "the reader must not rewrite the row"
        )


# -- completion and the cost basis -------------------------------------------


async def test_a_recorded_outcome_lands_with_exact_usage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-recorded")
        snapshot = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await complete_application_research(session, snapshot, outcome=_recorded_outcome())

        assert snapshot.status == ResearchStatus.SUCCEEDED
        assert snapshot.cost_basis == "recorded"
        assert snapshot.input_tokens == 10
        assert snapshot.cost == Decimal("0.02")


async def test_an_estimate_outcome_lands_marked_as_an_estimate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """D5: the basis is derived from which cost channel the outcome carried,
    and the adapter's run facts (truncation included, C4) land in
    `model_config_used`."""
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-estimate")
        snapshot = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await complete_application_research(session, snapshot, outcome=_estimate_outcome())

        assert snapshot.cost_basis == "estimate"
        assert snapshot.cost == Decimal("0.456")
        assert snapshot.input_tokens == 0
        assert snapshot.model_config_used is not None
        assert snapshot.model_config_used["posting_truncated"] is True
        assert snapshot.model_config_used["posting_chars_sent"] == 20000

        sources = (
            await session.scalars(
                select(ResearchSource).where(ResearchSource.application_snapshot_id == snapshot.id)
            )
        ).all()
        assert {s.source_id: s.fetch_status for s in sources} == {
            "s1": "retrieved",
            "f1": "failed",
        }
        assert all(s.excerpt is None for s in sources), "provider sources are attribution only"


async def test_a_failed_run_records_its_basis_never_zero_silently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SC-006 on the failure path: what was plausibly spent before the failure
    lands with its basis, so the run cannot read as free."""
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-fail")
        snapshot = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await fail_research(
            session, snapshot, "ResearchProviderRejected", cost_estimate=Decimal("0.456")
        )

        assert snapshot.status == ResearchStatus.FAILED
        assert snapshot.failure_reason == "ResearchProviderRejected"
        assert snapshot.cost == Decimal("0.456")
        assert snapshot.cost_basis == "estimate"


# -- the read path -----------------------------------------------------------


async def test_failure_never_evicts_the_last_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-evict")
        good = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await complete_application_research(session, good, outcome=_recorded_outcome())
        await _backdate(session, good.id, days=1)

        bad = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await fail_research(session, bad, "ResearchProviderUnavailable")

        current = await current_application_research(session, application)
        assert current is not None and current.id == good.id


async def test_a_failed_row_is_shown_only_when_nothing_ever_succeeded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-only-fail")
        bad = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await fail_research(session, bad, "ResearchProviderUnavailable")

        current = await current_application_research(session, application)
        assert current is not None and current.id == bad.id


# -- reuse -------------------------------------------------------------------


async def test_a_fresh_snapshot_is_reusable_and_an_old_one_is_not(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-reuse")
        snapshot = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await complete_application_research(session, snapshot, outcome=_recorded_outcome())

        assert await reusable_application_research(session, application) is not None

        await _backdate(session, snapshot.id, days=31)
        await session.refresh(snapshot)
        assert await reusable_application_research(session, application) is None


async def test_a_late_completion_cannot_resurrect_a_terminal_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Review fix: a background task finishing after its row was marked
    failed (AbandonedRun, or by any other session) must not flip the terminal
    state back to succeeded — the replacement run is already in flight, and a
    terminal transition is terminal (Principle IV)."""
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-late")
        snapshot = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await session.commit()

        # Another session marks the row failed — exactly what the abandoned-run
        # replacement does while the original task is still alive.
        async with session_factory() as other:
            stuck = await other.get(ApplicationResearchSnapshot, snapshot.id)
            assert stuck is not None
            await fail_research(other, stuck, "AbandonedRun")
            await other.commit()

        # The original task, holding its stale ORM copy, tries to complete.
        await complete_application_research(session, snapshot, outcome=_recorded_outcome())
        await session.commit()

    async with session_factory() as check:
        stored = await check.get(ApplicationResearchSnapshot, snapshot.id)
        assert stored is not None
        assert stored.status == ResearchStatus.FAILED, "a terminal row was resurrected"
        assert stored.sections == {}, "the late result must not be persisted onto it"


async def test_a_late_failure_cannot_overwrite_a_terminal_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-late-fail")
        snapshot = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await complete_application_research(session, snapshot, outcome=_recorded_outcome())
        await session.commit()

        async with session_factory() as other:
            done = await other.get(ApplicationResearchSnapshot, snapshot.id)
            assert done is not None
            await fail_research(other, done, "TooLate")
            await other.commit()

    async with session_factory() as check:
        stored = await check.get(ApplicationResearchSnapshot, snapshot.id)
        assert stored is not None
        assert stored.status == ResearchStatus.SUCCEEDED


async def test_an_abandoned_only_history_reads_as_nothing_so_recovery_is_reachable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Review fix: a first-ever run that died uncommitted must not be served as
    'running' forever — the read path answers None, the tab offers the start
    button, and the next POST replaces the stuck row."""
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-abandoned-only")
        stuck = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await session.flush()
        await _backdate(session, stuck.id, seconds=901)
        session.expunge_all()

        application = (await session.scalars(select(Application))).one()
        assert await current_application_research(session, application) is None


async def test_an_abandoned_provider_run_is_failed_with_its_estimated_bill(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Review fix: a run nothing will finish still plausibly billed — the
    replacement stamps the stuck row with the caller-supplied estimate rather
    than leaving a $0 row that reads as free."""
    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-abandon-bill")
        stuck = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await session.flush()
        await _backdate(session, stuck.id, seconds=901)

        await create_pending_application_research(
            session,
            application,
            produced_by="provider:tavily-research",
            abandoned_cost_estimate=Decimal("0.456"),
        )
        await session.refresh(stuck)
        assert stuck.status == ResearchStatus.FAILED
        assert stuck.cost == Decimal("0.456")
        assert stuck.cost_basis == "estimate"


async def test_reuse_is_refused_when_the_posting_context_changed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Review fix (US2 acceptance 2): a snapshot is reusable only for the
    context it was produced from. A missing stored fingerprint is a mismatch —
    never a free pass."""
    from careerhq.application.research_application import context_fingerprint

    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-fingerprint")
        snapshot = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        old_print = context_fingerprint(role_title=None, posting_text=None)
        await complete_application_research(
            session, snapshot, outcome=_recorded_outcome(), context_fingerprint=old_print
        )

        assert (
            await reusable_application_research(session, application, context_fingerprint=old_print)
            is not None
        ), "unchanged context reuses"

        new_print = context_fingerprint(
            role_title="Senior Backend", posting_text="Join the Parking Domain."
        )
        assert (
            await reusable_application_research(session, application, context_fingerprint=new_print)
            is None
        ), "a changed posting context must re-run"


async def test_a_snapshot_without_a_stored_fingerprint_is_not_reused_against_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from careerhq.application.research_application import context_fingerprint

    async with session_factory() as session:
        application = await _seed_application(session, sub="prs-nofingerprint")
        snapshot = await create_pending_application_research(
            session, application, produced_by="provider:tavily-research"
        )
        await complete_application_research(session, snapshot, outcome=_recorded_outcome())

        current = context_fingerprint(role_title=None, posting_text=None)
        assert (
            await reusable_application_research(session, application, context_fingerprint=current)
            is None
        )
