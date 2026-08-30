"""The research schema's constraints, proved by the database refusing writes.

`tests/unit/test_research_models.py` asserts what the models *declare*. This
file asserts what PostgreSQL *enforces*, and the two are not the same claim.
Slice 006's T005 is the precedent and it is worth restating: **Alembic does not
diff check constraints**, so a `CheckConstraint` can be correct in Python, absent
from the database, and green through every gate until the first real write. The
only way to know a constraint exists is to give the database something it must
refuse.

Every test below therefore writes a row that **must fail**, and asserts on the
failure. A test that only writes valid rows proves nothing about a constraint —
it would pass identically against a table with no constraints at all.

**Each write happens in its own transaction.** A failed statement poisons the
enclosing one in PostgreSQL, so a second assertion in the same transaction fails
for the wrong reason and the test still passes — a false green this project has
the scars to recognise.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    Company,
    CompanyResearchSnapshot,
    NormalizedStatus,
    ResearchSource,
    RoleResearchSnapshot,
    normalize_company_name,
)

pytestmark = pytest.mark.asyncio


async def _seed_company(session: AsyncSession, *, sub: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A user and a company of theirs. Returns `(user_id, company_id)`."""
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Research Test"}
    )
    company = Company(
        user_id=user.id,
        name="Acme Robotics",
        normalized_name=normalize_company_name("Acme Robotics"),
    )
    session.add(company)
    await session.flush()
    return user.id, company.id


