"""The advisor routes against the contract (T018/T028/T035).

Every path is exercised authenticated (the 401 side is the enumeration gate's
job), through the app in process, with the completion dependency overridden by
the prompt-reading double — the suite makes no provider call anywhere.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.api.deps import get_structured_completion
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    AdvisorRun,
    AdvisorRunStatus,
    Application,
    CareerMemory,
    Company,
    MemoryStatus,
    NormalizedStatus,
    User,
    normalize_company_name,
)
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.advisor_seam import ParsedPrompt, PromptReadingAdvisorSeam

pytestmark = pytest.mark.asyncio

_REJECTION_FACT = "outcome.rejection_rate.global"


def _answer(task: str, parsed: ParsedPrompt) -> dict[str, Any]:
    num, den = parsed.facts[_REJECTION_FACT]
    dispositions = [
        {
            "memory_id": memory_id,
            "action": "confirm",
            "fresh_fact_ids": [_REJECTION_FACT],
        }
        for memory_id in parsed.memory_ids
    ]
    return {
        "created": [
            {
                "claim": f"{num} of {den} applications ended rejected",
                "kind": "outcome_pattern",
                "scope_kind": "global",
                "cited_fact_ids": [_REJECTION_FACT],
                "priority": 70,
                "priority_reason": "the dominant outcome",
                "tentative": False,
            }
        ],
        "dispositions": dispositions,
    }


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


async def _seed(session: AsyncSession, *, applications: int = 3) -> User:
    sub = f"advisor-routes-{uuid.uuid4().hex[:10]}"
    user = await provision_user(
        session, {"sub": sub, "email": f"{sub}@example.com", "name": "Routes"}
    )
    if applications:
        company = Company(
            user_id=user.id, name="Seeded", normalized_name=normalize_company_name("Seeded")
        )
        session.add(company)
        await session.flush()
        for index in range(applications):
            application = Application(
                user_id=user.id,
                company_id=company.id,
                job_title=f"Role {index}",
                status="Rejected" if index == 0 else "Applied",
                normalized_status=(
                    NormalizedStatus.REJECTED if index == 0 else NormalizedStatus.APPLIED
                ),
            )
            application.date_added = datetime.now(UTC) - timedelta(days=10 + index)
            session.add(application)
    await session.commit()
    return user


def _install_seam(app, seam: PromptReadingAdvisorSeam) -> None:  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_structured_completion] = lambda: seam


async def _wait_ready(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """Poll like the frontend would. The background task runs on this loop,
    so a yield is enough; the deadline keeps a regression from hanging."""
    for _ in range(200):
        response = await client.get(f"/api/advisor/runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] != "pending":
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("run never left pending")


async def test_the_page_read_is_honest_when_empty(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        user = await _seed(session, applications=0)
    response = await _as(client, user).get("/api/advisor")
    assert response.status_code == 200
    body = response.json()
    assert body["memories"] == []
    assert body["latest_run"] is None
    assert body["coverage"] == {
        "applications": 0,
        "analysed": 0,
        "message": "Skill-level patterns grow as applications get match analyses.",
    }


async def test_no_history_answers_409_before_any_run_row_exists(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    app,  # type: ignore[no-untyped-def]
) -> None:
    async with session_factory() as session:
        user = await _seed(session, applications=0)
    response = await _as(client, user).post("/api/advisor/runs")
    assert response.status_code == 409
    assert "history" in response.json()["detail"]
    async with session_factory() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM advisor_runs WHERE user_id = :uid"),
            {"uid": str(user.id)},
        )
        assert count == 0, "the honest empty state must spend nothing"


async def test_trigger_poll_and_read_back(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    app,  # type: ignore[no-untyped-def]
) -> None:
    async with session_factory() as session:
        user = await _seed(session)
    seam = PromptReadingAdvisorSeam(answer=_answer)
    _install_seam(app, seam)

    accepted = await _as(client, user).post("/api/advisor/runs")
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["state"] == "running" and body["run"]["status"] == "pending"

    finished = await _wait_ready(client, body["run"]["id"])
    assert finished["status"] == "ready"
    assert finished["ops"] == {"proposed": 1, "applied": 1, "discarded": 0}
    assert finished["models"]["reason"] == "scripted/advisor_reason"
    assert finished["dispositions"], "a ready run exposes its journal"

    page = (await client.get("/api/advisor")).json()
    assert len(page["memories"]) == 1
    memory = page["memories"][0]
    assert memory["priority"] == 70
    assert memory["priority_reason"] == "the dominant outcome"  # N1: the shape carries it
    assert memory["evidence"]["facts"], "evidence travels to the page"
    assert page["latest_run"]["id"] == body["run"]["id"]


async def test_a_second_request_conflicts_while_one_is_pending(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    app,  # type: ignore[no-untyped-def]
) -> None:
    async with session_factory() as session:
        user = await _seed(session)
        run = AdvisorRun(
            user_id=user.id,
            status=AdvisorRunStatus.PENDING,
            rules_version="v1-advisor",
            dispositions=[],
        )
        session.add(run)
        await session.commit()

    response = await _as(client, user).post("/api/advisor/runs")
    assert response.status_code == 409
    assert response.json()["detail"] == "An analysis is already running."


async def test_an_abandoned_run_is_reaped_and_a_new_one_starts(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    app,  # type: ignore[no-untyped-def]
) -> None:
    async with session_factory() as session:
        user = await _seed(session)
        stale = AdvisorRun(
            user_id=user.id,
            status=AdvisorRunStatus.PENDING,
            rules_version="v1-advisor",
            dispositions=[],
        )
        session.add(stale)
        await session.commit()
        await session.execute(
            text(
                "UPDATE advisor_runs SET created_at = now() - interval '11 minutes' WHERE id = :id"
            ),
            {"id": stale.id},
        )
        await session.commit()
        stale_id = stale.id

    seam = PromptReadingAdvisorSeam(answer=_answer)
    _install_seam(app, seam)
    response = await _as(client, user).post("/api/advisor/runs")
    assert response.status_code == 202

    async with session_factory() as session:
        reaped = await session.get(AdvisorRun, stale_id)
        assert reaped is not None and reaped.status == "failed"
        assert reaped.error == "The analysis stopped before it finished."


async def test_runs_and_memories_are_ownership_scoped(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        owner = await _seed(session)
        stranger = await _seed(session)
        memory = CareerMemory(
            user_id=owner.id,
            advisor_run_id=(await _run_row(session, owner)).id,
            claim="1 of 3 applications ended rejected",
            kind="outcome_pattern",
            scope_kind="global",
            evidence={"facts": []},
            status=MemoryStatus.ACTIVE,
        )
        session.add(memory)
        await session.commit()
        memory_id = memory.id

    response = await _as(client, stranger).get(f"/api/advisor/memories/{memory_id}")
    assert response.status_code == 404
    response = await _as(client, owner).get(f"/api/advisor/memories/{memory_id}")
    assert response.status_code == 200
    assert response.json()["memory"]["claim"].startswith("1 of 3")


async def _run_row(session: AsyncSession, user: User) -> AdvisorRun:
    run = AdvisorRun(
        user_id=user.id,
        status=AdvisorRunStatus.READY,
        rules_version="v1-advisor",
        dispositions=[],
    )
    session.add(run)
    await session.flush()
    return run
