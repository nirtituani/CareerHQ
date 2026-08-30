"""Step 5 — persistence, reuse, staleness and the pointer, against a real database.

The rules under test are the ones this project has already paid to learn:

* **The pointer moves only on success** (FR-014). A failed re-run must leave the
  previous research standing rather than blanking it.
* **T093's read order**: an in-flight run comes first, but only while it is
  plausibly in flight — an abandoned row must fall through to the pointer, or a
  run nobody will finish replaces good research with a failure.
* **Layer 2 never triggers Layer 1** (FR-001).
* **Reuse and staleness are different windows** (OQ-E) read at different times.

Every write is checked from a **fresh session**, because a row read back through
the session that wrote it returns what that session set rather than what the
database holds — the identity-map trap this project has hit twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.ports import FetchedSource, Usage
from careerhq.application.provision_user import provision_user
from careerhq.application.research_company import COMPANY_PROMPT_VERSION
from careerhq.application.research_persistence import (
    ConcurrentResearchRun,
    NoCompanyResearch,
    complete_company_research,
    complete_role_research,
    create_pending_company_research,
    create_pending_role_research,
    current_company_research,
    current_role_research,
    fail_research,
    prepare_role_research,
    reusable_company_research,
)
from careerhq.application.research_role import ROLE_PROMPT_VERSION
from careerhq.application.research_windows import RESEARCH_REUSE_DAYS
from careerhq.config import get_settings
from careerhq.domain.models import (
    Application,
    Company,
    CompanyResearchSnapshot,
    NormalizedStatus,
    ResearchSource,
    ResearchStatus,
    RoleResearchSnapshot,
    normalize_company_name,
)
from careerhq.domain.schemas.research import (
    Claim,
    CompanyResearch,
    Evidence,
    ResearchSection,
    RoleFinding,
    RoleResearch,
)

pytestmark = pytest.mark.asyncio

PAGE = "Acme processes payments for European retailers."


def _max_duration() -> int:
    """FR-004's configured duration bound, read rather than hardcoded.

    Read through `get_settings()` so a test ages a row past whatever the
    configuration actually says. Hardcoding 900 here would keep passing if the
    application stopped consulting the setting at all.
    """
    return get_settings().research_max_duration_seconds


def _usage(cost: str = "0.01") -> Usage:
    from decimal import Decimal

    return Usage(
        model="anthropic/claude-sonnet-5", input_tokens=1000, output_tokens=400, cost=Decimal(cost)
    )


def _company_research(*, cited: bool = True) -> CompanyResearch:
    empty = ResearchSection(claims=[], empty_reason="Not covered.")
    claims = (
        [
            Claim(
                id="c1",
                text="Acme processes payments for European retailers.",
                tier="fact",
                evidence=[Evidence(source_id="s1", excerpt="payments for European retailers")],
            )
        ]
        if cited
        else []
    )
    first = (
        ResearchSection(claims=claims)
        if cited
        else ResearchSection(claims=[], empty_reason="Nothing usable found.")
    )
    return CompanyResearch(
        what_the_company_does=first,
        products_and_services=empty,
        market_and_customers=empty,
        practical_facts=empty,
        interview_preparation=empty,
    )


def _role_research() -> RoleResearch:
    return RoleResearch(
        findings=[
            RoleFinding(
                heading="Architecture",
                claims=[
                    Claim(
                        id="r1",
                        text="They run a service per team.",
                        tier="fact",
                        evidence=[Evidence(source_id="s1", excerpt="payments for European")],
                    )
                ],
            )
        ],
        interview_preparation=ResearchSection(claims=[], empty_reason="Nothing public."),
    )


def _sources() -> tuple[FetchedSource, ...]:
    return (FetchedSource(url="https://acme.example/a", title="A", text=PAGE, source_id="s1"),)


async def _seed(session: AsyncSession, *, sub: str) -> tuple[Company, Application]:
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Reuse Test"}
    )
    company = Company(user_id=user.id, name="Acme", normalized_name=normalize_company_name("Acme"))
    session.add(company)
    await session.flush()
    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Senior Backend Engineer",
        status="Wishlist",
        normalized_status=NormalizedStatus.WISHLIST,
    )
    session.add(application)
    await session.flush()
    return company, application


async def _succeeded(session: AsyncSession, company: Company) -> CompanyResearchSnapshot:
    snapshot = await create_pending_company_research(session, company)
    await complete_company_research(
        session,
        snapshot,
        research=_company_research(),
        sources=_sources(),
        failed_urls=(),
        usages=(_usage(),),
    )
    return snapshot


# -- FR-014: the pointer moves only on success ------------------------------


async def test_a_successful_run_moves_the_pointer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-ok")
        snapshot = await _succeeded(session, company)
        await session.commit()
        snapshot_id, company_id = snapshot.id, company.id

    async with session_factory() as session:
        stored = await session.get(Company, company_id)
        assert stored is not None
        assert stored.current_research_snapshot_id == snapshot_id


async def test_a_pending_run_does_not_move_the_pointer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The two-phase pattern's whole point: the row exists and is visible while
    running, without yet claiming to be the current research."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-pending")
        await create_pending_company_research(session, company)
        await session.commit()
        company_id = company.id

    async with session_factory() as session:
        stored = await session.get(Company, company_id)
        assert stored is not None and stored.current_research_snapshot_id is None


async def test_a_failed_rerun_leaves_the_previous_research_standing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-014, and the failure it exists to prevent: pressing the button again
    must not be able to destroy what you already had."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-failrerun")
        good = await _succeeded(session, company)
        await session.commit()
        good_id, company_id = good.id, company.id

    async with session_factory() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        second = await create_pending_company_research(session, company)
        await fail_research(session, second, "the provider was overloaded")
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(Company, company_id)
        assert stored is not None
        assert stored.current_research_snapshot_id == good_id, (
            "a failed re-run blanked or moved the pointer; the previous research must stand"
        )


async def test_a_failed_run_is_a_recorded_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Slice 005 lost $0.506821 to runs that recorded nothing and reported $0."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-failrec")
        snapshot = await create_pending_company_research(session, company)
        await fail_research(session, snapshot, "overloaded")
        await session.commit()
        snapshot_id = snapshot.id

    async with session_factory() as session:
        stored = await session.get(CompanyResearchSnapshot, snapshot_id)
        assert stored is not None
        assert stored.status == ResearchStatus.FAILED
        assert stored.failure_reason == "overloaded"


# -- reuse: the spend decision ----------------------------------------------


async def test_recent_research_is_offered_for_reuse(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-recent")
        snapshot = await _succeeded(session, company)
        await session.commit()
        expected = snapshot.id

    async with session_factory() as session:
        company = await session.get(Company, company.id)
        assert company is not None
        reusable = await reusable_company_research(session, company)
        assert reusable is not None and reusable.id == expected


async def test_research_past_the_reuse_window_is_not_offered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Aged by moving the row's timestamp, not by mocking the clock, so the
    query and the window are exercised together."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-old")
        snapshot = await _succeeded(session, company)
        await session.commit()
        snapshot_id, company_id = snapshot.id, company.id

    async with session_factory() as session:
        await session.execute(
            text("UPDATE company_research_snapshots SET retrieved_at = :t WHERE id = :id"),
            {"t": datetime.now(UTC) - timedelta(days=RESEARCH_REUSE_DAYS + 5), "id": snapshot_id},
        )
        await session.commit()

    async with session_factory() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        assert await reusable_company_research(session, company) is None


async def test_a_company_never_researched_offers_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-never")
        await session.commit()
        assert await reusable_company_research(session, company) is None


async def test_an_in_flight_run_is_never_reused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reuse is a spend decision; a run still in flight has nothing to reuse.
    T093's in-flight-first rule is a *display* rule and must not leak here."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-inflight")
        await create_pending_company_research(session, company)
        await session.commit()
        assert await reusable_company_research(session, company) is None


# -- T093: the display read path --------------------------------------------


async def test_an_in_flight_run_is_shown_before_the_pointer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The exact bug T093 fixed: preferring the pointer unconditionally made the
    interface report the previous result for the whole duration of a re-run, so
    polling stopped on the first poll and the real result arrived unobserved."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="t093-inflight")
        await _succeeded(session, company)
        running = await create_pending_company_research(session, company)
        await session.commit()
        running_id, company_id = running.id, company.id

    async with session_factory() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        current = await current_company_research(session, company)
        assert current is not None and current.id == running_id


async def test_an_abandoned_run_falls_through_to_the_pointer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The other half of T093, and the one that costs a good result: a run
    nobody will finish must not replace working research with a stuck one."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="t093-abandoned")
        good = await _succeeded(session, company)
        stuck = await create_pending_company_research(session, company)
        await session.commit()
        good_id, stuck_id, company_id = good.id, stuck.id, company.id

    async with session_factory() as session:
        await session.execute(
            text("UPDATE company_research_snapshots SET retrieved_at = :t WHERE id = :id"),
            {
                "t": datetime.now(UTC) - timedelta(seconds=_max_duration() + 60),
                "id": stuck_id,
            },
        )
        await session.commit()

    async with session_factory() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        current = await current_company_research(session, company)
        assert current is not None and current.id == good_id, (
            "an abandoned run hid a valid previous result"
        )


# -- FR-001: Layer 2 never triggers Layer 1 ---------------------------------


async def test_layer_two_refuses_when_no_company_research_exists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-001 keeps research on explicit request. Escalating here would turn a
    ~$0.05 warm run into a ~$0.15 cold one the user never asked for."""
    async with session_factory() as session:
        _company, application = await _seed(session, sub="layer2-none")
        await session.commit()
        with pytest.raises(NoCompanyResearch):
            await prepare_role_research(session, application)