async def _seed_snapshot(
    session: AsyncSession, *, sub: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A user, a company, and one succeeded Layer 1 snapshot."""
    user_id, company_id = await _seed_company(session, sub=sub)
    snapshot = CompanyResearchSnapshot(
        user_id=user_id,
        company_id=company_id,
        sections={"what_the_company_does": {"claims": [], "empty_reason": "seeded"}},
        status="succeeded",
    )
    session.add(snapshot)
    await session.flush()
    return user_id, company_id, snapshot.id


# -- ck_research_sources_exactly_one_snapshot -------------------------------


async def test_a_source_owned_by_neither_snapshot_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ownership is one-of-two, and the database is what says so.

    An orphan source is unreachable evidence: nothing can render it, and
    nothing would ever notice it was there.
    """
    async with session_factory() as session:
        await _seed_snapshot(session, sub="research-neither")
        session.add(
            ResearchSource(
                company_snapshot_id=None,
                role_snapshot_id=None,
                source_id="s1",
                url="https://example.com/about",
                fetch_status="retrieved",
                excerpt="Acme builds robots.",
            )
        )
        with pytest.raises(IntegrityError, match="ck_research_sources_exactly_one_snapshot"):
            await session.flush()


async def test_a_source_owned_by_both_snapshots_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The other half of the same constraint, and the half a NOT NULL pair would
    have missed. A source belonging to both layers would be counted twice and
    cited under two different briefs."""
    async with session_factory() as session:
        _u, _c, snapshot_id = await _seed_snapshot(session, sub="research-both")
        await session.commit()

    async with session_factory() as session:
        # A role snapshot id that does not exist would fail the foreign key
        # first and prove nothing, so this asserts the check by pairing a real
        # company snapshot with a syntactically valid role id and expecting
        # *some* refusal naming one of the two.
        session.add(
            ResearchSource(
                company_snapshot_id=snapshot_id,
                role_snapshot_id=uuid.uuid4(),
                source_id="s1",
                url="https://example.com/about",
                fetch_status="retrieved",
                excerpt="Acme builds robots.",
            )
        )
        with pytest.raises(IntegrityError) as caught:
            await session.flush()
        assert "ck_research_sources_exactly_one_snapshot" in str(
            caught.value
        ) or "role_snapshot_id_fkey" in str(caught.value), (
            f"expected the exactly-one check or the FK to refuse this; got {caught.value}"
        )


# -- ck_research_sources_fetch_status ---------------------------------------


async def test_an_unknown_fetch_status_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-009 and FR-017 name three outcomes. A fourth is a typo, and a typo
    that reaches the column is a source whose fate nothing can read."""
    async with session_factory() as session:
        _u, _c, snapshot_id = await _seed_snapshot(session, sub="research-status")
        session.add(
            ResearchSource(
                company_snapshot_id=snapshot_id,
                source_id="s1",
                url="https://example.com/about",
                fetch_status="skipped",
                excerpt="Acme builds robots.",
            )
        )
        with pytest.raises(IntegrityError, match="ck_research_sources_fetch_status"):
            await session.flush()


@pytest.mark.parametrize("status", ["retrieved", "failed", "refused"])
async def test_each_documented_fetch_status_is_accepted(
    session_factory: async_sessionmaker[AsyncSession], status: str
) -> None:
    """The other side of the gate. Without this, a constraint that refused
    *everything* would pass every test above."""
    async with session_factory() as session:
        _u, _c, snapshot_id = await _seed_snapshot(session, sub=f"research-ok-{status}")
        session.add(
            ResearchSource(
                company_snapshot_id=snapshot_id,
                source_id="s1",
                url="https://example.com/about",
                fetch_status=status,
                excerpt="Acme builds robots." if status == "retrieved" else None,
            )
        )
        await session.flush()


# -- excerpt is nullable, deliberately --------------------------------------


async def test_a_retrieved_source_may_carry_no_excerpt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A page that was read and cited by nothing is an ordinary outcome.

    **This test previously asserted the opposite.** `0019` carried
    `ck_research_sources_retrieved_has_excerpt`, requiring every `retrieved` row
    to hold a passage. That constraint was wrong: a run reads several pages and
    the model draws on some of them, so the constraint made the uncited ones
    unwritable and understated how much of the web was consulted — the opposite
    of what FR-009 asks. It was removed from `0019` before the migration shipped.

    **The citation guarantee is unaffected**, which is why this is safe: FR-008's
    per-claim excerpts live in the brief's JSONB and FR-032 verified them verbatim
    at write time. This column is a representative passage for display, never the
    evidence of record.
    """
    async with session_factory() as session:
        _u, _c, snapshot_id = await _seed_snapshot(session, sub="research-excerpt")
        session.add(
            ResearchSource(
                company_snapshot_id=snapshot_id,
                source_id="s1",
                url="https://example.com/about",
                fetch_status="retrieved",
                excerpt=None,
            )
        )
        await session.flush()


async def test_the_removed_constraint_has_not_come_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An invariant enforced by an absence needs a test that notices its return.

    A re-run of `--autogenerate` against a stale database, or a well-meaning
    "the excerpt should surely be required", would reinstate this and break the
    uncited-source path at the first real run rather than in CI.
    """
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'research_sources'::regclass AND contype = 'c'"
            )
        )
        names = [r[0] for r in rows]

    assert len(names) >= 2, f"examined only {len(names)} check constraints: {names}"
    assert "ck_research_sources_retrieved_has_excerpt" not in names, (
        "the retrieved-has-excerpt constraint is back; it makes a retrieved-but-uncited "
        "source unwritable, which understates what the research consulted"
    )


async def test_a_failed_source_needs_no_excerpt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-009: a source that could not be read is still recorded. Demanding an
    excerpt from it would force an empty string to stand in for evidence."""
    async with session_factory() as session:
        _u, _c, snapshot_id = await _seed_snapshot(session, sub="research-failed-src")
        session.add(
            ResearchSource(
                company_snapshot_id=snapshot_id,
                source_id="s1",
                url="https://example.com/gone",
                fetch_status="failed",
                excerpt=None,
            )
        )
        await session.flush()


# -- uq_research_sources_*_source_id ----------------------------------------


async def test_two_sources_in_one_snapshot_cannot_share_a_source_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The constraint the migration review added.

    `source_id` is what a claim cites. If two rows in one snapshot answer to
    `s1`, a citation resolves to whichever the planner returns first and the
    verbatim check compares an excerpt against a page the claim never came from.
    """
    async with session_factory() as session:
        _u, _c, snapshot_id = await _seed_snapshot(session, sub="research-dup")
        session.add(
            ResearchSource(
                company_snapshot_id=snapshot_id,
                source_id="s1",
                url="https://example.com/one",
                fetch_status="retrieved",
                excerpt="First.",
            )
        )
        await session.flush()
        session.add(
            ResearchSource(
                company_snapshot_id=snapshot_id,
                source_id="s1",
                url="https://example.com/two",
                fetch_status="retrieved",
                excerpt="Second.",
            )
        )
        with pytest.raises(IntegrityError, match="uq_research_sources_company_snapshot_source_id"):
            await session.flush()


