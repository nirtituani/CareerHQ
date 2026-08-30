"""Driving the benchmark through the shipping path, and refusing before it spends.

**The shipping path, never a reimplementation.** Every case goes through
`create_pending_version` and `run_tailoring` — the same use cases a user's click
goes through, with the same model mix (FR-010). A benchmark that reimplements the
pipeline measures the reimplementation, and evaluating a configuration that is
never deployed produces metrics describing a system nobody uses.

**Order of operations is the whole safety design** (FR-008, SC-011):

    resolve the set  →  fingerprint  →  project  →  REFUSE above the ceiling
                     →  run          →  record   →  write the result file

The refusal happens **before any billable call**, not as a reconciliation
afterwards, because a guard that only reconciles has already spent the money.

**The match analysis is authored, not generated, and that is a saving rather than
a shortcut.** A fixed benchmark needs fixed inputs: a model-generated analysis
would vary between passes and make the tailoring runs incomparable for reasons
that have nothing to do with what changed. It also removes one paid call per case.
The verdicts come from the case file's `expected_gaps`, which is an authored
property of the pairing — the same thing a human would assert when building the
case.

**It adds rows and modifies nothing** (FR-012). The eight versions, thirteen runs,
eight analyses and one submission already in the database cost $3.562567 and are
this project's only evaluation evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.evaluation.benchmark_set import BenchmarkCase, BenchmarkSet, ProfileState
from careerhq.application.evaluation.budget import SpendGuard, project_pass_cost
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import (
    Application,
    Company,
    ContactInformation,
    Education,
    ExperienceBullet,
    Language,
    MatchAnalysis,
    MatchBand,
    MatchRequirement,
    MatchStatus,
    ProfessionalProfile,
    ProfessionalTitle,
    ResumeProfile,
    Skill,
    SummaryBlock,
    User,
    WorkExperience,
    normalize_status,
)
from careerhq.domain.models.match import RequirementKind, RequirementVerdict, Shortfall
from careerhq.domain.models.profile import Certification, Project

#: Every benchmark user is provisioned under this prefix, on `example.com`.
#:
#: **Never a real address.** pydantic's `EmailStr` rejects reserved TLDs like
#: `.test`, and a scratch user seeded with one makes `/api/auth/me` return 500 —
#: which surfaces as a white-screen page and reads like an application bug.
BENCHMARK_EMAIL_DOMAIN = "example.com"
BENCHMARK_SUB_PREFIX = "benchmark|"


@dataclass(frozen=True, slots=True)
class SeededCase:
    """One case, materialised: a synthetic profile, a job, and an authored analysis."""

    case_id: str
    user_id: uuid.UUID
    profile_id: uuid.UUID
    application_id: uuid.UUID
    analysis_id: uuid.UUID


@dataclass
class PassPlan:
    """What a pass intends to do, and what it is authorised to spend."""

    benchmark_version: str
    cases: int
    static_arms: int
    judged: int
    projection: Decimal
    guard: SpendGuard
    benchmark_run_id: uuid.UUID = field(default_factory=uuid.uuid4)


def plan_pass(
    benchmark: BenchmarkSet,
    *,
    ceiling: Decimal,
    static_arms: int,
    judged: int | None = None,
    revising: bool = True,
) -> PassPlan:
    """Project the cost from what the pass will actually do, then authorise it.

    **Every count is derived, never assumed.** `cases` comes from the loaded set,
    `judged` defaults to the same, and `static_arms` is passed in. D3 approved
    twelve cases and five arms; a projection that hard-coded either would authorise
    a ceiling check for a run that was about to do something else.

    **Priced as though every run revises** (`revising=True`). That is the correct
    basis for a ceiling and the wrong one for a forecast: a ceiling sized on the
    average is a ceiling that is exceeded about half the time.

    Raises `CeilingExceededError` **before any billable call**.
    """
    cases = benchmark.case_count
    judged_count = cases if judged is None else judged
    projection = project_pass_cost(
        cases=cases, static_arms=static_arms, judged=judged_count, revising=revising
    )
    guard = SpendGuard(ceiling=ceiling)
    guard.authorise(projection)
    return PassPlan(
        benchmark_version=benchmark.version,
        cases=cases,
        static_arms=static_arms,
        judged=judged_count,
        projection=projection,
        guard=guard,
    )


async def _seed_profile(
    session: AsyncSession, state: ProfileState, *, suffix: str
) -> tuple[User, ProfessionalProfile]:
    """Materialise one synthetic profile state under a scratch user."""
    user: User = await provision_user(
        session,
        {
            "sub": f"{BENCHMARK_SUB_PREFIX}{state.state_id}|{suffix}",
            "email": f"{state.state_id}.{suffix}@{BENCHMARK_EMAIL_DOMAIN}",
            "name": state.full_name,
        },
    )
    profile = await session.scalar(
        select(ProfessionalProfile).where(ProfessionalProfile.user_id == user.id)
    )
    assert profile is not None

    session.add(
        ContactInformation(
            profile_id=profile.id,
            full_name=state.full_name,
            email=state.email,
            source="EXTRACTED",
        )
    )
    if state.headline:
        session.add(
            ProfessionalTitle(profile_id=profile.id, title=state.headline, source="EXTRACTED")
        )
    if state.summary:
        session.add(SummaryBlock(profile_id=profile.id, text=state.summary, source="EXTRACTED"))

    for ordinal, role in enumerate(state.experiences):
        experience = WorkExperience(
            profile_id=profile.id,
            company=role["company"],
            title=role.get("title"),
            location=role.get("location"),
            start_date=role.get("start_date"),
            end_date=role.get("end_date") or None,
            is_current=bool(role.get("is_current")),
            ordinal=role.get("ordinal", ordinal),
            source="EXTRACTED",
            bullets=[
                ExperienceBullet(text=text, ordinal=i, source="EXTRACTED")
                for i, text in enumerate(role.get("bullets", []))
            ],
        )
        session.add(experience)

    for skill in state.skills:
        session.add(
            Skill(
                profile_id=profile.id,
                name=skill["name"],
                category=skill.get("category"),
                source="EXTRACTED",
            )
        )
    for entry in state.education:
        session.add(Education(profile_id=profile.id, source="EXTRACTED", **entry))
    for language in state.languages:
        session.add(Language(profile_id=profile.id, source="EXTRACTED", **language))
    for certification in state.certifications:
        session.add(Certification(profile_id=profile.id, source="EXTRACTED", **certification))
    for project in state.projects:
        session.add(Project(profile_id=profile.id, source="EXTRACTED", **project))

    session.add(ResumeProfile(profile_id=profile.id, name="Master Resume", is_master=True))
    await session.flush()
    return user, profile


def _verdict_for(requirement: str, case: BenchmarkCase) -> tuple[RequirementVerdict, str, Any]:
    """The authored verdict for one requirement of one case.

    **Authored rather than judged**, so the benchmark's inputs are fixed. A model
    would produce a different analysis each pass, and two tailoring runs would then
    differ for a reason that has nothing to do with what changed.

    Every verdict except `unverified` must quote something (`ck_match_requirement_grounded`),
    **including `gap`, which quotes the shortfall** — a verdict carrying no evidence
    would let the absence be invented, which is the same fabrication pointed the
    other way.
    """
    if requirement in case.expected_gaps:
        return (
            RequirementVerdict.GAP,
            f"The profile records no experience matching {requirement!r}.",
            Shortfall.EVIDENCE,
        )
    return (
        RequirementVerdict.CONFIRMED,
        f"The profile's history supports {requirement!r}.",
        None,
    )


async def seed_case(
    session: AsyncSession, benchmark: BenchmarkSet, case: BenchmarkCase, *, suffix: str
) -> SeededCase:
    """One case, ready to tailor: profile, company, application and a READY analysis."""
    state = benchmark.profiles[case.profile_state]
    user, profile = await _seed_profile(session, state, suffix=f"{case.case_id}-{suffix}")

    # **User-owned, like every company row.** Ownership comes from the session and
    # never from a request; a benchmark is not an exception to that, and a
    # company with no owner would be the first row in the system without one.
    company = Company(
        user_id=user.id, name=case.company, normalized_name=case.company.strip().lower()
    )
    session.add(company)
    await session.flush()

    application = Application(
        user_id=user.id,
        company_id=company.id,
        job_title=case.role,
        job_description=case.posting_text,
        # **Both, and neither is optional here.** `scoreable_posting` refuses a row
        # whose `requirements` is NULL outright — that marks a pre-slice-004 row
        # whose description holds a joined requirements list rather than a posting.
        # A benchmark case seeded without them is refused by the shipping path
        # before any model is reached, which is the gate working correctly.
        requirements=list(case.requirements),
        status="Applied",
        normalized_status=normalize_status("Applied"),
    )
    session.add(application)
    await session.flush()

    covered = len([r for r in case.requirements if r not in case.expected_gaps])
    score = round(100 * covered / max(1, len(case.requirements)))
    analysis = MatchAnalysis(
        application_id=application.id,
        status=MatchStatus.READY,
        overall_score=score,
        band=(
            MatchBand.STRONG
            if score >= 80
            else MatchBand.MODERATE
            if score >= 60
            else MatchBand.STRETCH
        ),
        # **A criteria version of its own, and NOT one of the real rubric's.**
        # `criteria_version` is what makes calibration across analyses meaningful;
        # labelling authored benchmark scores as though a model had produced them
        # under `v3-earned` would silently mix two populations in exactly the
        # measurement (FR-018) that exists to keep them apart.
        criteria_version="benchmark-authored-v1",
        verdict=f"Authored benchmark analysis for {case.case_id}.",
        requirements=[
            MatchRequirement(
                ordinal=i,
                text_=requirement,
                kind=(
                    RequirementKind.MUST_HAVE
                    if requirement in case.must_have
                    else RequirementKind.PREFERRED
                ),
                importance=70 if requirement in case.must_have else 40,
                verdict=verdict,
                evidence=evidence,
                shortfall=shortfall,
            )
            for i, requirement in enumerate(case.requirements)
            for verdict, evidence, shortfall in [_verdict_for(requirement, case)]
        ],
    )
    session.add(analysis)
    await session.flush()

    application.current_match_analysis_id = analysis.id
    await session.flush()

    return SeededCase(
        case_id=case.case_id,
        user_id=user.id,
        profile_id=profile.id,
        application_id=application.id,
        analysis_id=analysis.id,
    )


__all__ = [
    "BENCHMARK_EMAIL_DOMAIN",
    "BENCHMARK_SUB_PREFIX",
    "PassPlan",
    "SeededCase",
    "plan_pass",
    "render_version",
    "seed_case",
    "version_items",
]


def render_version(items: list[dict[str, Any]]) -> str:
    """The tailored résumé as text, from the version's own rows.

    **What the judge is shown.** Built from `final_text` — the column the export
    renders — rather than re-deriving it from `decision` plus the other two, because
    deriving it means every reader re-implements the rule and the reader that gets
    it wrong is the document somebody sends.

    Excluded items are omitted: a résumé is what it contains.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if not item.get("included", True):
            continue
        groups.setdefault(str(item["source_kind"]), []).append(item)

    order = [
        "summary",
        "experience_bullet",
        "skill",
        "project",
        "education",
        "certification",
        "language",
    ]
    lines: list[str] = []
    for kind in order:
        rows = groups.get(kind)
        if not rows:
            continue
        lines.append(f"\n{kind.replace('_', ' ').upper()}")
        current_role: str | None = None
        for row in sorted(rows, key=lambda r: (r.get("role_ordinal") or 0, r.get("position") or 0)):
            role = row.get("role_employer")
            if role and role != current_role:
                current_role = str(role)
                dates = " - ".join(
                    str(d) for d in (row.get("role_start_date"), row.get("role_end_date")) if d
                )
                lines.append(f"  {row.get('role_title')} at {role} ({dates})")
            prefix = "    - " if kind == "experience_bullet" else "  - "
            lines.append(f"{prefix}{row['final_text']}")
    return "\n".join(lines).strip()


async def version_items(session: AsyncSession, version_id: uuid.UUID) -> list[dict[str, Any]]:
    """The version's items as plain dicts, ordered as the document orders them."""
    from careerhq.domain.models import ResumeVersionItem

    rows = (
        await session.scalars(
            sa.select(ResumeVersionItem)
            .where(ResumeVersionItem.resume_version_id == version_id)
            .order_by(ResumeVersionItem.position)
        )
    ).all()
    return [
        {
            "source_kind": r.source_kind,
            "source_item_id": str(r.source_item_id) if r.source_item_id else None,
            "position": r.position,
            "role_employer": r.role_employer,
            "role_title": r.role_title,
            "role_start_date": r.role_start_date,
            "role_end_date": r.role_end_date,
            "role_ordinal": r.role_ordinal,
            "original_text": r.original_text,
            "proposed_text": r.proposed_text,
            "final_text": r.final_text,
            "included": r.included,
        }
        for r in rows
    ]