async def test_layer_two_refuses_when_the_company_research_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, application = await _seed(session, sub="layer2-failed")
        snapshot = await create_pending_company_research(session, company)
        company.current_research_snapshot_id = snapshot.id
        await fail_research(session, snapshot, "overloaded")
        await session.commit()
        with pytest.raises(NoCompanyResearch):
            await prepare_role_research(session, application)


async def test_layer_two_creates_no_company_research_when_it_refuses(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The refusal must be a refusal, not a quiet cold run. Counted, because
    "it raised" and "it raised without spending" are different claims."""
    async with session_factory() as session:
        _company, application = await _seed(session, sub="layer2-nospend")
        await session.commit()
        with pytest.raises(NoCompanyResearch):
            await prepare_role_research(session, application)
        await session.rollback()

    async with session_factory() as session:
        count = await session.scalar(text("SELECT count(*) FROM company_research_snapshots"))
        assert count == 0, f"{count} company snapshot(s) were created by a Layer 2 refusal"


async def test_layer_two_builds_on_research_past_the_reuse_window(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The reuse window governs Layer 1's spend, not Layer 2's right to build on
    what exists. Refusing here would force a cold run nobody asked for — FR-001
    broken by the back door — so the age travels with the lineage instead."""
    async with session_factory() as session:
        company, application = await _seed(session, sub="layer2-old")
        snapshot = await _succeeded(session, company)
        await session.commit()
        snapshot_id = snapshot.id

    async with session_factory() as session:
        await session.execute(
            text("UPDATE company_research_snapshots SET retrieved_at = :t WHERE id = :id"),
            {"t": datetime.now(UTC) - timedelta(days=RESEARCH_REUSE_DAYS + 60), "id": snapshot_id},
        )
        await session.commit()

    async with session_factory() as session:
        application = await session.get(Application, application.id)
        assert application is not None
        rested_on = await prepare_role_research(session, application)
        assert rested_on.id == snapshot_id


# -- Layer 2 persistence and lineage ----------------------------------------


async def test_a_completed_layer_two_run_records_its_lineage_and_findings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, application = await _seed(session, sub="layer2-write")
        company_snapshot = await _succeeded(session, company)
        role = await create_pending_role_research(session, application, company_snapshot)
        await complete_role_research(
            session,
            role,
            research=_role_research(),
            sources=_sources(),
            failed_urls=(),
            usages=(_usage("0.02"), _usage("0.03")),
        )
        await session.commit()
        role_id, company_snapshot_id = role.id, company_snapshot.id

    async with session_factory() as session:
        stored = await session.get(type(role), role_id)
        assert stored is not None
        assert stored.company_research_snapshot_id == company_snapshot_id
        assert [f["heading"] for f in stored.findings] == ["Architecture"]
        assert stored.status == ResearchStatus.SUCCEEDED
        assert stored.cost == sum(u.cost for u in (_usage("0.02"), _usage("0.03")))


async def test_layer_two_does_not_move_the_company_pointer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The pointer is a company-level fact. A Layer 2 run must leave it alone."""
    async with session_factory() as session:
        company, application = await _seed(session, sub="layer2-nopointer")
        company_snapshot = await _succeeded(session, company)
        await session.commit()
        expected, company_id = company_snapshot.id, company.id

    async with session_factory() as session:
        application = await session.get(Application, application.id)
        company_snapshot = await session.get(CompanyResearchSnapshot, expected)
        assert application is not None and company_snapshot is not None
        role = await create_pending_role_research(session, application, company_snapshot)
        await complete_role_research(
            session,
            role,
            research=_role_research(),
            sources=_sources(),
            failed_urls=(),
            usages=(_usage(),),
        )
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(Company, company_id)
        assert stored is not None and stored.current_research_snapshot_id == expected


async def test_the_current_role_research_prefers_an_in_flight_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, application = await _seed(session, sub="layer2-current")
        company_snapshot = await _succeeded(session, company)
        done = await create_pending_role_research(session, application, company_snapshot)
        await complete_role_research(
            session,
            done,
            research=_role_research(),
            sources=_sources(),
            failed_urls=(),
            usages=(_usage(),),
        )
        running = await create_pending_role_research(session, application, company_snapshot)
        await session.commit()
        running_id, application_id = running.id, application.id

    async with session_factory() as session:
        application = await session.get(Application, application_id)
        assert application is not None
        current = await current_role_research(session, application)
        assert current is not None and current.id == running_id


# -- sources ------------------------------------------------------------------


async def test_a_cited_source_is_recorded_with_its_excerpt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, _ = await _seed(session, sub="src-cited")
        snapshot = await _succeeded(session, company)
        await session.commit()
        snapshot_id = snapshot.id

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(ResearchSource).where(ResearchSource.company_snapshot_id == snapshot_id)
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].excerpt == "payments for European retailers"
        assert rows[0].url == "https://acme.example/a"


async def test_a_failed_fetch_is_recorded_not_dropped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-009. An absent row cannot be told apart from a source nobody tried."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="src-failed")
        snapshot = await create_pending_company_research(session, company)
        await complete_company_research(
            session,
            snapshot,
            research=_company_research(),
            sources=_sources(),
            failed_urls=("https://acme.example/gone",),
            usages=(_usage(),),
        )
        await session.commit()
        snapshot_id = snapshot.id

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(ResearchSource).where(ResearchSource.company_snapshot_id == snapshot_id)
            )
        ).all()
        statuses = sorted(r.fetch_status for r in rows)
        assert statuses == ["failed", "retrieved"], statuses


async def test_a_retrieved_but_uncited_source_is_still_recorded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """How much of the web was consulted is part of what a brief claims.

    A run that reads a page and draws nothing from it still read the page, and a
    reader weighing a thin brief needs to know whether it rests on eight sources
    or three. Recording only cited sources would make those two runs identical.

    **This test previously asserted the opposite**, because
    `ck_research_sources_retrieved_has_excerpt` made the row unwritable. The
    constraint was removed from `0019` in place, before it shipped.
    """
    async with session_factory() as session:
        company, _ = await _seed(session, sub="src-uncited")
        snapshot = await create_pending_company_research(session, company)
        await complete_company_research(
            session,
            snapshot,
            research=_company_research(cited=False),
            sources=_sources(),
            failed_urls=(),
            usages=(_usage(),),
        )
        await session.commit()
        snapshot_id = snapshot.id

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(ResearchSource).where(ResearchSource.company_snapshot_id == snapshot_id)
            )
        ).all()
        assert len(rows) == 1, f"the uncited source was not recorded ({len(rows)} rows)"
        assert rows[0].fetch_status == "retrieved"
        assert rows[0].excerpt is None, (
            "an uncited source was given an excerpt; nothing cited it, so there is no "
            "passage to attribute and inventing one would fabricate evidence"
        )
        assert rows[0].url == "https://acme.example/a"


async def test_a_run_records_every_page_it_read_cited_or_not(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The consultation count, asserted as a count.

    Two pages fetched, one cited, one failed — three rows, because all three
    outcomes are facts about the research.
    """
    async with session_factory() as session:
        company, _ = await _seed(session, sub="src-count")
        snapshot = await create_pending_company_research(session, company)
        await complete_company_research(
            session,
            snapshot,
            research=_company_research(),
            sources=(
                FetchedSource(url="https://acme.example/a", title="A", text=PAGE, source_id="s1"),
                FetchedSource(
                    url="https://acme.example/b", title="B", text="Unrelated.", source_id="s2"
                ),
            ),
            failed_urls=("https://acme.example/gone",),
            usages=(_usage(),),
        )
        await session.commit()
        snapshot_id = snapshot.id

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(ResearchSource).where(ResearchSource.company_snapshot_id == snapshot_id)
            )
        ).all()
        assert len(rows) == 3, f"expected 3 consulted sources, recorded {len(rows)}"
        cited = [r for r in rows if r.excerpt is not None]
        assert len(cited) == 1 and cited[0].source_id == "s1"
        assert sorted(r.fetch_status for r in rows) == ["failed", "retrieved", "retrieved"]


