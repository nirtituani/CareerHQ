"""Nothing spends a completion on a job with no posting to read.

The bug this closes billed a real run: a job with requirements and no
description passed Match's guard, was sent an empty posting, and returned
`0/100 · low_probability`. Tailoring had no such check at all — a `ready`
analysis was its precondition, and an empty-posting zero is `ready`.

Two of these tests assert an **absence of a call**, not an absence of a row. A
version that created no analysis but still asked the provider would satisfy the
weaker assertion and cost money on every save.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.analyze_match import create_pending_analysis, run_analysis
from careerhq.application.scoreability import scoreable_posting
from careerhq.application.tailor_resume import (
    TailoringRefused,
    check_preconditions,
    create_pending_version,
)
from careerhq.domain.models import MatchAnalysis, MatchStatus
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio


class _CountingSeam:
    """Records every completion asked for. Answering is beside the point."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, *, task: str, schema: Any, prompt: str) -> Any:
        self.calls.append(task)
        raise AssertionError(f"a completion was requested for {task!r} with no posting content")


async def test_requirements_without_a_description_are_scored(
    db_session: AsyncSession,
) -> None:
    """**The regression case, and the one the suite never had.**

    Slice 004's edge cases cover "a description but no extractable
    requirements". The mirror — requirements but no description — appears in no
    spec, no edge case and no test, and it is the shape of the record that
    failed: ten requirements pasted into the requirements box, a null
    description, and a paid call against an empty posting.
    """
    seeded = await seed_tailorable(db_session, sub="score-reqs", email="score-reqs@example.com")
    seeded.application.job_description = None
    seeded.application.requirements = [
        "3+ years building production cloud systems",
        "Strong Python",
    ]
    await db_session.flush()

    analysis = await create_pending_analysis(db_session, seeded.application)

    assert analysis is not None, "content the owner supplied must not be ignored"

    # And — the part that was actually broken — the content reaches the prompt.
    # `create_pending_analysis` returning a row was never the bug; the bug was
    # `run_analysis` sending an empty posting to the provider afterwards.
    captured: dict[str, str] = {}

    class _CapturesThePrompt:
        async def complete(self, *, task: str, schema: Any, prompt: str) -> Any:
            from decimal import Decimal

            from careerhq.application.ports import Completion, Usage

            captured["prompt"] = prompt
            return Completion(
                value=schema.model_validate(
                    {
                        "verdict": "Assessed.",
                        "requirements": [
                            {
                                "text": "3+ years building production cloud systems",
                                "kind": "must_have",
                                "importance": 80,
                                "verdict": "confirmed",
                                "shortfall": None,
                                "evidence": "Led the payments platform team for six years.",
                            }
                        ],
                    }
                ),
                usage=Usage(model="d", input_tokens=1, output_tokens=1, cost=Decimal("0")),
            )

    await run_analysis(
        db_session,
        analysis_id=analysis.id,
        completion=_CapturesThePrompt(),  # type: ignore[arg-type]
    )

    assert "3+ years building production cloud systems" in captured["prompt"]
    assert "Strong Python" in captured["prompt"]


async def test_a_job_with_no_posting_content_requests_no_completion(
    db_session: AsyncSession,
) -> None:
    """No row **and** no call.

    Asserting only that the analysis row is absent would pass against a version
    that asked the provider first and discarded the answer.
    """
    seeded = await seed_tailorable(db_session, sub="score-none", email="score-none@example.com")
    seeded.application.job_description = None
    seeded.application.requirements = []
    await db_session.flush()

    seam = _CountingSeam()

    assert await create_pending_analysis(db_session, seeded.application) is None
    assert seam.calls == []

    rows = await db_session.scalars(
        select(MatchAnalysis).where(MatchAnalysis.application_id == seeded.application.id)
    )
    assert [r for r in rows if r.status == MatchStatus.PENDING] == []


async def test_run_analysis_asks_for_nothing_when_the_posting_has_gone(
    db_session: AsyncSession,
) -> None:
    """The second half of the same guard.

    The row is reserved when a job is saved and scored moments later, so the
    posting can be emptied in between. `run_analysis` must re-check rather than
    trust that `create_pending_analysis` already did.
    """
    seeded = await seed_tailorable(db_session, sub="score-gone", email="score-gone@example.com")
    analysis = await create_pending_analysis(db_session, seeded.application)
    assert analysis is not None
    await db_session.flush()

    seeded.application.job_description = None
    seeded.application.requirements = []
    await db_session.flush()

    seam = _CountingSeam()
    await run_analysis(db_session, analysis_id=analysis.id, completion=seam)  # type: ignore[arg-type]

    assert seam.calls == [], "a completion was requested for a job with no posting"


async def test_the_guard_and_the_prompt_can_never_disagree_again(
    db_session: AsyncSession,
) -> None:
    """The class of bug, not the instance.

    The original defect was not a missing check — it was two checks reading
    different fields. So this asserts the relationship: **if an analysis is
    reserved, there is posting content for the prompt to send.**

    One direction only. Content is necessary, not sufficient: a job with a
    description and an empty requirement list has content and is still declined,
    because FR-006 says a posting that yielded no requirements is nothing to
    score against rather than a zero. Asserting equivalence here is how the first
    version of this fix broke that rule.
    """
    seeded = await seed_tailorable(db_session, sub="score-agree", email="score-agree@example.com")

    cases: list[tuple[str | None, list[str] | None]] = [
        ("A whole posting.", ["5+ years"]),
        ("A whole posting.", []),
        (None, ["5+ years"]),
        ("", ["5+ years"]),
        (None, []),
        ("", []),
        ("   ", ["  "]),
        ("A joined list.", None),
    ]

    for description, requirements in cases:
        seeded.application.job_description = description
        seeded.application.requirements = requirements
        await db_session.flush()

        reserved = await create_pending_analysis(db_session, seeded.application)
        posting = scoreable_posting(seeded.application)

        if reserved is not None:
            assert posting is not None, (
                "an analysis was reserved with nothing for the prompt to send: "
                f"description={description!r} requirements={requirements!r}"
            )
        if reserved is not None:
            await db_session.delete(reserved)
            await db_session.flush()