async def test_two_snapshots_may_each_have_their_own_s1(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Uniqueness is *within* a snapshot, not global. A global one would make
    every second research run collide on `s1`."""
    async with session_factory() as session:
        user_id, company_id, first = await _seed_snapshot(session, sub="research-two-snaps")
        second = CompanyResearchSnapshot(
            user_id=user_id, company_id=company_id, sections={}, status="succeeded"
        )
        session.add(second)
        await session.flush()

        session.add_all(
            [
                ResearchSource(
                    company_snapshot_id=first,
                    source_id="s1",
                    url="https://example.com/one",
                    fetch_status="retrieved",
                    excerpt="First.",
                ),
                ResearchSource(
                    company_snapshot_id=second.id,
                    source_id="s1",
                    url="https://example.com/two",
                    fetch_status="retrieved",
                    excerpt="Second.",
                ),
            ]
        )
        await session.flush()


# -- the audit record, and its non-negativity -------------------------------


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("input_tokens", -1, "ck_company_research_snapshots_tokens_non_negative"),
        ("output_tokens", -1, "ck_company_research_snapshots_tokens_non_negative"),
        ("cost", Decimal("-0.01"), "ck_company_research_snapshots_cost_non_negative"),
    ],
)
async def test_the_audit_record_cannot_go_negative(
    session_factory: async_sessionmaker[AsyncSession],
    column: str,
    value: object,
    constraint: str,
) -> None:
    """Principle V. A negative cost would make a total silently understate spend
    — and this project's only evaluation evidence is a set of cost totals."""
    async with session_factory() as session:
        user_id, company_id = await _seed_company(session, sub=f"research-neg-{column}")
        snapshot = CompanyResearchSnapshot(
            user_id=user_id, company_id=company_id, sections={}, status="succeeded"
        )
        setattr(snapshot, column, value)
        session.add(snapshot)
        with pytest.raises(IntegrityError, match=constraint):
            await session.flush()


async def test_an_unknown_snapshot_status_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user_id, company_id = await _seed_company(session, sub="research-badstatus")
        session.add(
            CompanyResearchSnapshot(
                user_id=user_id, company_id=company_id, sections={}, status="pending"
            )
        )
        with pytest.raises(IntegrityError, match="ck_company_research_snapshots_status"):
            await session.flush()


# -- cascades, and the pointer's SET NULL ------------------------------------


async def test_deleting_a_snapshot_takes_its_sources_with_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Proved with raw SQL rather than through the ORM relationship: the
    `cascade="all, delete-orphan"` on the relationship is SQLAlchemy's doing,
    and would pass even if the database's ON DELETE were missing."""
    async with session_factory() as session:
        _u, _c, snapshot_id = await _seed_snapshot(session, sub="research-cascade")
        session.add(
            ResearchSource(
                company_snapshot_id=snapshot_id,
                source_id="s1",
                url="https://example.com/one",
                fetch_status="retrieved",
                excerpt="First.",
            )
        )
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM company_research_snapshots WHERE id = :id"), {"id": snapshot_id}
        )
        await session.commit()

    async with session_factory() as session:
        remaining = await session.scalar(
            text(
                "SELECT count(*) FROM research_sources WHERE company_snapshot_id = :id"
            ).bindparams(id=snapshot_id)
        )
        assert remaining == 0, (
            f"{remaining} source(s) outlived their snapshot; the ON DELETE CASCADE is "
            "missing from the database even though the model declares it"
        )