async def test_a_pointer_at_a_non_succeeded_row_is_not_reused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The status guard in `reusable_company_research`, reached directly.

    `test_an_in_flight_run_is_never_reused` does NOT reach it: a pending run
    never sets the pointer, so that test returns `None` at the pointer check and
    the status check is never evaluated. A drill proved exactly that — removing
    the status guard left the whole suite green. This points the pointer at a
    non-succeeded row by hand, which is the only way the guard can fire, and
    without it the guard is decoration.
    """
    async with session_factory() as session:
        company, _ = await _seed(session, sub="reuse-badpointer")
        running = await create_pending_company_research(session, company)
        company.current_research_snapshot_id = running.id
        await session.commit()
        company_id = company.id

    async with session_factory() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        assert company.current_research_snapshot_id is not None, "the pointer was not set up"
        assert await reusable_company_research(session, company) is None, (
            "a running snapshot named by the pointer was offered for reuse"
        )


# -- FR-012: the prompt version is recorded ---------------------------------


async def test_a_layer_one_snapshot_records_which_prompt_produced_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-012 names the prompt version as part of the audit record.

    Without it, two runs whose prompts differed are indistinguishable and slice
    007 cannot compare like with like — the same unrecoverable-after-the-fact
    loss that made slice 006 add `0018`.
    """
    async with session_factory() as session:
        company, _ = await _seed(session, sub="pv-layer1")
        snapshot = await _succeeded(session, company)
        await session.commit()
        snapshot_id = snapshot.id

    async with session_factory() as session:
        stored = await session.get(CompanyResearchSnapshot, snapshot_id)
        assert stored is not None
        assert stored.prompt_version == COMPANY_PROMPT_VERSION
        assert stored.prompt_version, "prompt_version is empty; the column reads as never written"


