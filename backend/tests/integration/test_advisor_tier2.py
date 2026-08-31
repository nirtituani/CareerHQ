"""US3 end to end: skill patterns grow with analyses, honest at small N (T033).

Four analysed postings share an AWS requirement under varied wordings. The
grouping double buckets the enumerated `[req:]` rows it parsed out of the
grouping prompt; deterministic counting produces `tier2.gap.*` at 4/4; the
reasoning double claims it — and the floor forces the memory **tentative**
(denominator 4 < 5), whatever the model said.

Two more analyses land; the next run confirms with a fresh 6/6 fact, and the
tentative memory is **promoted to active** — the floor working in both
directions, end to end.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.advise_career import create_pending_run, run_advisor
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    CareerMemory,
    Company,
    MatchAnalysis,
    MatchRequirement,
    MatchStatus,
    NormalizedStatus,
    RequirementKind,
    RequirementVerdict,
    Shortfall,
    User,
    normalize_company_name,
)
from tests.support.advisor_seam import ParsedPrompt, PromptReadingAdvisorSeam

pytestmark = pytest.mark.asyncio

_AWS_WORDINGS = (
    "AWS",
    "5+ years of AWS experience",
    "Amazon Web Services in production",
    "deep AWS knowledge",
    "AWS (EC2, S3)",
    "hands-on AWS",
)


async def _analysed_application(
    session: AsyncSession, user: User, company_id: uuid.UUID, index: int
) -> None:
    application = Application(
        user_id=user.id,
        company_id=company_id,
        job_title=f"Backend Engineer {index}",
        status="Applied",
        normalized_status=NormalizedStatus.APPLIED,
        requirements=[_AWS_WORDINGS[index]],
    )
    application.date_added = datetime.now(UTC) - timedelta(days=40 - index)
    session.add(application)
    await session.flush()
    analysis = MatchAnalysis(
        application_id=application.id,
        status=MatchStatus.READY,
        criteria_version="test",
        overall_score=55 + index,
        requirements=[],
    )
    session.add(analysis)
    await session.flush()
    session.add(
        MatchRequirement(
            analysis_id=analysis.id,
            ordinal=0,
            text_=_AWS_WORDINGS[index],
            kind=RequirementKind.MUST_HAVE,
            importance=80,
            verdict=RequirementVerdict.GAP,
            shortfall=Shortfall.CAPABILITY,
            evidence="the profile shows no cloud provider experience",
        )
    )
    await session.flush()


def _grouping_answer(parsed: ParsedPrompt) -> dict[str, Any]:
    """Bucket every parsed requirement row whose text mentions AWS/Amazon —
    ids read out of the grouping prompt, exactly as a model would."""
    members = [
        req_id
        for req_id, text in parsed.req_texts.items()
        if "aws" in text.lower() or "amazon" in text.lower()
    ]
    assert members, "the grouping prompt rendered no requirement rows"
    return {
        "groups": [
            {"group_id": "g_aws", "label": "AWS", "group_kind": "skill", "member_ids": members}
        ]
    }


def _answer(task: str, parsed: ParsedPrompt) -> dict[str, Any]:
    if task == "advisor_grouping":
        return _grouping_answer(parsed)
    num, den = parsed.facts["tier2.gap.g_aws"]
    dispositions = [
        {"memory_id": memory_id, "action": "confirm", "fresh_fact_ids": ["tier2.gap.g_aws"]}
        for memory_id in parsed.memory_ids
    ]
    created = []
    if not parsed.memory_ids:
        created = [
            {
                "claim": f"AWS was judged a gap in {num} of {den} analysed Backend postings",
                "kind": "recurring_gap",
                "scope_kind": "skill",
                "scope_value": "AWS",
                "cited_fact_ids": ["tier2.gap.g_aws"],
                "grouping_ids": ["g_aws"],
                "priority": 85,
                "priority_reason": "the most frequent gap in the analysed postings",
                # The model claims full confidence; the floor must overrule it.
                "tentative": False,
            }
        ]
    return {
        "created": created,
        "dispositions": dispositions,
        "nothing_found_reason": None if created else "confirming the existing pattern",
    }


async def _run(session_factory, user_id: uuid.UUID) -> None:  # type: ignore[no-untyped-def]
    async with session_factory() as session:
        user = await session.get(User, user_id)
        run = await create_pending_run(session, user)
        assert run is not None
        await session.commit()
        run_id = run.id
    seam = PromptReadingAdvisorSeam(answer=_answer, max_calls=2)
    async with session_factory() as session:
        await run_advisor(session, run_id=run_id, completion=seam)
        await session.commit()
    assert seam.tasks == ["advisor_grouping", "advisor_reason"], (
        "with analysed applications present, the grouping step runs first"
    )


async def test_the_floor_forces_tentative_then_promotes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        sub = f"tier2-{uuid.uuid4().hex[:10]}"
        user = await provision_user(
            session, {"sub": sub, "email": f"{sub}@example.com", "name": "Tier2"}
        )
        company = Company(
            user_id=user.id, name="Seeded", normalized_name=normalize_company_name("Seeded")
        )
        session.add(company)
        await session.flush()
        for index in range(4):
            await _analysed_application(session, user, company.id, index)
        await session.commit()
        user_id, company_id = user.id, company.id

    await _run(session_factory, user_id)

    async with session_factory() as session:
        memory = (
            await session.scalars(select(CareerMemory).where(CareerMemory.user_id == user_id))
        ).one()
        assert memory.status == "tentative", (
            "denominator 4 is under the floor of 5 — the gate must overrule the "
            "model's own full-confidence flag"
        )
        assert "4 of 4" in memory.claim
        assert memory.scope_value == "AWS"
        # FR-007: the grouping is frozen into the evidence, auditable.
        assert memory.evidence["groupings"], "the grouping must travel with the memory"
        assert memory.evidence["groupings"][0]["label"] == "AWS"
        assert len(memory.evidence["groupings"][0]["member_ids"]) == 4
        memory_id = memory.id

    # -- two more analysed postings land: 6/6, over the floor ----------------
    async with session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        for index in (4, 5):
            await _analysed_application(session, user, company_id, index)
        await session.commit()

    await _run(session_factory, user_id)

    async with session_factory() as session:
        promoted = await session.get(CareerMemory, memory_id)
        assert promoted is not None
        assert promoted.status == "active", (
            "a confirmation whose fresh evidence clears the floor promotes the memory"
        )
        assert "4 of 4" in promoted.claim, "the frozen claim itself never changes"