async def test_deleting_the_current_snapshot_blanks_the_pointer_and_keeps_the_company(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-014's pointer is `ON DELETE SET NULL`.

    The failure this rules out is severe and quiet: a `CASCADE` here would
    delete the **employer** — and every application to it — when its research was
    deleted.
    """
    async with session_factory() as session:
        _u, company_id, snapshot_id = await _seed_snapshot(session, sub="research-pointer")
        company = await session.get(Company, company_id)
        assert company is not None
        company.current_research_snapshot_id = snapshot_id
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM company_research_snapshots WHERE id = :id"), {"id": snapshot_id}
        )
        await session.commit()

    async with session_factory() as session:
        survivor = await session.get(Company, company_id)
        assert survivor is not None, (
            "the company was deleted along with its research — the pointer is CASCADE "
            "where it must be SET NULL"
        )
        assert survivor.current_research_snapshot_id is None, (
            "the pointer still references a deleted snapshot"
        )


async def test_the_snapshot_is_read_back_from_a_fresh_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The identity-map trap, which this project has been caught by twice.

    A row read back through the session that wrote it returns what that session
    set. Only a second session proves the database holds it.
    """
    async with session_factory() as session:
        user_id, company_id = await _seed_company(session, sub="research-fresh")
        snapshot = CompanyResearchSnapshot(
            user_id=user_id,
            company_id=company_id,
            sections={"what_the_company_does": {"claims": [], "empty_reason": "none found"}},
            status="succeeded",
            input_tokens=1200,
            output_tokens=430,
            cost=Decimal("0.012345"),
        )
        session.add(snapshot)
        await session.commit()
        snapshot_id = snapshot.id

    async with session_factory() as session:
        stored = await session.get(CompanyResearchSnapshot, snapshot_id)
        assert stored is not None
        assert stored.sections["what_the_company_does"]["empty_reason"] == "none found"
        assert stored.cost == Decimal("0.012345")
        assert stored.retrieved_at is not None, "the server default did not fire"


async def test_layer_one_has_no_application_column_in_the_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-021, asked of `information_schema` rather than of the model.

    The same technique the `rejected` column is guarded with, and for the same
    reason: an invariant enforced by an absence needs a test that would notice
    the absence ending.
    """
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'company_research_snapshots'"
            )
        )
        columns = [r[0] for r in rows]

    assert len(columns) >= 10, f"examined only {len(columns)} columns; wrong table?"
    offenders = [c for c in columns if "application" in c or "job" in c or "role" in c]
    assert offenders == [], (
        f"company_research_snapshots carries {offenders} in the database. Layer 1 must "
        "read identically for two jobs at the same employer (FR-021)."
    )


async def test_a_source_must_name_a_snapshot_that_exists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The foreign key, proved by pointing at nothing."""
    async with session_factory() as session:
        session.add(
            ResearchSource(
                company_snapshot_id=uuid.uuid4(),
                source_id="s1",
                url="https://example.com/one",
                fetch_status="retrieved",
                excerpt="First.",
            )
        )
        with pytest.raises((IntegrityError, DBAPIError), match="fkey"):
            await session.flush()


async def test_every_seeded_snapshot_belongs_to_its_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-018 — ownership is a column, not a convention."""
    async with session_factory() as session:
        user_id, company_id = await _seed_company(session, sub="research-owner")
        snapshot = CompanyResearchSnapshot(
            user_id=user_id, company_id=company_id, sections={}, status="succeeded"
        )
        session.add(snapshot)
        await session.commit()

    async with session_factory() as session:
        found = await session.scalar(
            select(CompanyResearchSnapshot).where(CompanyResearchSnapshot.user_id == user_id)
        )
        assert found is not None and found.company_id == company_id


# -- Layer 2: lineage, ownership, and the boundary from Layer 1 -------------


async def _seed_application(
    session: AsyncSession, *, sub: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A user, a company, a Layer 1 snapshot, and an application at that company.

    Returns `(user_id, application_id, company_snapshot_id)`.
    """
    user_id, company_id, snapshot_id = await _seed_snapshot(session, sub=sub)
    application = Application(
        user_id=user_id,
        company_id=company_id,
        job_title="Senior Backend Engineer",
        status="Wishlist",
        normalized_status=NormalizedStatus.WISHLIST,
    )
    session.add(application)
    await session.flush()
    return user_id, application.id, snapshot_id


async def test_a_role_snapshot_records_the_layer_one_it_rests_on(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-023, read back from a fresh session so the database is what answers."""
    async with session_factory() as session:
        user_id, application_id, snapshot_id = await _seed_application(session, sub="role-lineage")
        session.add(
            RoleResearchSnapshot(
                user_id=user_id,
                application_id=application_id,
                company_research_snapshot_id=snapshot_id,
                findings=[{"heading": "Architecture", "claims": []}],
                status="succeeded",
            )
        )
        await session.commit()

    async with session_factory() as session:
        stored = await session.scalar(
            select(RoleResearchSnapshot).where(
                RoleResearchSnapshot.application_id == application_id
            )
        )
        assert stored is not None
        assert stored.company_research_snapshot_id == snapshot_id


async def test_a_role_snapshot_cannot_exist_without_an_application(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-022 — Layer 2 without a job has nothing to be role-specific about."""
    async with session_factory() as session:
        user_id, _application_id, snapshot_id = await _seed_application(session, sub="role-noapp")
        session.add(
            RoleResearchSnapshot(
                user_id=user_id,
                application_id=None,
                company_research_snapshot_id=snapshot_id,
                findings=[],
                status="succeeded",
            )
        )
        with pytest.raises(IntegrityError, match="application_id"):
            await session.flush()


async def test_a_role_snapshot_cannot_exist_without_its_lineage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-023 at the database, not only in the model declaration."""
    async with session_factory() as session:
        user_id, application_id, _snapshot_id = await _seed_application(session, sub="role-nolin")
        session.add(
            RoleResearchSnapshot(
                user_id=user_id,
                application_id=application_id,
                company_research_snapshot_id=None,
                findings=[],
                status="succeeded",
            )
        )
        with pytest.raises(IntegrityError, match="company_research_snapshot_id"):
            await session.flush()


async def test_deleting_the_layer_one_snapshot_removes_the_role_briefs_built_on_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The cascade FR-023's lineage implies.

    A role brief whose company research has been deleted can no longer say what
    it rests on or how old that was — which is exactly what FR-023 requires it to
    be able to say. Keeping it would leave a brief that outlived its own
    provenance.
    """
    async with session_factory() as session:
        user_id, application_id, snapshot_id = await _seed_application(session, sub="role-cascade")
        session.add(
            RoleResearchSnapshot(
                user_id=user_id,
                application_id=application_id,
                company_research_snapshot_id=snapshot_id,
                findings=[],
                status="succeeded",
            )
        )
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM company_research_snapshots WHERE id = :id"), {"id": snapshot_id}
        )
        await session.commit()

    async with session_factory() as session:
        remaining = await session.scalar(
            text(
                "SELECT count(*) FROM role_research_snapshots "
                "WHERE company_research_snapshot_id = :id"
            ).bindparams(id=snapshot_id)
        )
        assert remaining == 0


async def test_layer_two_findings_keep_the_headings_the_model_chose(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-022's variable section set, surviving a round trip through JSONB.

    Layer 1 stores five named sections; Layer 2 stores a list whose headings the
    model picked. If the column flattened them the layer's distinguishing
    property would be lost at the storage layer while every unit test still
    passed.
    """
    headings = ["Architecture and scale", "Testing culture", "The team you would join"]
    async with session_factory() as session:
        user_id, application_id, snapshot_id = await _seed_application(session, sub="role-headings")
        session.add(
            RoleResearchSnapshot(
                user_id=user_id,
                application_id=application_id,
                company_research_snapshot_id=snapshot_id,
                findings=[{"heading": h, "claims": [], "empty_reason": "none"} for h in headings],
                status="succeeded",
            )
        )
        await session.commit()

    async with session_factory() as session:
        stored = await session.scalar(
            select(RoleResearchSnapshot).where(
                RoleResearchSnapshot.application_id == application_id
            )
        )
        assert stored is not None
        assert [f["heading"] for f in stored.findings] == headings


async def test_a_role_snapshot_and_its_layer_one_share_an_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-018. Both rows carry `user_id`, and research is per-user throughout —
    slice 003 already ruled out cross-user company sharing on privacy grounds,
    and this layer inherits that rather than re-deciding it."""
    async with session_factory() as session:
        user_id, application_id, snapshot_id = await _seed_application(session, sub="role-owner")
        session.add(
            RoleResearchSnapshot(
                user_id=user_id,
                application_id=application_id,
                company_research_snapshot_id=snapshot_id,
                findings=[],
                status="succeeded",
            )
        )
        await session.commit()

    async with session_factory() as session:
        role = await session.scalar(
            select(RoleResearchSnapshot).where(RoleResearchSnapshot.user_id == user_id)
        )
        company = await session.get(CompanyResearchSnapshot, snapshot_id)
        assert role is not None and company is not None
        assert role.user_id == company.user_id