async def test_a_layer_two_snapshot_records_which_prompt_produced_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, application = await _seed(session, sub="pv-layer2")
        company_snapshot = await _succeeded(session, company)
        role = await create_pending_role_research(session, application, company_snapshot)
        await session.commit()
        role_id = role.id

    async with session_factory() as session:
        stored = await session.get(RoleResearchSnapshot, role_id)
        assert stored is not None
        assert stored.prompt_version == ROLE_PROMPT_VERSION


async def test_the_two_layers_version_their_prompts_separately(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One column, two independent prompts. Recording the same constant for both
    would make a Layer 1 prompt change look like a Layer 2 one."""
    async with session_factory() as session:
        company, application = await _seed(session, sub="pv-both")
        company_snapshot = await _succeeded(session, company)
        role = await create_pending_role_research(session, application, company_snapshot)
        await session.commit()

    assert company_snapshot.prompt_version == COMPANY_PROMPT_VERSION
    assert role.prompt_version == ROLE_PROMPT_VERSION


# -- concurrent runs are refused by the database ----------------------------


async def test_a_second_in_flight_layer_one_run_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Slice 005: "an application-level check loses to a double-click; a partial
    unique index does not."

    Two concurrent cold runs would each bill ~$0.10-0.20 and the pointer would
    land wherever the race did.
    """
    async with session_factory() as session:
        company, _ = await _seed(session, sub="conc-l1")
        await create_pending_company_research(session, company)
        await session.commit()

    async with session_factory() as session:
        company = await session.get(Company, company.id)
        assert company is not None
        with pytest.raises(ConcurrentResearchRun):
            await create_pending_company_research(session, company)


async def test_a_second_in_flight_layer_two_run_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        company, application = await _seed(session, sub="conc-l2")
        company_snapshot = await _succeeded(session, company)
        await create_pending_role_research(session, application, company_snapshot)
        await session.commit()
        snapshot_id, application_id = company_snapshot.id, application.id

    async with session_factory() as session:
        application = await session.get(Application, application_id)
        company_snapshot = await session.get(CompanyResearchSnapshot, snapshot_id)
        assert application is not None and company_snapshot is not None
        with pytest.raises(ConcurrentResearchRun):
            await create_pending_role_research(session, application, company_snapshot)


async def test_a_finished_run_does_not_block_the_next_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The index is partial for this reason. A plain unique index would allow
    exactly one snapshot per company ever, which contradicts FR-011's "re-running
    writes a new snapshot and leaves every earlier one intact"."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="conc-sequential")
        first = await _succeeded(session, company)
        await session.commit()
        first_id = first.id

    async with session_factory() as session:
        company = await session.get(Company, company.id)
        assert company is not None
        second = await create_pending_company_research(session, company)
        await session.commit()
        assert second.id != first_id


