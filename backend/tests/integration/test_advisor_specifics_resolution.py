"""Resolving a memory's frozen evidence back to its requirement rows (V2).

`tests/unit/test_advisor_specifics.py` pins the taxonomy over rows handed to
it; this file proves the rows come back from PostgreSQL correctly — including
the two failure directions that matter: another user's row must not resolve,
and a deleted one must be reported rather than silently dropped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.advisor_specifics import resolve_specifics
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    AdvisorRun,
    AdvisorRunStatus,
    Application,
    CareerMemory,
    Company,
    MatchAnalysis,
    MatchRequirement,
    MatchStatus,
    MemoryStatus,
    NormalizedStatus,
    RequirementKind,
    RequirementVerdict,
    Shortfall,
    User,
    normalize_company_name,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

pytestmark = pytest.mark.asyncio


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


async def _user_with_rows(
    session: AsyncSession,
    rows: list[tuple[str, RequirementVerdict, Shortfall | None, int, str | None]],
) -> tuple[User, list[MatchRequirement]]:
    """One user, one analysed application, and the requirement rows given."""
    sub = f"specifics-{uuid.uuid4().hex[:10]}"
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Specifics"}
    )
    company = Company(
        user_id=user.id, name="DemoCo", normalized_name=normalize_company_name(f"D{sub}")
    )
    session.add(company)
    await session.flush()
    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Backend Engineer",
        status="Applied",
        normalized_status=NormalizedStatus.APPLIED,
        requirements=["x"],
    )
    application.date_added = datetime.now(UTC)
    session.add(application)
    await session.flush()
    analysis = MatchAnalysis(
        application_id=application.id,
        status=MatchStatus.READY,
        criteria_version="v",
        overall_score=60,
        requirements=[],
    )
    session.add(analysis)
    await session.flush()

    created: list[MatchRequirement] = []
    for ordinal, (row_text, verdict, shortfall, importance, quote) in enumerate(rows):
        # `ck_match_requirement_grounded` (AI-008): every verdict except
        # `unverified` must quote the profile. Cases that do not care about the
        # quote still have to satisfy it, so supply one.
        if quote is None and verdict != RequirementVerdict.UNVERIFIED:
            quote = f"Profile evidence for {row_text[:24]}"
        row = MatchRequirement(
            analysis_id=analysis.id,
            ordinal=ordinal,
            text_=row_text,
            kind=RequirementKind.MUST_HAVE,
            importance=importance,
            verdict=verdict,
            shortfall=shortfall,
            evidence=quote,
        )
        session.add(row)
        created.append(row)
    await session.flush()
    return user, created


def _evidence(row_ids: list[uuid.UUID], gap_ids: list[uuid.UUID], topic: str = "Cloud") -> dict:  # type: ignore[type-arg]
    return {
        "as_of": datetime.now(UTC).isoformat(),
        "rules_version": "v1-advisor",
        "facts": [
            {
                "fact_id": "tier2.requirement.g1",
                "kind": "tier2.requirement",
                "scope_kind": "skill",
                "scope_value": topic,
                "numerator": len(row_ids),
                "denominator": 7,
                "value": f"{topic} appears in {len(row_ids)} of 7 analysed postings",
                "record_ids": [str(i) for i in row_ids],
                "basis": "b",
            },
            {
                "fact_id": "tier2.gap.g1",
                "kind": "tier2.gap",
                "scope_kind": "skill",
                "scope_value": topic,
                "numerator": len(gap_ids),
                "denominator": 7,
                "value": f"{topic} was a gap in {len(gap_ids)} of 7 analysed postings",
                "record_ids": [str(i) for i in gap_ids],
                "basis": "b",
            },
        ],
        "groupings": [],
    }


async def _memory(
    session: AsyncSession,
    user: User,
    evidence: dict,  # type: ignore[type-arg]
    *,
    scope_kind: str = "skill",
    scope_value: str | None = "Cloud",
) -> CareerMemory:
    run = AdvisorRun(
        user_id=user.id,
        status=AdvisorRunStatus.READY,
        rules_version="v1-advisor",
        dispositions=[],
    )
    session.add(run)
    await session.flush()
    memory = CareerMemory(
        user_id=user.id,
        advisor_run_id=run.id,
        claim="Cloud Platforms was a gap in 2 of 7 analysed postings",
        kind="recurring_gap",
        scope_kind=scope_kind,
        scope_value=scope_value,
        evidence=evidence,
        priority=80,
        priority_reason="the most frequent unmet requirement",
        status=MemoryStatus.ACTIVE,
    )
    session.add(memory)
    await session.flush()
    return memory


async def test_rows_resolve_with_their_verdict_shortfall_and_quote(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user, rows = await _user_with_rows(
            session,
            [
                (
                    "Deep understanding of cloud infrastructure (AWS/GCP)",
                    RequirementVerdict.PARTIAL,
                    Shortfall.CAPABILITY,
                    65,
                    "Building cloud-based applications",
                ),
                (
                    "Experience with cloud platforms (e.g. AWS, GCP)",
                    RequirementVerdict.CONFIRMED,
                    None,
                    70,
                    "Building cloud-based applications",
                ),
            ],
        )
        ids = [row.id for row in rows]
        memory = await _memory(session, user, _evidence(ids, [ids[0]]))
        await session.commit()

        resolved = await resolve_specifics(
            session, user_id=user.id, evidence_by_memory={memory.id: memory.evidence}
        )

    specifics = resolved[memory.id]
    assert len(specifics.items) == 2 and specifics.unresolved == 0
    # Most important ask first — deterministic ordering.
    assert specifics.items[0].importance == 70
    assert specifics.items[0].verdict == "confirmed" and specifics.items[0].shortfall is None
    partial = specifics.items[1]
    assert partial.verdict == "partial" and partial.shortfall == "capability"
    assert partial.text.startswith("Deep understanding"), "verbatim, not paraphrased"
    assert specifics.profile_quotes == ["Building cloud-based applications"], "deduped"


async def test_another_users_row_never_resolves(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ownership comes from the session, not from the id the evidence names."""
    async with session_factory() as session:
        owner, owner_rows = await _user_with_rows(
            session, [("Owner requirement", RequirementVerdict.GAP, Shortfall.CAPABILITY, 50, None)]
        )
        stranger, stranger_rows = await _user_with_rows(
            session,
            [
                (
                    "Stranger requirement",
                    RequirementVerdict.GAP,
                    Shortfall.CAPABILITY,
                    90,
                    "secret quote",
                )
            ],
        )
        # The owner's memory points at BOTH ids — the stranger's must not leak.
        ids = [owner_rows[0].id, stranger_rows[0].id]
        memory = await _memory(session, owner, _evidence(ids, ids))
        await session.commit()

        resolved = await resolve_specifics(
            session, user_id=owner.id, evidence_by_memory={memory.id: memory.evidence}
        )

    specifics = resolved[memory.id]
    assert [item.text for item in specifics.items] == ["Owner requirement"]
    assert specifics.unresolved == 1, "the foreign row is reported missing, not rendered"
    assert "secret quote" not in str(specifics.items)
    assert stranger.id != owner.id


