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

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

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


def _key(*parts: object) -> str:
    """A comparison key for deciding whether the profile already holds a fact.

    Case- and whitespace-insensitive, because "C++" and "c++ " are the same
    skill and a second import should not add both.
    """
    return "|".join(str(p or "").strip().casefold() for p in parts)


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

    # Two modes, and which one applies is decided by what the user actually did.
    #
    # On a first import people want the whole CV, so an untouched review means
    # "add everything I did not discard" — thirty-nine confirmations of the
    # obvious is not consent, it is an obstacle. On a second import the
    # interesting items are the few that are new, so explicitly adding any of
    # them switches the meaning to "only these".
    #
    # The interface names the active mode in the button rather than leaving it
    # to be inferred: "Add all 39" or "Add 5 selected".
    explicit = [i for i in imported_resume.items if i.decision == ItemDecision.ACCEPTED]
    accepted = explicit or [
        i for i in imported_resume.items if i.decision != ItemDecision.DISCARDED
    ]
    if not accepted:
        raise NothingAcceptedError("Nothing was accepted, so there is nothing to approve.")

    # What the profile already holds. A second import merges into it rather than
    # appending to it (FR-009): re-importing an updated CV is normal, and
    # without this every approval duplicated the entire profile — observed at
    # 66 skills, 27 bullets and three contact rows after three imports.
    existing = await existing_keys(session, profile_id)

    roles: dict[uuid.UUID, WorkExperience] = {}
    #: Roles already in the profile, so a re-import's bullets attach to the row
    #: that is already there instead of creating a second copy of the job.
    known_roles = await _existing_roles(session, profile_id)
    skipped = 0

    for item in accepted:
        payload = dict(item.payload)
        source = _source_of(item)

        duplicate = duplicate_key(item.kind, payload)
        if duplicate is not None and duplicate in existing:
            skipped += 1
            if item.kind == "work_experience" and duplicate in known_roles:
                # Point this import's bullets at the role already on the
                # profile, so an updated CV adds only its new achievements.
                roles[item.id] = known_roles[duplicate]
            continue
        if duplicate is not None:
            existing.add(duplicate)

        match item.kind:
            case "contact":
                # Single-valued: a person has one set of contact details, so a
                # newer CV supersedes the older rather than adding a second row.
                # But never over a value the user corrected — FR-009 forbids
                # silently overwriting a verified fact, and losing an edited
                # phone number to a stale CV is exactly that.
                if not await _replaceable(
                    session,
                    ContactInformation.source,
                    ContactInformation.profile_id,
                    profile_id,
                ):
                    skipped += 1
                    continue
                await session.execute(
                    delete(ContactInformation).where(ContactInformation.profile_id == profile_id)
                )
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
                if not await _replaceable(
                    session,
                    SummaryBlock.source,
                    SummaryBlock.profile_id,
                    profile_id,
                ):
                    skipped += 1
                    continue
                await session.execute(
                    delete(SummaryBlock).where(SummaryBlock.profile_id == profile_id)
                )
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
        text = dict(item.payload)["text"]
        if any(_key(b.text) == _key(text) for b in parent_role.bullets):
            skipped += 1
            continue

        parent_role.bullets.append(
            ExperienceBullet(
                text=text,
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
            "skipped_as_duplicate": skipped,
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


def duplicate_key(kind: str, payload: dict[str, object]) -> str | None:
    """The identity of a fact, for deciding whether the profile already has it.

    Returns `None` for kinds that are single-valued and handled by replacement
    (contact, summary), and for bullets, which are compared within their role
    rather than across the profile — the same sentence under two different jobs
    is two different claims.

    The keys are deliberately conservative. A role is identified by company,
    title *and* start date, so a promotion at the same employer stays a separate
    entry; two spellings of one job would rather be duplicated and discarded by
    hand than silently merged into one.
    """
    match kind:
        case "title":
            return _key("title", payload.get("title"))
        case "work_experience":
            return _key(
                "role", payload.get("company"), payload.get("title"), payload.get("start_date")
            )
        case "skill":
            return _key("skill", payload.get("name"))
        case "project":
            return _key("project", payload.get("name"))
        case "education":
            return _key("education", payload.get("institution"), payload.get("qualification"))
        case "certification":
            return _key("certification", payload.get("name"), payload.get("issuer"))
        case "language":
            return _key("language", payload.get("name"))
        case "military_service":
            return _key("military", payload.get("branch"), payload.get("role"))
        case "volunteer":
            return _key("volunteer", payload.get("organisation"), payload.get("role"))
        case _:
            return None


async def existing_keys(session: AsyncSession, profile_id: uuid.UUID) -> set[str]:
    """Keys for everything the profile already holds."""
    keys: set[str] = set()

    for title in await session.scalars(
        select(ProfessionalTitle).where(ProfessionalTitle.profile_id == profile_id)
    ):
        keys.add(_key("title", title.title))

    for role in await session.scalars(
        select(WorkExperience).where(WorkExperience.profile_id == profile_id)
    ):
        keys.add(_key("role", role.company, role.title, role.start_date))

    for skill in await session.scalars(select(Skill).where(Skill.profile_id == profile_id)):
        keys.add(_key("skill", skill.name))

    for project in await session.scalars(select(Project).where(Project.profile_id == profile_id)):
        keys.add(_key("project", project.name))

    for education in await session.scalars(
        select(Education).where(Education.profile_id == profile_id)
    ):
        keys.add(_key("education", education.institution, education.qualification))

    for cert in await session.scalars(
        select(Certification).where(Certification.profile_id == profile_id)
    ):
        keys.add(_key("certification", cert.name, cert.issuer))

    for language in await session.scalars(
        select(Language).where(Language.profile_id == profile_id)
    ):
        keys.add(_key("language", language.name))

    for service in await session.scalars(
        select(MilitaryService).where(MilitaryService.profile_id == profile_id)
    ):
        keys.add(_key("military", service.branch, service.role))

    for volunteering in await session.scalars(
        select(VolunteerExperience).where(VolunteerExperience.profile_id == profile_id)
    ):
        keys.add(_key("volunteer", volunteering.organisation, volunteering.role))

    return keys


async def _existing_roles(
    session: AsyncSession, profile_id: uuid.UUID
) -> dict[str, WorkExperience]:
    """Roles already on the profile, keyed the same way as an incoming one.

    An updated CV usually repeats the job you are still in and adds a new
    achievement to it. Without this the bullet would be orphaned — its role
    skipped as a duplicate, and nothing for it to attach to.
    """
    roles = await session.scalars(
        select(WorkExperience).where(WorkExperience.profile_id == profile_id)
    )
    return {_key("role", r.company, r.title, r.start_date): r for r in roles}


async def _replaceable(
    session: AsyncSession,
    source_column: InstrumentedAttribute[Source],
    owner_column: InstrumentedAttribute[uuid.UUID],
    profile_id: uuid.UUID,
) -> bool:
    """Whether a single-valued field may be replaced by an incoming import.

    Yes when it is absent, or when what is there came from an earlier extraction
    and the user never touched it. **No when the user corrected or wrote it**:
    FR-009 forbids silently overwriting a verified fact, and a rewritten summary
    is among the most likely things a person edits by hand and the least likely
    thing they expect a later CV to erase.

    The incoming value is not lost — the import record keeps it — but it does
    not take effect on its own.
    """
    sources = await session.scalars(select(source_column).where(owner_column == profile_id))
    return all(source == Source.EXTRACTED for source in sources)
