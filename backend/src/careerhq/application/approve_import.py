"""Approval: the moment staged content becomes profile data.

This is Principle II's mechanism. Everything before it is a proposal; this is
where a human's decision takes effect, and it is the only path that writes to
the Professional Profile.

The whole operation is one transaction (FR-023). A half-applied import would
leave a profile that is neither what the CV said nor what the user approved.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.domain.models import (
    Certification,
    ContactInformation,
    Education,
    ExperienceBullet,
    ExtractionItem,
    ImportedResume,
    ImportStatus,
    ItemDecision,
    Language,
    MilitaryService,
    ProfessionalTitle,
    Project,
    ResumeProfile,
    Skill,
    Source,
    SummaryBlock,
    VolunteerExperience,
    WorkExperience,
)

logger = logging.getLogger("careerhq.import")

MASTER_RESUME_NAME = "Master Resume"


class AlreadyApprovedError(RuntimeError):
    """This import has been approved already.

    Raised rather than silently succeeding so the caller can answer 409. The
    realistic cause is a double-clicked button, and constraint C4 would refuse
    the second Master Resume anyway — but a clear conflict is a better answer
    than a database error.
    """


class NothingAcceptedError(RuntimeError):
    """No item was accepted, so there is nothing to approve."""


async def approve_import(
    session: AsyncSession,
    *,
    imported_resume: ImportedResume,
    profile_id: uuid.UUID,
) -> ResumeProfile:
    """Write accepted items into the profile and create the Master Resume.

    Items left `pending` are treated as accepted: the reviewer saw them and did
    not discard them. Only an explicit discard excludes an item — which keeps
    the default action "keep what your CV says" rather than making the user
    confirm sixty things individually.
    """
    if imported_resume.status == ImportStatus.APPROVED:
        raise AlreadyApprovedError("This import has already been approved.")

    accepted = [item for item in imported_resume.items if item.decision != ItemDecision.DISCARDED]
    if not accepted:
        raise NothingAcceptedError("Nothing was accepted, so there is nothing to approve.")

    roles: dict[uuid.UUID, WorkExperience] = {}

    for item in accepted:
        payload = dict(item.payload)
        source = _source_of(item)

        match item.kind:
            case "contact":
                session.add(
                    ContactInformation(
                        profile_id=profile_id,
                        full_name=payload.get("full_name"),
                        email=payload.get("email"),
                        phone=payload.get("phone"),
                        location=payload.get("location"),
                        links=_join_links(payload.get("links")),
                        source=source,
                    )
                )
            case "title":
                session.add(
                    ProfessionalTitle(
                        profile_id=profile_id,
                        title=payload["title"],
                        ordinal=item.ordinal,
                        source=source,
                    )
                )
            case "summary":
                session.add(
                    SummaryBlock(profile_id=profile_id, text=payload["text"], source=source)
                )
            case "work_experience":
                role = WorkExperience(
                    profile_id=profile_id,
                    company=payload["company"],
                    title=payload.get("title"),
                    location=payload.get("location"),
                    start_date=payload.get("start_date"),
                    end_date=payload.get("end_date"),
                    is_current=bool(payload.get("is_current")),
                    ordinal=item.ordinal,
                    source=source,
                )
                session.add(role)
                roles[item.id] = role
            case "skill":
                session.add(
                    Skill(
                        profile_id=profile_id,
                        name=payload["name"],
                        category=payload.get("category"),
                        source=source,
                    )
                )
            case "project":
                session.add(
                    Project(
                        profile_id=profile_id,
                        name=payload["name"],
                        description=payload.get("description"),
                        url=payload.get("url"),
                        source=source,
                    )
                )
            case "education":
                session.add(
                    Education(
                        profile_id=profile_id,
                        institution=payload["institution"],
                        qualification=payload.get("qualification"),
                        field_of_study=payload.get("field_of_study"),
                        start_date=payload.get("start_date"),
                        end_date=payload.get("end_date"),
                        grade=payload.get("grade"),
                        source=source,
                    )
                )
            case "certification":
                session.add(
                    Certification(
                        profile_id=profile_id,
                        name=payload["name"],
                        issuer=payload.get("issuer"),
                        year=payload.get("year"),
                        source=source,
                    )
                )
            case "military_service":
                session.add(
                    MilitaryService(
                        profile_id=profile_id,
                        branch=payload["branch"],
                        role=payload.get("role"),
                        start_date=payload.get("start_date"),
                        end_date=payload.get("end_date"),
                        details=payload.get("details"),
                        source=source,
                    )
                )
            case "volunteer":
                session.add(
                    VolunteerExperience(
                        profile_id=profile_id,
                        organisation=payload["organisation"],
                        role=payload.get("role"),
                        start_date=payload.get("start_date"),
                        end_date=payload.get("end_date"),
                        description=payload.get("description"),
                        source=source,
                    )
                )
            case "language":
                session.add(
                    Language(
                        profile_id=profile_id,
                        name=payload["name"],
                        proficiency=payload.get("proficiency"),
                        source=source,
                    )
                )

    # Bullets last: their roles must exist as objects first so the relationship
    # resolves the foreign key on flush.
    for item in accepted:
        if item.kind != "bullet" or item.parent_id is None:
            continue
        parent_role = roles.get(item.parent_id)
        if parent_role is None:
            # The role was discarded; its bullets go with it rather than being
            # orphaned onto the profile with no context.
            continue
        parent_role.bullets.append(
            ExperienceBullet(
                text=dict(item.payload)["text"],
                ordinal=item.ordinal,
                source=_source_of(item),
            )
        )

    master = await _ensure_master_resume(session, profile_id)

    imported_resume.status = ImportStatus.APPROVED
    imported_resume.approved_at = func.now()

    logger.info(
        "import approved",
        extra={
            "import_id": str(imported_resume.id),
            "accepted_items": len(accepted),
            "discarded_items": len(imported_resume.items) - len(accepted),
        },
    )
    return master


def _join_links(value: object) -> str | None:
    """Flatten extracted links to one string, tolerating a malformed payload.

    The payload is JSON from a model. It *should* be a list of strings, and if
    it is not, dropping the links is better than failing an entire approval over
    a secondary field.
    """
    if not isinstance(value, list):
        return None
    links = [str(item) for item in value if item]
    return "\n".join(links) if links else None


def _source_of(item: ExtractionItem) -> Source:
    """Provenance survives approval (FR-004).

    An item the user never touched stays `extracted`, so the profile records
    which facts a human actually verified rather than flattening everything into
    equally-trusted claims.
    """
    return item.source


async def _ensure_master_resume(session: AsyncSession, profile_id: uuid.UUID) -> ResumeProfile:
    """Return the profile's Master Resume, creating it on first approval.

    Constraint C4 makes a second one impossible at the database level; this
    keeps a re-import from trying and failing.
    """
    existing = await session.scalar(
        select(ResumeProfile).where(ResumeProfile.profile_id == profile_id, ResumeProfile.is_master)
    )
    if existing is not None:
        return existing

    master = ResumeProfile(profile_id=profile_id, name=MASTER_RESUME_NAME, is_master=True)
    session.add(master)
    return master