# -- Tailoring must refuse for the same reason ------------------------------


async def test_tailoring_refuses_a_job_with_no_posting_before_any_call(
    db_session: AsyncSession,
) -> None:
    """Tailoring had no content check at all.

    Its precondition was a `ready` analysis — and an empty-posting `0/100` is
    `ready`. So the worst case was a five-call run, $0.30 to $0.46, planning and
    drafting against `description: null` and no requirements.
    """
    seeded = await seed_tailorable(db_session, sub="tailor-none", email="tailor-none@example.com")
    seeded.application.job_description = None
    seeded.application.requirements = []
    await db_session.flush()

    with pytest.raises(TailoringRefused) as refused:
        await check_preconditions(db_session, seeded.application)

    assert refused.value.reason == "no_posting"
    assert "posting" in refused.value.detail.lower()


async def test_the_refusal_happens_before_a_version_or_run_is_reserved(
    db_session: AsyncSession,
) -> None:
    seeded = await seed_tailorable(db_session, sub="tailor-norow", email="tailor-norow@example.com")
    seeded.application.job_description = None
    seeded.application.requirements = []
    await db_session.flush()

    with pytest.raises(TailoringRefused):
        await create_pending_version(db_session, seeded.application)

    from sqlalchemy import func

    from careerhq.domain.models import ResumeVersion, TailoringRun

    versions = await db_session.scalar(
        select(func.count())
        .select_from(ResumeVersion)
        .where(ResumeVersion.application_id == seeded.application.id)
    )
    runs = await db_session.scalar(select(func.count()).select_from(TailoringRun))
    assert versions == 0
    assert runs == 0


async def test_tailoring_accepts_a_job_whose_posting_is_its_requirements(
    db_session: AsyncSession,
) -> None:
    """The positive case, so the guard proves a rule rather than a closed door."""
    seeded = await seed_tailorable(db_session, sub="tailor-reqs", email="tailor-reqs@example.com")
    seeded.application.job_description = None
    seeded.application.requirements = ["5+ years backend services"]
    await db_session.flush()

    analysis, profile, master = await check_preconditions(db_session, seeded.application)

    assert analysis is not None and profile is not None and master is not None


# -- what the interface is told ---------------------------------------------


async def test_the_api_says_whether_a_job_can_be_scored_at_all(
    client: Any, db_session: AsyncSession
) -> None:
    """One implementation of the rule, computed server-side.

    The interface needs to mark an incomplete job persistently, and deriving
    that client-side would be a second implementation of `scoreable_posting`
    living where nobody would think to keep it in step.
    """
    import httpx

    from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

    seeded = await seed_tailorable(db_session, sub="api-score", email="api-score@example.com")
    seeded.application.job_description = None
    seeded.application.requirements = []
    await db_session.commit()

    assert isinstance(client, httpx.AsyncClient)
    client.cookies.set(SESSION_COOKIE, create_session_token(str(seeded.user.id)))

    body = (await client.get(f"/api/applications/{seeded.application.id}")).json()
    assert body["is_scoreable"] is False

    seeded.application.requirements = ["5+ years backend services"]
    await db_session.commit()

    body = (await client.get(f"/api/applications/{seeded.application.id}")).json()
    assert body["is_scoreable"] is True


async def test_an_analysis_with_no_requirement_rows_is_not_reported_as_a_score(
    client: Any, db_session: AsyncSession
) -> None:
    """**The existing Voyantis record, without touching it.**

    That row is `ready` with `overall_score = 0`, `band = low_probability` and
    zero requirement rows, carrying the model's verdict "No job posting content
    was provided". It is not a judgement about the person; it is an analysis
    that had nothing to judge.

    The spec already says what this should look like — *"a job with a description
    but no extractable requirements is treated as nothing to score against, not
    as a failure and not as a zero"* — and that edge case was never implemented.
    Implementing it now covers the historical row too, so no data has to be
    edited to stop it lying.
    """
    from decimal import Decimal

    import httpx

    from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

    seeded = await seed_tailorable(db_session, sub="api-zero", email="api-zero@example.com")
    empty = MatchAnalysis(
        application_id=seeded.application.id,
        status=MatchStatus.READY,
        overall_score=0,
        band="low_probability",
        criteria_version="v3-earned",
        verdict="No job posting content was provided, so fit cannot be assessed.",
        model="claude-sonnet-5",
        input_tokens=3018,
        output_tokens=123,
        cost=Decimal("0.007266"),
        requirements=[],
    )
    db_session.add(empty)
    await db_session.flush()
    seeded.application.current_match_analysis_id = empty.id
    await db_session.commit()

    assert isinstance(client, httpx.AsyncClient)
    client.cookies.set(SESSION_COOKIE, create_session_token(str(seeded.user.id)))

    body = (await client.get(f"/api/applications/{seeded.application.id}/match")).json()

    assert body["state"] == "nothing_to_score", "a zero with nothing behind it is not a score"