async def test_a_failed_run_does_not_block_the_next_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A stuck run must stay recoverable. Slice 005 needed hand-written SQL three
    times because a guard refused the one action that would clear it."""
    async with session_factory() as session:
        company, _ = await _seed(session, sub="conc-afterfail")
        first = await create_pending_company_research(session, company)
        await fail_research(session, first, "overloaded")
        await session.commit()

    async with session_factory() as session:
        company = await session.get(Company, company.id)
        assert company is not None
        await create_pending_company_research(session, company)
        await session.commit()


async def test_two_companies_may_research_concurrently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The guard is per company, not global. A global one would serialise every
    user's research behind every other user's."""
    async with session_factory() as session:
        first, _ = await _seed(session, sub="conc-companyA")
        second, _ = await _seed(session, sub="conc-companyB")
        await create_pending_company_research(session, first)
        await create_pending_company_research(session, second)
        await session.commit()


async def test_an_unrelated_integrity_error_is_not_reported_as_a_concurrent_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The discriminator in `_is_running_conflict`, exercised through the real
    call path.

    **An earlier version of this test did not reach it.** It added a duplicate
    `ResearchSource` directly, so `create_pending_*` was never called and the
    helper never ran — a drill replacing the whole helper with `return True`
    left the suite green. This drives a *foreign key* violation through
    `create_pending_role_research` instead, which is the only way the helper can
    be asked to discriminate.

    Answering every `IntegrityError` with "already running" would turn a genuine
    bug into a message telling the user to wait for a run that does not exist.
    """
    async with session_factory() as session:
        company, application = await _seed(session, sub="conc-unrelated")
        # A real, succeeded Layer 1 exists — so the refusal below cannot be
        # mistaken for "no company research", which is a different path.
        await _succeeded(session, company)
        await session.commit()

    async with session_factory() as session:
        application = await session.get(Application, application.id)
        assert application is not None
        # A snapshot id that no row carries: the lineage foreign key must fail,
        # and it is not the in-flight guard.
        phantom = CompanyResearchSnapshot(
            user_id=application.user_id,
            company_id=company.id,
            sections={},
            status=ResearchStatus.SUCCEEDED,
        )
        phantom.id = uuid.uuid4()

        with pytest.raises(IntegrityError) as caught:
            await create_pending_role_research(session, application, phantom)

        assert not isinstance(caught.value, ConcurrentResearchRun), (
            "a foreign key violation was reported as a concurrent run"
        )
        assert "company_research_snapshot_id" in str(caught.value), (
            f"expected the lineage FK to fail; got {caught.value}"
        )


# -- FR-004: the configured duration bound is actually used -----------------


async def test_the_abandonment_bound_reads_the_configured_duration(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-004's second half, proved by changing the configuration.

    A test that aged a row past a hardcoded 900 would keep passing if the
    application stopped consulting the setting. This shortens the bound and
    asserts the *same* row changes classification.
    """
    async with session_factory() as session:
        company, _ = await _seed(session, sub="dur-config")
        good = await _succeeded(session, company)
        running = await create_pending_company_research(session, company)
        await session.commit()
        good_id, running_id, company_id = good.id, running.id, company.id

    async with session_factory() as session:
        await session.execute(
            text("UPDATE company_research_snapshots SET retrieved_at = :t WHERE id = :id"),
            {"t": datetime.now(UTC) - timedelta(seconds=120), "id": running_id},
        )
        await session.commit()

    # Two minutes old: in flight under the default bound.
    async with session_factory() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        current = await current_company_research(session, company)
        assert current is not None and current.id == running_id

    # The same row, under a 60-second bound, is abandoned.
    get_settings.cache_clear()
    monkeypatch.setenv("RESEARCH_MAX_DURATION_SECONDS", "60")
    get_settings.cache_clear()
    try:
        assert get_settings().research_max_duration_seconds == 60
        async with session_factory() as session:
            company = await session.get(Company, company_id)
            assert company is not None
            current = await current_company_research(session, company)
            assert current is not None and current.id == good_id, (
                "the shortened bound was ignored; is_abandoned is not reading configuration"
            )
    finally:
        monkeypatch.delenv("RESEARCH_MAX_DURATION_SECONDS", raising=False)
        get_settings.cache_clear()
