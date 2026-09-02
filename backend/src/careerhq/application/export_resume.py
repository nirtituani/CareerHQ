"""Export an approved version to a stored PDF (T036, FR-016/FR-017/FR-019).

**Export is a workflow operation, not a render.** `render_resume_pdf` turns content into
bytes; this turns an approved version into a stored artefact with a lifecycle — a
refusal, an object in storage, a checksum over exactly those bytes, and a status change.

    ensure_exportable  →  render  →  put bytes  →  ExportedDocument  →  status = EXPORTED

**The order is the substance.** The guard runs before anything with a side effect, so a
version that may not be exported costs nothing and leaves no trace. Bytes are stored
**before** the row is written because object storage is outside the transaction and one
failure direction has to be chosen: storing first leaves an orphan object when the
transaction fails, which is garbage; writing first would leave a record whose checksum
refers to bytes that do not exist, and FR-021's re-verification would fail on a document
the user believes they have.

**Not in `export.py`.** That module is the precondition alone, and T033 asserts it
imports no renderer — a guard that can render is a guard that might render before
refusing. Putting the use case there would have made that guarantee unassertable, so this
follows `extract_resume.py` and `tailor_resume.py` instead. `plan.md`'s file map put both
in `export.py`; the deviation is recorded in `tasks.md` under T036.

**The use case flushes; the caller commits** — the boundary `run_tailoring` already sets,
so a route can span several use cases in one transaction.
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from careerhq.application.export import ensure_exportable
from careerhq.domain.models import (
    ContactInformation,
    ExportedDocument,
    ResumeProfile,
    ResumeVersion,
    ResumeVersionItem,
    SourceKind,
    VersionStatus,
)
from careerhq.domain.schemas.document import (
    ResumeDocument,
    ResumeGroup,
    ResumeRole,
    ResumeSection,
    SectionStyle,
)
from careerhq.domain.schemas.theme import ResumeTheme
from careerhq.infrastructure import storage
from careerhq.infrastructure.documents.render import render_resume_pdf

logger = logging.getLogger(__name__)

#: Which conventional heading each kind of item belongs under, and the order the sections
#: appear in. **This is where the heading vocabulary lives** — T034 established that the
#: template must not choose it, because the renderer receives structure rather than
#: inferring it, and the corpus rule (*"use conventional section headings — Experience,
#: Education, Skills, Projects"*) is about content the caller assembles.
#:
#: `TITLE` shares the Summary section rather than getting one of its own: a professional
#: title is a headline, "Title" is not a conventional résumé heading, and
#: `ResumeDocument` has no header field to put it in. Recorded as a compromise forced by
#: the document model, not a preference — see the gap noted under T036.
#:
#: **The third element is what the section *is*, not how it looks.** `list` means every
#: line is a complete entry; `prose` means lines wrap into paragraphs. Only the caller
#: assembling the section knows which, so it is decided here rather than guessed at by a
#: renderer — and the plain template ignores it entirely.
_SECTIONS: tuple[tuple[str, tuple[SourceKind, ...], SectionStyle], ...] = (
    ("Summary", (SourceKind.TITLE, SourceKind.SUMMARY), "prose"),
    ("Experience", (SourceKind.EXPERIENCE_BULLET,), "roles"),
    ("Skills", (SourceKind.SKILL,), "list"),
    ("Projects", (SourceKind.PROJECT,), "list"),
    ("Education", (SourceKind.EDUCATION,), "list"),
    ("Certifications", (SourceKind.CERTIFICATION,), "list"),
    ("Languages", (SourceKind.LANGUAGE,), "list"),
)


def _dates(item: ResumeVersionItem) -> str:
    """The role's dates, composed from **only what the profile stored** (T051).

    Never inferred. A role with a start and no end does not become "Present": the owner
    recorded no end date, and the exporter asserting one would be writing a claim into an
    approved document that nobody approved.
    """
    start, end = (item.role_start_date or "").strip(), (item.role_end_date or "").strip()
    if start and end:
        # An en dash is the correct separator for a range. RUF001 is suppressed by code
        # rather than blanket, exactly as `test_export_ats.py` does for its Unicode
        # fixture: replacing it with a hyphen would be a typographic regression, and
        # `font-variant-ligatures: none` already guarantees it survives extraction.
        return f"{start} – {end}"  # noqa: RUF001
    return start or end


def _role_groups(members: list[ResumeVersionItem]) -> tuple[ResumeGroup, ...]:
    """Experience bullets, grouped into the jobs they came from.

    **Role order is `role_ordinal`, snapshotted from `work_experiences.ordinal`** — the
    profile's own explicit order field. **Within a role, order is `position`**, the
    owner's approved order, unchanged.

    That split is the whole T051 ordering decision, and it exists because `position`
    **collides across roles**: the draft reorders one flat list with no notion of a role
    boundary, so the real submitted document has two different jobs both holding position
    0. Within a single role `position` is unique and meaningful; across roles it is a
    data-model artefact and ordering by it interleaves two jobs into one stream.

    **Items with no snapshot render last, in one unlabelled group.** They are the versions
    that predate this — including a submitted one — and dropping them would silently
    delete approved content from a document somebody already sent.
    """
    snapshotted = [item for item in members if item.role_ordinal is not None]
    legacy = [item for item in members if item.role_ordinal is None]

    groups: list[ResumeGroup] = []
    # `dict` preserves insertion order, so sorting the items once orders the roles too.
    by_role: dict[tuple[int, str, str], list[ResumeVersionItem]] = {}
    for item in sorted(snapshotted, key=lambda i: (i.role_ordinal or 0, i.position)):
        key = (item.role_ordinal or 0, item.role_employer or "", item.role_title or "")
        by_role.setdefault(key, []).append(item)

    for (_, employer, title), items in by_role.items():
        groups.append(
            ResumeGroup(
                role=ResumeRole(employer=employer, title=title, dates=_dates(items[0])),
                lines=tuple(item.final_text for item in items),
            )
        )

    if legacy:
        groups.append(
            ResumeGroup(
                role=None,
                lines=tuple(item.final_text for item in sorted(legacy, key=lambda i: i.position)),
            )
        )
    return tuple(groups)


def _compose(version: ResumeVersion, contact: ContactInformation | None) -> ResumeDocument:
    """The approved items, in approved order, as a document.

    **`final_text`, always.** The column is materialised precisely so this reader does not
    re-derive it — and a *rejected* proposal is not a dropped item: its `final_text` is
    the owner's original wording, which belongs in the résumé. Only `included=False`
    leaves the document.
    """
    included = [item for item in version.items if item.included]

    sections: list[ResumeSection] = []
    for heading, kinds, style in _SECTIONS:
        # **Filter before sorting.** `kinds.index()` raises for a kind that is not in
        # this section, so sorting the whole list first is a crash rather than a
        # mis-ordering — found by the drill-shaped failure of the re-export test.
        members = [item for item in included if item.source_kind in kinds]
        if not members:
            continue
        groups = (
            _role_groups(members)
            if heading == "Experience"
            else (
                ResumeGroup(
                    role=None,
                    lines=tuple(
                        item.final_text
                        for item in sorted(
                            members, key=lambda i: (kinds.index(i.source_kind), i.position)
                        )
                    ),
                ),
            )
        )
        sections.append(ResumeSection(heading=heading, groups=groups, style=style))

    fragments = tuple(
        value
        for value in (
            contact.email if contact else None,
            contact.phone if contact else None,
            contact.location if contact else None,
        )
        if value
    )

    return ResumeDocument(
        full_name=(contact.full_name if contact and contact.full_name else version.name),
        contact=fragments,
        sections=tuple(sections),
    )


async def _theme_for(session: AsyncSession, version: ResumeVersion) -> ResumeTheme | None:
    """The design this version's résumé profile was imported in, if any.

    **Read from the résumé profile the version was built from**, not from whichever
    master exists now: `source_resume_profile_id` is the lineage the version already
    records, and following it means a document renders in the design it was created
    under.

    **A stored theme that no longer validates falls back to the plain template rather
    than failing the export.** The vocabulary is closed and versionless, so a field that
    is removed or narrowed later would otherwise turn every historical row into a failed
    export of a résumé somebody is waiting for. Logged, because silently changing how a
    document looks is exactly the kind of thing that should leave a trace.
    """
    stored = await session.scalar(
        select(ResumeProfile.theme).where(ResumeProfile.id == version.source_resume_profile_id)
    )
    if not stored:
        return None
    try:
        return ResumeTheme.model_validate(stored)
    except ValidationError:
        logger.warning(
            "stored resume theme no longer validates; exporting on the plain template",
            extra={
                "version_id": str(version.id),
                "resume_profile_id": str(version.source_resume_profile_id),
            },
        )
        return None


async def export_version(session: AsyncSession, *, version_id: uuid.UUID) -> ExportedDocument:
    """Render an approved version, store it, and record the export.

    Raises `ExportRefused` when the version may not be exported (FR-016) and `LookupError`
    when it does not exist — never `None`, which would make every caller guess.
    """
    version = await session.scalar(
        select(ResumeVersion)
        .where(ResumeVersion.id == version_id)
        .options(selectinload(ResumeVersion.items))
    )
    if version is None:
        raise LookupError(f"resume version {version_id} does not exist")

    # **First, and before anything with a side effect.** Not duplicated here: the rule
    # itself lives in `export.py` so it can be stated and drilled on its own.
    ensure_exportable(version.status)

    contact = await session.scalar(
        select(ContactInformation).where(ContactInformation.profile_id == version.profile_id)
    )
    theme = await _theme_for(session, version)

    pdf = render_resume_pdf(_compose(version, contact), theme)
    checksum = hashlib.sha256(pdf).hexdigest()

    # A fresh key per export. Re-export is legitimate and each one is its own object, so
    # the second must not overwrite the bytes the first recorded a checksum for.
    key = f"exports/{version.profile_id}/{version.id}/{uuid.uuid4()}.pdf"
    await storage.put_object(key, pdf, content_type="application/pdf")

    record = ExportedDocument(
        resume_version_id=version.id,
        document_storage_key=key,
        checksum_sha256=checksum,
        byte_size=len(pdf),
    )
    session.add(record)
    version.status = VersionStatus.EXPORTED
    await session.flush()
    return record


__all__ = ["export_version"]