async def test_deleted_rows_are_counted_not_silently_dropped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user, rows = await _user_with_rows(
            session,
            [
                ("Kept requirement", RequirementVerdict.GAP, Shortfall.CAPABILITY, 50, None),
                ("Doomed requirement", RequirementVerdict.GAP, Shortfall.CAPABILITY, 60, None),
            ],
        )
        ids = [row.id for row in rows]
        memory = await _memory(session, user, _evidence(ids, ids))
        await session.commit()
        await session.execute(text("DELETE FROM match_requirements WHERE id = :i"), {"i": ids[1]})
        await session.commit()

        resolved = await resolve_specifics(
            session, user_id=user.id, evidence_by_memory={memory.id: memory.evidence}
        )

    specifics = resolved[memory.id]
    assert [item.text for item in specifics.items] == ["Kept requirement"]
    assert specifics.unresolved == 1, (
        "the frozen headline still counts it; the reader is told it cannot be read"
    )


async def test_many_memories_resolve_in_one_query(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Batching is the contract: the page's cost must not scale with the
    number of memories (the N+1 shape this project has paid for elsewhere)."""
    async with session_factory() as session:
        user, rows = await _user_with_rows(
            session,
            [
                (f"Requirement {i}", RequirementVerdict.GAP, Shortfall.CAPABILITY, 50 + i, None)
                for i in range(6)
            ],
        )
        memories = [
            await _memory(session, user, _evidence([rows[i].id, rows[i + 1].id], [rows[i].id]))
            for i in range(0, 6, 2)
        ]
        await session.commit()

        statements: list[str] = []
        from sqlalchemy import event as sa_event

        sync_engine = session.get_bind()

        def record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
            if "match_requirements" in statement:
                statements.append(statement)

        sa_event.listen(sync_engine, "before_cursor_execute", record)
        try:
            resolved = await resolve_specifics(
                session,
                user_id=user.id,
                evidence_by_memory={m.id: m.evidence for m in memories},
            )
        finally:
            sa_event.remove(sync_engine, "before_cursor_execute", record)

    assert len(resolved) == 3
    assert all(len(s.items) == 2 for s in resolved.values())
    assert len(statements) == 1, f"expected one batched query, saw {len(statements)}"


async def test_the_api_exposes_specifics_assessment_and_a_typed_action(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        user, rows = await _user_with_rows(
            session,
            [
                (
                    "Hands-on Kubernetes in production",
                    RequirementVerdict.GAP,
                    Shortfall.CAPABILITY,
                    80,
                    None,
                ),
                (
                    "Experience with Docker",
                    RequirementVerdict.PARTIAL,
                    Shortfall.CAPABILITY,
                    70,
                    "Containerised services",
                ),
                (
                    "Container orchestration at scale",
                    RequirementVerdict.GAP,
                    Shortfall.CAPABILITY,
                    60,
                    None,
                ),
                ("Helm familiarity", RequirementVerdict.GAP, Shortfall.CAPABILITY, 55, None),
            ],
        )
        ids = [row.id for row in rows]
        memory = await _memory(session, user, _evidence(ids, ids[:3]))
        await session.commit()
        memory_id = memory.id

    body = (await _as(client, user).get("/api/advisor")).json()
    assert body["action_rules_version"] == "v1-actions"
    item = next(m for m in body["memories"] if m["id"] == str(memory_id))

    assert len(item["specifics"]) == 4
    assert item["specifics"][0]["text"] == "Hands-on Kubernetes in production"
    assert item["specifics"][0]["verdict"] == "gap"
    assert item["specifics"][0]["shortfall"] == "capability"
    assert item["specifics"][0]["resolved"] is True
    assert item["specifics_unresolved"] == 0
    assert "Containerised services" in item["profile_quotes"]
    assert len(item["profile_quotes"]) == 4, "one distinct quote per row, deduped"
    assert len(item["specific_labels"]) == 3, "the compact card takes at most three"

    assert item["assessment"] and not any(c.isdigit() for c in item["assessment"])
    # `action` is the plain text, `recommended_action` the typed form — see B1 in
    # `_memory_out`. Both are asserted so neither can drift away from the other.
    assert item["action"] == (
        "Build hands-on depth here — this is a capability gap, not a wording one."
    )
    assert item["recommended_action"] == {
        "category": "learn_build",
        "text": ("Build hands-on depth here — this is a capability gap, not a wording one."),
    }

    # The single-memory route resolves the head memory too.
    detail = (await _as(client, user).get(f"/api/advisor/memories/{memory_id}")).json()
    assert len(detail["memory"]["specifics"]) == 4


async def test_a_memory_with_no_tier2_evidence_stays_serialisable(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A Tier-1 (portfolio) memory has no requirement rows at all: no
    specifics, no assessment, no action — and certainly no crash."""
    async with session_factory() as session:
        user, _ = await _user_with_rows(
            session, [("anything", RequirementVerdict.CONFIRMED, None, 50, None)]
        )
        tier1 = {
            "as_of": datetime.now(UTC).isoformat(),
            "rules_version": "v1-advisor",
            "facts": [
                {
                    "fact_id": "outcome.rejection_rate.global",
                    "kind": "outcome",
                    "scope_kind": "global",
                    "numerator": 4,
                    "denominator": 7,
                    "value": "4 of 7 applications ended rejected",
                    "record_ids": [],
                    "basis": "b",
                }
            ],
            "groupings": [],
        }
        # Built with its scope, not mutated afterwards: content columns are
        # frozen at insert and the ORM guard refuses a later write.
        memory = await _memory(session, user, tier1, scope_kind="global", scope_value=None)
        await session.commit()
        memory_id = memory.id

    body = (await _as(client, user).get("/api/advisor")).json()
    item = next(m for m in body["memories"] if m["id"] == str(memory_id))
    assert item["tier"] == "portfolio"
    assert item["specifics"] == [] and item["specifics_unresolved"] == 0
    assert item["assessment"] is None
    assert item["action"] is None


async def _cloud_rows(session: AsyncSession) -> tuple[User, list[MatchRequirement]]:
    """Four capability rows — the shape the assessment taxonomy calls a capability gap."""
    return await _user_with_rows(
        session,
        [
            (
                "Hands-on Kubernetes in production",
                RequirementVerdict.GAP,
                Shortfall.CAPABILITY,
                80,
                None,
            ),
            (
                "Experience with Docker",
                RequirementVerdict.PARTIAL,
                Shortfall.CAPABILITY,
                70,
                "Containers",
            ),
            (
                "Container orchestration at scale",
                RequirementVerdict.GAP,
                Shortfall.CAPABILITY,
                60,
                None,
            ),
            ("Terraform familiarity", RequirementVerdict.GAP, Shortfall.CAPABILITY, 55, None),
        ],
    )


_UNAVAILABLE = "The requirements behind this claim are no longer available to read."


async def test_the_action_field_stays_a_string_for_one_deployment_cycle(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """B1. The two services deploy independently and the backend lands first.

    A frontend bundle compiled against `action: string` that receives an object
    renders it as a React child, which throws — and the app has no error
    boundary, so the whole Advisor page goes blank until the frontend build
    catches up. `action` therefore stays a string while the typed form ships
    beside it.

    Asserted as a **type**, not a value: the point is the shape an already-built
    bundle will meet, not the wording.
    """
    async with session_factory() as session:
        user, rows = await _cloud_rows(session)
        memory = await _memory(session, user, _evidence([r.id for r in rows], [rows[0].id]))
        await session.commit()
        memory_id = memory.id

    body = (await _as(client, user).get("/api/advisor")).json()
    item = next(m for m in body["memories"] if m["id"] == str(memory_id))

    assert isinstance(item["action"], str), (
        f"`action` is {type(item['action']).__name__}; a bundle built against a string "
        "renders an object as a React child and blanks the page"
    )
    assert isinstance(item["recommended_action"], dict)
    assert item["recommended_action"]["text"] == item["action"], (
        "the two forms describe the same next step and must not drift"
    )
    assert item["recommended_action"]["category"] == "learn_build"


async def test_lineage_entries_do_not_claim_their_requirements_are_unreadable(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """H1. The lineage view does not resolve rows; that is not the same as their being gone.

    It rendered every superseded memory with *"The requirements behind this claim
    are no longer available to read."* beside `specifics_unresolved: 0` — a
    statement about the user's own evidence that was simply false.
    """
    async with session_factory() as session:
        user, rows = await _cloud_rows(session)
        ids = [row.id for row in rows]
        older = await _memory(session, user, _evidence(ids, ids[:2]))
        await session.flush()
        # Born with its lineage: a `before_update` listener freezes memory content,
        # so `supersedes_id` cannot be assigned after the insert.
        newer = CareerMemory(
            user_id=user.id,
            advisor_run_id=older.advisor_run_id,
            claim=older.claim,
            kind=older.kind,
            scope_kind=older.scope_kind,
            scope_value=older.scope_value,
            evidence=_evidence(ids, ids[:2]),
            priority=80,
            priority_reason="the most frequent unmet requirement",
            status=MemoryStatus.ACTIVE,
            supersedes_id=older.id,
        )
        session.add(newer)
        older.status = MemoryStatus.SUPERSEDED
        await session.commit()
        newer_id = newer.id

    detail = (await _as(client, user).get(f"/api/advisor/memories/{newer_id}")).json()
    assert detail["lineage"], "no lineage entry — this gate would examine nothing"

    for entry in detail["lineage"]:
        assert entry["assessment"] is None, (
            f"a lineage entry asserts {entry['assessment']!r} about rows nobody tried to read"
        )
        assert entry["action"] is None
        assert entry["recommended_action"] is None

    # ...and the head, which *is* resolved, still says something.
    assert detail["memory"]["assessment"] and detail["memory"]["assessment"] != _UNAVAILABLE


async def test_the_dismiss_response_does_not_claim_requirements_are_unreadable(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """H1, the other unresolved caller. Dismissing must not restate the memory falsely."""
    async with session_factory() as session:
        user, rows = await _cloud_rows(session)
        memory = await _memory(session, user, _evidence([r.id for r in rows], [rows[0].id]))
        await session.commit()
        memory_id = memory.id

    response = await _as(client, user).post(f"/api/advisor/memories/{memory_id}/dismiss")
    assert response.status_code == 200
    dismissed = response.json()["memory"]

    assert dismissed["assessment"] is None, (
        f"the dismiss response asserts {dismissed['assessment']!r} about rows it never read"
    )
    assert dismissed["action"] is None
    assert dismissed["recommended_action"] is None
    assert dismissed["specifics_unresolved"] == 0
    assert dismissed["status"] == "retired"


async def test_an_unreadable_row_is_reported_through_the_real_route(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """H4. The count has to survive the serialisation hop, not just the resolver.

    `Specifics.unresolved` was computed correctly and asserted at three layers —
    each of which **supplied the value itself**: the unit test built
    `Specifics(unresolved=4)`, the frontend fixture wrote `4`, and the only route
    assertions expected `0`. Hard-coding `"specifics_unresolved": 0` in the route
    passed every one of them while killing the invariant the field exists for.

    So: four rows, delete one behind the memory's back, then ask the real
    endpoint.
    """
    async with session_factory() as session:
        user, rows = await _cloud_rows(session)
        ids = [row.id for row in rows]
        memory = await _memory(session, user, _evidence(ids, ids[:2]))
        await session.commit()
        await session.execute(text("DELETE FROM match_requirements WHERE id = :i"), {"i": ids[2]})
        await session.commit()
        memory_id = memory.id

    body = (await _as(client, user).get("/api/advisor")).json()
    item = next(m for m in body["memories"] if m["id"] == str(memory_id))

    assert len(item["specifics"]) == 3, "the surviving rows"
    assert item["specifics_unresolved"] == 1, (
        "the deleted row must be reported; the frozen headline still counts it"
    )
    assert "Container orchestration at scale" not in [s["text"] for s in item["specifics"]]
    # The rows that remain still support the same reading, so the assessment must
    # not collapse to the unavailable sentence.
    assert item["assessment"] == (
        "You partly meet these asks — the shortfalls are depth of hands-on capability."
    )
