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
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from careerhq.application.export import ensure_exportable
from careerhq.domain.models import (
    ContactInformation,
    ExportedDocument,
    ResumeVersion,
    SourceKind,
    VersionStatus,
)
from careerhq.domain.schemas.document import ResumeDocument, ResumeSection
from careerhq.infrastructure import storage
from careerhq.infrastructure.documents.render import render_resume_pdf

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
_SECTIONS: tuple[tuple[str, tuple[SourceKind, ...]], ...] = (
    ("Summary", (SourceKind.TITLE, SourceKind.SUMMARY)),
    ("Experience", (SourceKind.EXPERIENCE_BULLET,)),
    ("Skills", (SourceKind.SKILL,)),
    ("Projects", (SourceKind.PROJECT,)),
    ("Education", (SourceKind.EDUCATION,)),
    ("Certifications", (SourceKind.CERTIFICATION,)),
    ("Languages", (SourceKind.LANGUAGE,)),
)


def _compose(version: ResumeVersion, contact: ContactInformation | None) -> ResumeDocument:
    """The approved items, in approved order, as a document.

    **`final_text`, always.** The column is materialised precisely so this reader does not
    re-derive it — and a *rejected* proposal is not a dropped item: its `final_text` is
    the owner's original wording, which belongs in the résumé. Only `included=False`
    leaves the document.
    """
    included = [item for item in version.items if item.included]

    sections: list[ResumeSection] = []
    for heading, kinds in _SECTIONS:
        # **Filter before sorting.** `kinds.index()` raises for a kind that is not in
        # this section, so sorting the whole list first is a crash rather than a
        # mis-ordering — found by the drill-shaped failure of the re-export test.
        members = [item for item in included if item.source_kind in kinds]
        lines = tuple(
            item.final_text
            for item in sorted(members, key=lambda i: (kinds.index(i.source_kind), i.position))
        )
        if lines:
            sections.append(ResumeSection(heading=heading, lines=lines))

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

    pdf = render_resume_pdf(_compose(version, contact))
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
