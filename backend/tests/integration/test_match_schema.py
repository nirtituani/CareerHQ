"""The constraints that make match analysis honest at the table level.

Every assertion here is about something being **rejected**. That makes them the
tests most likely to pass for the wrong reason — slice 003 lost a release
blocker to exactly this, when `create_all` skipped an existing table and T067
passed against a schema that still carried the column it was asserting the
absence of. `conftest.py` drops before creating now (T003), and each constraint
below was watched rejecting a row before it was trusted.

The grounding constraint is the important one. Read it as an equivalence in both
directions: every verdict except `unverified` must quote the profile, including
`gap`, which has to point at the text showing the shortfall. A model that cannot
quote anything does not get to say the person falls short.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.match_criteria import CRITERIA_VERSION
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    Company,
    MatchAnalysis,
    MatchRequirement,
    MatchStatus,
    RequirementKind,
    RequirementVerdict,
    Shortfall,
    User,
    normalize_status,
)

CLAIMS = {"sub": "google-match", "email": "match@example.com", "name": "Match Tester"}


async def _application(session: AsyncSession) -> Application:
    user: User = await provision_user(session, CLAIMS)
    company = Company(user_id=user.id, name="Acme", normalized_name="acme")
    session.add(company)
    await session.flush()

    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Senior Backend Engineer",
        status="Applied",
        normalized_status=normalize_status("Applied"),
        job_description="The whole posting.",
        requirements=["5+ years of Python"],
    )
    session.add(application)
    await session.flush()
    return application


async def _analysis(session: AsyncSession, application: Application) -> MatchAnalysis:
    analysis = MatchAnalysis(
        application_id=application.id,
        status=MatchStatus.PENDING,
        criteria_version=CRITERIA_VERSION,
    )
    session.add(analysis)
    await session.flush()
    return analysis


@pytest.mark.parametrize(
    "verdict",
    [
        RequirementVerdict.CONFIRMED,
        RequirementVerdict.PARTIAL,
        RequirementVerdict.TRANSFERABLE,
        RequirementVerdict.GAP,
    ],
)
async def test_a_grounded_verdict_cannot_be_stored_without_evidence(
    db_session: AsyncSession, verdict: RequirementVerdict
) -> None:
    """AI-008 at the table level, for every verdict that makes a claim.

    `gap` is in this list deliberately. *You fall short of this* is a claim
    about the person, and it needs the profile text that shows it just as much
    as *you have this* does. An earlier draft let the negative verdict go
    unevidenced, which turned a silent profile into a confident "you do not have
    this" — inventing an absence, which is the same fabrication as inventing
    experience (research.md R9/D1).
    """
    application = await _application(db_session)
    analysis = await _analysis(db_session, application)

    db_session.add(
        MatchRequirement(
            analysis_id=analysis.id,
            ordinal=0,
            text_="5+ years of Python",
            kind=RequirementKind.MUST_HAVE,
            verdict=verdict,
            shortfall=None if verdict is RequirementVerdict.CONFIRMED else Shortfall.EVIDENCE,
            evidence=None,
        )
    )

    with pytest.raises(IntegrityError, match="ck_match_requirement_grounded"):
        await db_session.flush()
    await db_session.rollback()


async def test_unverified_cannot_smuggle_in_evidence(db_session: AsyncSession) -> None:
    """The rule is an equivalence, not an implication.

    `unverified` means the profile says nothing either way. Attaching a quote to
    it would be asserting something after all, under the one label that promises
    not to.
    """
    application = await _application(db_session)
    analysis = await _analysis(db_session, application)

    db_session.add(
        MatchRequirement(
            analysis_id=analysis.id,
            ordinal=0,
            text_="Kubernetes in production",
            kind=RequirementKind.MUST_HAVE,
            verdict=RequirementVerdict.UNVERIFIED,
            shortfall=Shortfall.EVIDENCE,
            evidence="Something the profile does not actually say.",
        )
    )

    with pytest.raises(IntegrityError, match="ck_match_requirement_grounded"):
        await db_session.flush()
    await db_session.rollback()


async def test_a_confirmed_requirement_cannot_carry_a_shortfall(
    db_session: AsyncSession,
) -> None:
    """A reason for falling short is meaningless on something the profile confirms."""
    application = await _application(db_session)
    analysis = await _analysis(db_session, application)

    db_session.add(
        MatchRequirement(
            analysis_id=analysis.id,
            ordinal=0,
            text_="5+ years of Python",
            kind=RequirementKind.MUST_HAVE,
            verdict=RequirementVerdict.CONFIRMED,
            shortfall=Shortfall.WORDING,
            evidence="Six years on the payments platform.",
        )
    )

    with pytest.raises(IntegrityError, match="ck_match_requirement_shortfall"):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.parametrize("importance", [-1, 101])
async def test_importance_stays_inside_the_scale(db_session: AsyncSession, importance: int) -> None:
    """The band rule reads this column, so a value outside 0-100 would make the
    cap threshold meaningless in a way nothing else would notice."""
    application = await _application(db_session)
    analysis = await _analysis(db_session, application)

    db_session.add(
        MatchRequirement(
            analysis_id=analysis.id,
            ordinal=0,
            text_="5+ years of Python",
            kind=RequirementKind.MUST_HAVE,
            importance=importance,
            verdict=RequirementVerdict.CONFIRMED,
            shortfall=None,
            evidence="Six years on the payments platform.",
        )
    )

    with pytest.raises(IntegrityError, match="ck_match_requirement_importance"):
        await db_session.flush()
    await db_session.rollback()


async def test_only_one_analysis_may_be_pending_per_application(
    db_session: AsyncSession,
) -> None:
    """FR-007, enforced where it cannot be raced.

    An application-level "is one already running?" check loses to two clicks
    arriving together. A partial unique index does not.
    """
    application = await _application(db_session)
    await _analysis(db_session, application)

    db_session.add(
        MatchAnalysis(
            application_id=application.id,
            status=MatchStatus.PENDING,
            criteria_version=CRITERIA_VERSION,
        )
    )

    with pytest.raises(IntegrityError, match="uq_match_analysis_one_pending_per_application"):
        await db_session.flush()
    await db_session.rollback()


async def test_a_finished_analysis_does_not_block_a_new_run(db_session: AsyncSession) -> None:
    """The index is partial on purpose — history must not block a re-run.

    Without the `WHERE status = 'pending'` clause this would fail, and every
    application would be scoreable exactly once. That is the failure mode a
    plain unique index would introduce, so it is asserted rather than assumed.
    """
    application = await _application(db_session)
    first = await _analysis(db_session, application)
    first.status = MatchStatus.READY
    first.overall_score = 84
    await db_session.flush()

    db_session.add(
        MatchAnalysis(
            application_id=application.id,
            status=MatchStatus.PENDING,
            criteria_version=CRITERIA_VERSION,
        )
    )
    await db_session.flush()  # must not raise

    assert first.id is not None
