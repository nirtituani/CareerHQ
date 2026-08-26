"""Seed a state that can actually be tailored.

Tailoring has more preconditions than anything before it: an approved profile
with real content, a master resume, a recorded job with a description, and a
**completed, non-stale** match analysis. Rebuilding all of that per test file
would guarantee they drift apart, and the drift would be invisible — each file
would keep testing its own slightly different world.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    ResumeProfile,
    Skill,
    SummaryBlock,
    User,
    WorkExperience,
    normalize_status,
)

MASTER_RESUME_NAME = "Master Resume"


class Seeded:
    """Everything a tailoring test needs, by name rather than by tuple index."""

    def __init__(
        self,
        *,
        user: User,
        profile: ProfessionalProfile,
        master: ResumeProfile,
        application: Application,
        analysis: MatchAnalysis,
        bullet_ids: list[uuid.UUID],
        skill_ids: list[uuid.UUID],
        summary_id: uuid.UUID,
    ) -> None:
        self.user = user
        self.profile = profile
        self.master = master
        self.application = application
        self.analysis = analysis
        self.bullet_ids = bullet_ids
        self.skill_ids = skill_ids
        self.summary_id = summary_id


async def seed_tailorable(
    session: AsyncSession,
    *,
    sub: str = "google-tailoring",
    email: str = "tailoring@example.com",
    analysis_status: MatchStatus = MatchStatus.READY,
) -> Seeded:
    """A profile, a master, a job and a finished analysis.

    `email` defaults to an `example.com` address deliberately: pydantic's
    `EmailStr` rejects reserved TLDs like `.test`, and a scratch user seeded
    with one makes `/api/auth/me` return 500, which surfaces as a white-screen
    page and reads like an application bug.
    """
    user: User = await provision_user(session, {"sub": sub, "email": email, "name": "Tailor Test"})
    profile = await session.scalar(
        select(ProfessionalProfile).where(ProfessionalProfile.user_id == user.id)
    )
    assert profile is not None

    session.add(
        ContactInformation(profile_id=profile.id, full_name="Tailor Test", source="EXTRACTED")
    )
    summary = SummaryBlock(
        profile_id=profile.id,
        text="Backend engineer with six years on payment systems.",
        source="EXTRACTED",
    )
    session.add(summary)

    role = WorkExperience(
        profile_id=profile.id,
        company="Payments Co",
        title="Staff Engineer",
        start_date="2019",
        source="EXTRACTED",
    )
    session.add(role)
    await session.flush()

    bullets = [
        ExperienceBullet(
            experience_id=role.id,
            text="Led the payments platform team for six years.",
            source="EXTRACTED",
        ),
        ExperienceBullet(
            experience_id=role.id,
            text="Contributed to a migration onto containerised infrastructure.",
            source="EXTRACTED",
        ),
    ]
    skills = [
        Skill(profile_id=profile.id, name="Python", source="EXTRACTED"),
        Skill(profile_id=profile.id, name="PostgreSQL", source="EXTRACTED"),
    ]
    for row in (*bullets, *skills):
        session.add(row)

    # The master, created at import approval in production.
    master = ResumeProfile(profile_id=profile.id, name=MASTER_RESUME_NAME, is_master=True)
    session.add(master)

    company = Company(user_id=user.id, name="Acme", normalized_name="acme")
    session.add(company)
    await session.flush()

    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title="Senior Backend Engineer",
        status="Pre-Applied",
        normalized_status=normalize_status("Pre-Applied"),
        job_description="Build and operate payment services at scale. Kubernetes preferred.",
        requirements=["5+ years backend services", "Kubernetes in production"],
    )
    session.add(application)
    await session.flush()

    analysis = MatchAnalysis(
        application_id=application.id,
        status=analysis_status,
        overall_score=58 if analysis_status is MatchStatus.READY else None,
        band=MatchBand.MODERATE if analysis_status is MatchStatus.READY else None,
        criteria_version="v3-earned",
        model="anthropic/claude-sonnet-5",
        input_tokens=3000,
        output_tokens=1500,
        cost=Decimal("0.022"),
        requirements=[
            MatchRequirement(
                ordinal=0,
                text_="5+ years backend services",
                kind="must_have",
                importance=90,
                verdict="confirmed",
                evidence="Led the payments platform team for six years.",
            ),
            MatchRequirement(
                ordinal=1,
                text_="Kubernetes in production",
                kind="must_have",
                importance=40,
                verdict="unverified",
            ),
        ],
    )
    session.add(analysis)
    await session.flush()

    application.current_match_analysis_id = analysis.id
    await session.flush()

    return Seeded(
        user=user,
        profile=profile,
        master=master,
        application=application,
        analysis=analysis,
        bullet_ids=[b.id for b in bullets],
        skill_ids=[s.id for s in skills],
        summary_id=summary.id,
    )
