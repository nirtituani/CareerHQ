"""Professional Profile routes.

There is deliberately no ``GET /api/profile/{id}``. The profile is always
resolved from the session, so cross-user access is impossible by construction
rather than by a permission check that a future endpoint could omit
(FR-015, SC-005).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute

from careerhq.api.deps import DbSession, get_current_profile
from careerhq.domain.models import (
    Certification,
    ContactInformation,
    Education,
    Language,
    ProfessionalProfile,
    ProfessionalTitle,
    Project,
    ResumeProfile,
    Skill,
    SummaryBlock,
    WorkExperience,
)
from careerhq.domain.schemas import ProfileOut

router = APIRouter(tags=["profile"])

CurrentProfile = Annotated[ProfessionalProfile, Depends(get_current_profile)]


@router.get("/profile", response_model=ProfileOut, summary="The signed-in user's profile")
async def read_profile(profile: CurrentProfile) -> ProfileOut:
    """Return the profile. Empty in this slice; later slices populate it."""
    return ProfileOut.model_validate(profile)


@router.get("/profile/content", summary="Everything the profile holds")
async def read_profile_content(profile: CurrentProfile, session: DbSession) -> dict[str, object]:
    """The structured profile, with provenance on every item.

    `source` travels to the interface because FR-004 requires user-verified
    facts to stay distinguishable from unverified extraction **after** approval,
    not only during review. Dropping it here would make the profile a flat set
    of equally-trusted claims with no record of which ones a human checked.
    """

    async def _all[M](model: type[M], owner: InstrumentedAttribute[uuid.UUID]) -> list[M]:
        """Rows of `model` belonging to this profile.

        The owning column is passed explicitly rather than reached for on the
        model, so the element type is still inferrable — a helper that takes
        only `type` erases it and turns every field access below into `object`.
        """
        return list(await session.scalars(select(model).where(owner == profile.id)))

    roles = await _all(WorkExperience, WorkExperience.profile_id)

    return {
        "contact": [
            {
                "id": str(c.id),
                "full_name": c.full_name,
                "email": c.email,
                "phone": c.phone,
                "location": c.location,
                "source": c.source,
            }
            for c in await _all(ContactInformation, ContactInformation.profile_id)
        ],
        "titles": [
            {"id": str(t.id), "title": t.title, "source": t.source}
            for t in await _all(ProfessionalTitle, ProfessionalTitle.profile_id)
        ],
        "summaries": [
            {"id": str(s.id), "text": s.text, "source": s.source}
            for s in await _all(SummaryBlock, SummaryBlock.profile_id)
        ],
        "work_experience": [
            {
                "id": str(r.id),
                "company": r.company,
                "title": r.title,
                "location": r.location,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "is_current": r.is_current,
                "source": r.source,
                "bullets": [
                    {"id": str(b.id), "text": b.text, "source": b.source} for b in r.bullets
                ],
            }
            for r in roles
        ],
        "skills": [
            {"id": str(s.id), "name": s.name, "category": s.category, "source": s.source}
            for s in await _all(Skill, Skill.profile_id)
        ],
        "projects": [
            {"id": str(p.id), "name": p.name, "description": p.description, "source": p.source}
            for p in await _all(Project, Project.profile_id)
        ],
        "education": [
            {
                "id": str(e.id),
                "institution": e.institution,
                "qualification": e.qualification,
                "field_of_study": e.field_of_study,
                "end_date": e.end_date,
                "source": e.source,
            }
            for e in await _all(Education, Education.profile_id)
        ],
        "certifications": [
            {"id": str(c.id), "name": c.name, "issuer": c.issuer, "source": c.source}
            for c in await _all(Certification, Certification.profile_id)
        ],
        "languages": [
            {
                "id": str(lang.id),
                "name": lang.name,
                "proficiency": lang.proficiency,
                "source": lang.source,
            }
            for lang in await _all(Language, Language.profile_id)
        ],
        "master_resume": (
            {"id": str(m.id), "name": m.name}
            if (
                m := await session.scalar(
                    select(ResumeProfile).where(
                        ResumeProfile.profile_id == profile.id, ResumeProfile.is_master
                    )
                )
            )
            else None
        ),
    }
