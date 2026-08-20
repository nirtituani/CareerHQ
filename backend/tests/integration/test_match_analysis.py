"""Running one match analysis (User Story 1).

The seam is overridden throughout — no test here makes a provider call (FR-027).

Three of these guard things that would be invisible in production if they broke.
A profile silently mutated by an analysis, an `imported_match_rating` quietly
overwritten, and a legacy row scored against a requirements list while the
prompt claims to read a posting: none of them raise, none of them look wrong,
and the last produces a number that reads as entirely normal.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.analyze_match import create_pending_analysis, run_analysis
from careerhq.application.match_criteria import CRITERIA_VERSION
from careerhq.application.ports import Completion, Usage
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    Company,
    ContactInformation,
    ExperienceBullet,
    MatchAnalysis,
    MatchBand,
    MatchRequirement,
    MatchStatus,
    ProfessionalProfile,
    RequirementVerdict,
    User,
    WorkExperience,
    normalize_status,
)

CLAIMS = {"sub": "google-analysis", "email": "analysis@example.com", "name": "Analysis Tester"}

_JUDGEMENT = {
    "direct": 88,
    "transferable": 82,
    "adjacent": 75,
    "impact": 80,
    "verdict": "Strong backend fit; Kubernetes is unproven rather than absent.",
    "requirements": [
        {
            "text": "5+ years building production backend services",
            "kind": "must_have",
            "importance": 90,
            "verdict": "confirmed",
            "shortfall": None,
            "evidence": "Led the payments platform team for six years.",
        },
        {
            "text": "Kubernetes in production",
            "kind": "must_have",
            # Below CAP_IMPORTANCE, so this fixture stays a `strong` match and
            # the banding assertions test banding rather than the cap.
            "importance": 40,
            "verdict": "unverified",
            # No shortfall: a silent profile cannot say *why* it is silent.
            "shortfall": None,
            "evidence": None,
        },
    ],
}


class _Stub:
    """Returns a fixed judgement, and records what it was asked."""

    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload if payload is not None else _JUDGEMENT
        self.prompt: str | None = None
        self.task: str | None = None

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        self.task = task
        self.prompt = prompt
        return Completion(
            value=schema.model_validate(self.payload),
            usage=Usage(
                model="anthropic/claude-sonnet-5",
                input_tokens=3420,
                output_tokens=1487,
                cost=Decimal("0.022110"),
            ),
        )


async def _setup(
    session: AsyncSession, *, requirements: list[str] | None = None
) -> tuple[User, Application]:
    user: User = await provision_user(session, CLAIMS)
    # `provision_user` creates the profile — exactly one per user, Principle I.
    # Adding a second here is what the UNIQUE constraint is for.
    profile = await session.scalar(
        select(ProfessionalProfile).where(ProfessionalProfile.user_id == user.id)
    )
    assert profile is not None

    session.add(
        ContactInformation(profile_id=profile.id, full_name="Analysis Tester", source="EXTRACTED")
    )
    role = WorkExperience(
        profile_id=profile.id,
        company="Payments Co",
        title="Staff Engineer",
        start_date="2019",
        source="EXTRACTED",
    )
    session.add(role)
    await session.flush()
    session.add(
        ExperienceBullet(
            experience_id=role.id,
            text="Led the payments platform team for six years.",
            source="EXTRACTED",
        )
    )

    company = Company(user_id=user.id, name="Acme", normalized_name="acme")
    session.add(company)
    await session.flush()

    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Senior Backend Engineer",
        status="Applied",
        normalized_status=normalize_status("Applied"),
        job_description="The whole posting, including scale and domain signals.",
        requirements=(
            ["5+ years building production backend services", "Kubernetes in production"]
            if requirements is None
            else requirements
        ),
    )
    session.add(application)
    await session.flush()
    return user, application


async def test_a_successful_run_records_the_result_and_what_it_cost(
    db_session: AsyncSession,
) -> None:
    """FR-017, Constitution V. Usage lands in the same transaction as the work.

    Enum columns are compared with `==` rather than `is`: they are stored as
    `String(16)`, as `NormalizedStatus` already is, so a value read back from
    the database is a plain `str`. `StrEnum` compares equal to its value, which
    is what makes that safe — and `is` would silently never match.
    """
    _, application = await _setup(db_session)
    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None

    stub = _Stub()
    await run_analysis(db_session, analysis_id=analysis.id, completion=stub)
    await db_session.refresh(analysis)

    assert stub.task == "match_analysis"
    assert analysis.status == MatchStatus.READY
    # 88*.4 + 82*.3 + 75*.2 + 80*.1 = 82.8 -> 83
    assert analysis.overall_score == 83
    assert analysis.band == MatchBand.STRONG
    assert analysis.verdict is not None
    assert analysis.criteria_version == CRITERIA_VERSION
    assert analysis.completed_at is not None

    assert analysis.model == "anthropic/claude-sonnet-5"
    assert analysis.input_tokens == 3420
    assert analysis.output_tokens == 1487
    assert analysis.cost == Decimal("0.022110")
    assert analysis.is_fixture is False


async def test_the_four_dimensions_are_kept_not_just_their_total(
    db_session: AsyncSession,
) -> None:
    """The score is a weighted sum, and the parts are what explain it.

    They were computed, used, and thrown away — so the interface could show a
    number with no way to say where it came from. That is precisely the
    "pseudo-scientific fit percentage" one of the rubric sources warns against:
    a bare total implies a measurement nobody can audit. Kept, the total becomes
    arithmetic a person can check against stated judgements.
    """
    _, application = await _setup(db_session)
    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None

    await run_analysis(db_session, analysis_id=analysis.id, completion=_Stub())
    await db_session.refresh(analysis)

    assert analysis.direct == 88
    assert analysis.transferable == 82
    assert analysis.adjacent == 75
    assert analysis.impact == 80

    # And they still add up to what was stored.
    assert analysis.overall_score == round(88 * 0.4 + 82 * 0.3 + 75 * 0.2 + 80 * 0.1)


async def test_the_pointer_advances_only_on_success(db_session: AsyncSession) -> None:
    """FR-015, invariant I3."""
    _, application = await _setup(db_session)
    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None
    assert application.current_match_analysis_id is None

    await run_analysis(db_session, analysis_id=analysis.id, completion=_Stub())
    await db_session.refresh(application)

    assert application.current_match_analysis_id == analysis.id


async def test_requirement_rows_keep_their_order_and_their_grounding(
    db_session: AsyncSession,
) -> None:
    """One row per requirement, in the order the posting stated them."""
    _, application = await _setup(db_session)
    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None

    await run_analysis(db_session, analysis_id=analysis.id, completion=_Stub())

    rows = list(
        await db_session.scalars(
            select(MatchRequirement)
            .where(MatchRequirement.analysis_id == analysis.id)
            .order_by(MatchRequirement.ordinal)
        )
    )

    assert [r.ordinal for r in rows] == [0, 1]
    assert rows[0].verdict == RequirementVerdict.CONFIRMED
    assert rows[0].evidence == "Led the payments platform team for six years."
    assert rows[0].shortfall is None

    # The silent one is unverified, not a gap, and carries nothing.
    assert rows[1].verdict == RequirementVerdict.UNVERIFIED
    assert rows[1].evidence is None


async def test_an_invalid_completion_fails_the_analysis_and_leaves_the_job_alone(
    db_session: AsyncSession,
) -> None:
    """Contract T4, FR-026.

    The completion claims a match it cannot quote. O2 makes that an extraction
    failure rather than something to patch up, so the analysis records `failed`
    and the application stays exactly as usable as it was.
    """
    _, application = await _setup(db_session)
    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None

    ungrounded = {
        **_JUDGEMENT,
        "requirements": [
            {
                "text": "5+ years building production backend services",
                "kind": "must_have",
                "importance": 90,
                "verdict": "confirmed",
                "shortfall": None,
                "evidence": None,
            }
        ],
    }
    await run_analysis(db_session, analysis_id=analysis.id, completion=_Stub(ungrounded))
    await db_session.refresh(analysis)
    await db_session.refresh(application)

    assert analysis.status == MatchStatus.FAILED
    assert analysis.error
    assert analysis.overall_score is None
    assert analysis.completed_at is not None

    # The job is untouched and still usable.
    assert application.current_match_analysis_id is None
    assert application.job_title == "Senior Backend Engineer"
    assert application.job_description


async def test_an_analysis_writes_nothing_to_the_profile(db_session: AsyncSession) -> None:
    """Contract T7, FR-012, invariant I6. It observes; it does not own."""
    user, application = await _setup(db_session)
    profile = await db_session.scalar(
        select(ProfessionalProfile).where(ProfessionalProfile.user_id == user.id)
    )
    assert profile is not None

    before = {
        "bullets": sorted(
            b.text
            for b in await db_session.scalars(
                select(ExperienceBullet)
                .join(WorkExperience)
                .where(WorkExperience.profile_id == profile.id)
            )
        ),
        "contacts": sorted(
            c.full_name or ""
            for c in await db_session.scalars(
                select(ContactInformation).where(ContactInformation.profile_id == profile.id)
            )
        ),
        "updated_at": profile.updated_at,
    }

    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None
    await run_analysis(db_session, analysis_id=analysis.id, completion=_Stub())
    await db_session.refresh(profile)

    after = {
        "bullets": sorted(
            b.text
            for b in await db_session.scalars(
                select(ExperienceBullet)
                .join(WorkExperience)
                .where(WorkExperience.profile_id == profile.id)
            )
        ),
        "contacts": sorted(
            c.full_name or ""
            for c in await db_session.scalars(
                select(ContactInformation).where(ContactInformation.profile_id == profile.id)
            )
        ),
        "updated_at": profile.updated_at,
    }

    assert before == after


async def test_the_users_own_rating_is_never_overwritten(db_session: AsyncSession) -> None:
    """FR-013.

    What the person thought and what the system computed are two facts. One
    field for both would drift, exactly as the source app's `rejected` flag
    drifted from its status.
    """
    _, application = await _setup(db_session)
    application.imported_match_rating = 4
    await db_session.flush()

    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None
    await run_analysis(db_session, analysis_id=analysis.id, completion=_Stub())
    await db_session.refresh(application)

    assert application.imported_match_rating == 4
    assert application.current_match_analysis_id is not None


async def test_a_legacy_row_is_never_scored(db_session: AsyncSession) -> None:
    """Invariant I7, research.md R1.

    `requirements IS NULL` means no posting was ever captured — `job_description`
    holds a joined requirements list. Scoring it would compare the profile
    against that list while the prompt claims to read a whole posting, silently
    reinstating requirements-only scoring. **The resulting number would look
    entirely normal**, which is why this is a test rather than a code comment.
    """
    _, application = await _setup(db_session, requirements=[])
    application.requirements = None
    await db_session.flush()

    assert await create_pending_analysis(db_session, application) is None
    assert (
        await db_session.scalar(
            select(MatchAnalysis).where(MatchAnalysis.application_id == application.id)
        )
    ) is None


async def test_a_posting_that_yielded_no_requirements_is_not_scored_either(
    db_session: AsyncSession,
) -> None:
    """FR-006. Not an error, and not a zero.

    An analysis against an empty requirement list returns a number with nothing
    behind it, which is worse than no number.
    """
    _, application = await _setup(db_session, requirements=[])

    assert await create_pending_analysis(db_session, application) is None


async def test_an_analysis_whose_application_vanished_is_discarded(
    db_session: AsyncSession,
) -> None:
    """A fire-and-forget task must not raise into nowhere when it lands late."""
    _, application = await _setup(db_session)
    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None

    missing = uuid.uuid4()
    await run_analysis(db_session, analysis_id=missing, completion=_Stub())  # must not raise


async def test_a_fresh_session_still_recognises_a_pending_analysis(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The background task loads the row in its **own** session. So must this.

    Every other test here calls `run_analysis` with the session that created the
    row, so SQLAlchemy's identity map hands back the in-memory object whose
    `status` is still a Python enum member. Production never does that: the
    request's session is closed by the time the background task runs, so it
    loads from the database and gets a plain `str` — these are `String(16)`
    columns.

    That divergence hid a total failure. The guard read `status is not
    MatchStatus.PENDING`, which is always true for a string, so `run_analysis`
    returned immediately and every real analysis sat `pending` forever. Nothing
    raised, nothing logged, the suite was green, and the deployed feature did
    nothing at all.

    Reproduced here with a second session, which is the only way to see it.
    """
    _, application = await _setup(db_session)
    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None
    analysis_id = analysis.id
    await db_session.commit()

    async with session_factory() as fresh:
        await run_analysis(fresh, analysis_id=analysis_id, completion=_Stub())
        await fresh.commit()

    await db_session.refresh(analysis)
    assert analysis.status == MatchStatus.READY
    assert analysis.overall_score == 83


async def test_the_prompt_carries_the_whole_posting_and_the_whole_profile(
    db_session: AsyncSession,
) -> None:
    """P1. Nothing is retrieved, sampled, or summarised first (research.md R4).

    The feature's central question is *which requirements do I lack*, and that
    can only be answered from the entire profile. A retrieval miss would invent
    a gap — silently, in the one feature where a false negative is the headline.
    """
    _, application = await _setup(db_session)
    analysis = await create_pending_analysis(db_session, application)
    assert analysis is not None

    stub = _Stub()
    await run_analysis(db_session, analysis_id=analysis.id, completion=stub)

    assert stub.prompt is not None
    assert "The whole posting, including scale and domain signals." in stub.prompt
    assert "Led the payments platform team for six years." in stub.prompt
    assert "Payments Co" in stub.prompt
