"""Professional Profile routes.

There is deliberately no ``GET /api/profile/{id}``. The profile is always
resolved from the session, so cross-user access is impossible by construction
rather than by a permission check that a future endpoint could omit
(FR-015, SC-005).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.orm import InstrumentedAttribute

from careerhq.api.deps import DbSession, get_current_profile
from careerhq.domain.models import (
    Certification,
    ContactInformation,
    Education,
    ExperienceBullet,
    Language,
    MilitaryService,
    ProfessionalProfile,
    ProfessionalTitle,
    Project,
    ResumeProfile,
    Skill,
    Source,
    SummaryBlock,
    VolunteerExperience,
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
                # Stored as newline-separated text; returned as a list so the
                # interface does not have to know that.
                "links": [line for line in (c.links or "").splitlines() if line.strip()],
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
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "url": p.url,
                "source": p.source,
            }
            for p in await _all(Project, Project.profile_id)
        ],
        "education": [
            {
                "id": str(e.id),
                "institution": e.institution,
                "qualification": e.qualification,
                "field_of_study": e.field_of_study,
                "start_date": e.start_date,
                "end_date": e.end_date,
                "grade": e.grade,
                "source": e.source,
            }
            for e in await _all(Education, Education.profile_id)
        ],
        "certifications": [
            {
                "id": str(c.id),
                "name": c.name,
                "issuer": c.issuer,
                "year": c.year,
                "source": c.source,
            }
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
        "military_service": [
            {
                "id": str(m.id),
                "branch": m.branch,
                "role": m.role,
                "start_date": m.start_date,
                "end_date": m.end_date,
                "source": m.source,
            }
            for m in await _all(MilitaryService, MilitaryService.profile_id)
        ],
        "volunteering": [
            {
                "id": str(v.id),
                "organisation": v.organisation,
                "role": v.role,
                "start_date": v.start_date,
                "end_date": v.end_date,
                "source": v.source,
            }
            for v in await _all(VolunteerExperience, VolunteerExperience.profile_id)
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


# ---------------------------------------------------------------------------
# Removing things from the profile
# ---------------------------------------------------------------------------
#
# Until this existed, anything that reached the profile was permanent. A badly
# parsed role or a skills block that came through wrong could be discarded
# during review, but never afterwards — and the review is exactly where a
# mistake is easiest to miss, because there are dozens of items and no
# consequence has been felt yet.
#
# Deletion is permanent and it is meant to be: the profile holds current
# professional knowledge, not history. What *is* history — which import a fact
# arrived in — lives on the ImportedResume record and is untouched by this.


@dataclass(frozen=True)
class _Removable:
    """A profile-owned entity, with the columns needed to delete one safely."""

    model: Any
    owner: InstrumentedAttribute[uuid.UUID]
    identity: InstrumentedAttribute[uuid.UUID]


#: Sections a user may clear. Keyed by the same names the review screen uses, so
#: one vocabulary covers extraction, review and the profile.
REMOVABLE: dict[str, _Removable] = {
    "contact": _Removable(ContactInformation, ContactInformation.profile_id, ContactInformation.id),
    "title": _Removable(ProfessionalTitle, ProfessionalTitle.profile_id, ProfessionalTitle.id),
    "summary": _Removable(SummaryBlock, SummaryBlock.profile_id, SummaryBlock.id),
    "work_experience": _Removable(WorkExperience, WorkExperience.profile_id, WorkExperience.id),
    "skill": _Removable(Skill, Skill.profile_id, Skill.id),
    "project": _Removable(Project, Project.profile_id, Project.id),
    "education": _Removable(Education, Education.profile_id, Education.id),
    "certification": _Removable(Certification, Certification.profile_id, Certification.id),
    "language": _Removable(Language, Language.profile_id, Language.id),
    "military_service": _Removable(MilitaryService, MilitaryService.profile_id, MilitaryService.id),
    "volunteer": _Removable(
        VolunteerExperience, VolunteerExperience.profile_id, VolunteerExperience.id
    ),
}


def _removable(kind: str) -> _Removable:
    entry = REMOVABLE.get(kind)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"There is no {kind!r} section."
        )
    return entry


#: Fields a user may change, per kind. A whitelist rather than "any column the
#: request names": without it a PATCH could set `profile_id` and move a row to
#: someone else's profile, or rewrite `source` and forge the provenance that
#: decides what a later import may overwrite.
EDITABLE_COLUMNS: dict[str, frozenset[str]] = {
    "contact": frozenset({"full_name", "email", "phone", "location"}),
    "title": frozenset({"title"}),
    "summary": frozenset({"text"}),
    "work_experience": frozenset(
        {"company", "title", "location", "start_date", "end_date", "is_current"}
    ),
    "bullet": frozenset({"text"}),
    "skill": frozenset({"name", "category"}),
    "project": frozenset({"name", "description", "url"}),
    "education": frozenset(
        {"institution", "qualification", "field_of_study", "start_date", "end_date", "grade"}
    ),
    "certification": frozenset({"name", "issuer", "year"}),
    "language": frozenset({"name", "proficiency"}),
    "military_service": frozenset({"branch", "role", "start_date", "end_date", "details"}),
    "volunteer": frozenset({"organisation", "role", "start_date", "end_date", "description"}),
}


@router.patch("/profile/{kind}/{item_id}", summary="Correct one item in the profile")
async def edit_item(
    kind: str,
    item_id: uuid.UUID,
    body: dict[str, Any],
    profile: CurrentProfile,
    session: DbSession,
) -> dict[str, Any]:
    """Change a fact already in the profile, and mark it as verified.

    Review lets a user correct something before approving it; this lets them
    correct it afterwards. Without it, "correction" existed only inside a window
    that closed — a one-character typo in a job title cost the whole entry,
    because deleting was the only repair available.

    Saving sets `source` to `user_corrected`, which is the same state a review
    correction produces and carries the same consequence: a later import will
    not overwrite it.
    """
    allowed = EDITABLE_COLUMNS.get(kind)
    if allowed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"There is no {kind!r} section."
        )

    if kind == "bullet":
        item = await session.scalar(
            select(ExperienceBullet).where(
                ExperienceBullet.id == item_id,
                ExperienceBullet.experience_id.in_(
                    select(WorkExperience.id).where(WorkExperience.profile_id == profile.id)
                ),
            )
        )
    else:
        entry = _removable(kind)
        item = await session.scalar(
            select(entry.model).where(entry.owner == profile.id, entry.identity == item_id)
        )

    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    for field, value in body.items():
        if field not in allowed:
            # Ignored rather than rejected: an interface sending a field this
            # kind does not have is a bug to fix, not a reason to lose the rest
            # of a user's correction.
            continue
        setattr(item, field, value)

    item.source = Source.USER_CORRECTED
    await session.commit()
    return {"id": str(item_id), "source": item.source}


@router.delete(
    "/profile/content",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear everything in the profile",
)
async def clear_profile(profile: CurrentProfile, session: DbSession) -> Response:
    """Empty the profile without deleting the account.

    Clearing eleven sections one at a time is not a realistic way to start over,
    and starting over is a reasonable thing to want after a bad import.

    **The profile row itself survives**, and so does the user. Principle I says
    each user owns exactly one Professional Profile; deleting and recreating it
    would briefly break that and would orphan anything later pointed at it. This
    empties the container rather than replacing it.

    Import records are kept. They are history — what was uploaded and when — and
    they are not profile content, so a clean profile does not require pretending
    the imports never happened. The Master Resume goes, because it is derived
    from content that no longer exists; the next approval recreates it.
    """
    for entry in REMOVABLE.values():
        await session.execute(delete(entry.model).where(entry.owner == profile.id))

    # Bullets are removed by the cascade from their roles, and the Master Resume
    # is derived rather than owned.
    await session.execute(delete(ResumeProfile).where(ResumeProfile.profile_id == profile.id))

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/profile/{kind}/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove one item from the profile",
)
async def remove_item(
    kind: str, item_id: uuid.UUID, profile: CurrentProfile, session: DbSession
) -> Response:
    """Delete one item.

    Ownership is part of the WHERE clause rather than a separate check, so
    another user's row cannot be deleted even if the id is guessed — the query
    that could do it does not exist (FR-019).
    """
    if kind == "bullet":
        # Bullets hang off a role rather than the profile, so ownership is
        # established through the role they belong to.
        # `execute` is typed as returning Result; a DELETE really returns a
        # CursorResult, which is where rowcount lives. The cast states that
        # rather than working around it by fetching the row first.
        result = cast(
            CursorResult[Any],
            await session.execute(
                delete(ExperienceBullet).where(
                    ExperienceBullet.id == item_id,
                    ExperienceBullet.experience_id.in_(
                        select(WorkExperience.id).where(WorkExperience.profile_id == profile.id)
                    ),
                )
            ),
        )
    else:
        entry = _removable(kind)
        result = cast(
            CursorResult[Any],
            await session.execute(
                delete(entry.model).where(entry.owner == profile.id, entry.identity == item_id)
            ),
        )

    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/profile/{kind}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear a whole section of the profile",
)
async def remove_section(kind: str, profile: CurrentProfile, session: DbSession) -> Response:
    """Delete every item of one kind.

    Exists for the case that motivated it: a skills block parsed badly enough
    that removing twenty-two entries one at a time is not a realistic repair.
    """
    entry = _removable(kind)
    await session.execute(delete(entry.model).where(entry.owner == profile.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
