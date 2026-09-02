"""Turn an uploaded CV into staged, reviewable content.

Nothing here writes to the Professional Profile. That is `approve_import`'s job,
and keeping them apart is what makes FR-007 true by construction rather than by
care: an import nobody approved has nothing to undo.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.ports import StructuredCompletion
from careerhq.domain.models import ExtractionItem, ImportedResume, ImportStatus
from careerhq.domain.schemas.extraction import ResumeExtraction
from careerhq.infrastructure import storage
from careerhq.infrastructure.documents import extract_document

logger = logging.getLogger("careerhq.import")

TASK = "cv_extraction"

_PROMPT = """Extract this person's professional history from the CV below.

Rules:
- Copy what the document says. Do not infer, improve, or fill gaps.
- Keep each achievement or responsibility as its own bullet, worded as written.
- Keep dates exactly as they appear — do not normalise them.
- Omit anything you cannot find rather than guessing.
- Military service belongs in military_service, not work_experience. Volunteer
  and leadership roles belong in volunteering. Paid employment only in
  work_experience.
- For education, `qualification` is the award alone ("B.Sc.", "MSc", "PhD") and
  `field_of_study` is the subject ("Computer Science"). Do not repeat the
  subject inside the qualification.
- Set confidence per item: high when the document states it plainly, low when
  you had to interpret layout or infer a boundary.

CV:
---
{text}
---"""


class ExtractionProducedNothingError(RuntimeError):
    """The file was read, and nothing usable came out (FR-008).

    Separate from a failed provider call because the user-facing explanation
    differs: this one usually means a scan with no text layer, and saying so is
    more useful than reporting an error.
    """


async def extract_resume(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    filename: str,
    content_type: str,
    data: bytes,
    completion: StructuredCompletion,
) -> ImportedResume:
    """Store the upload, extract it, and stage the result for review.

    Raises `UnsupportedDocumentError` for a file that is not a CV format, and
    `ExtractionProducedNothingError` when the document yielded nothing usable.
    Both leave the profile untouched; the second records a failed import so the
    user can see what happened rather than wondering where their upload went.
    """
    # Refused before anything is stored: a rejected upload should leave no trace.
    #
    # **Text and theme come out of one parse of the bytes in hand.** After this
    # function returns, the only copy is the retained original, which no
    # extraction path may read back (`test_architecture.py`) — so a design not
    # taken here cannot be taken at all.
    extracted = extract_document(data, content_type=content_type)
    text = extracted.text

    storage_key = f"imports/{user_id}/{uuid.uuid4()}/{filename}"
    await storage.put_object(storage_key, data, content_type=content_type)

    record = ImportedResume(
        user_id=user_id,
        storage_key=storage_key,
        filename=filename,
        content_type=content_type,
        byte_size=len(data),
        status=ImportStatus.PENDING,
        # `None` for every DOCX and for any PDF whose design is not reproducible.
        theme=extracted.theme.model_dump(mode="json") if extracted.theme else None,
    )
    session.add(record)
    await session.flush()

    if not text.strip():
        record.status = ImportStatus.FAILED
        record.extraction_error = (
            "This file has no readable text — it looks like a scan or an image. "
            "Try a PDF exported from a word processor."
        )
        # Structured fields, not the message: the deployed platform discards
        # message text entirely (FR-022, slice 002).
        logger.info(
            "extraction found no text layer",
            extra={"import_id": str(record.id), "content_type": content_type},
        )
        raise ExtractionProducedNothingError(record.extraction_error)

    result = await completion.complete(
        task=TASK, schema=ResumeExtraction, prompt=_PROMPT.format(text=text)
    )

    # Principle V's audit record, written in the same transaction as the work.
    record.model = result.usage.model
    record.input_tokens = result.usage.input_tokens
    record.output_tokens = result.usage.output_tokens
    record.cost = result.usage.cost
    record.is_fixture = result.usage.is_fixture

    if result.value.is_empty:
        record.status = ImportStatus.FAILED
        record.extraction_error = (
            "Nothing usable could be read from this CV. Check it is the right file, "
            "or try a different export."
        )
        logger.info(
            "extraction produced no usable items",
            extra={"import_id": str(record.id), "model": result.usage.model},
        )
        raise ExtractionProducedNothingError(record.extraction_error)

    record.status = ImportStatus.EXTRACTED
    for item in _stage(result.value):
        item.imported_resume_id = record.id
        session.add(item)

    logger.info(
        "extraction staged",
        extra={
            "import_id": str(record.id),
            "model": result.usage.model,
            "item_count": result.value.item_count,
            "is_fixture": result.usage.is_fixture,
        },
    )
    return record


def _stage(extraction: ResumeExtraction) -> list[ExtractionItem]:
    """Flatten the extraction into reviewable rows, preserving CV order.

    Bullets are staged as their own items with `parent_id` pointing at their
    role, because review and later tailoring both operate at that granularity.
    """
    items: list[ExtractionItem] = []
    ordinal = 0

    def add(kind: str, payload: dict[str, object], confidence: float) -> ExtractionItem:
        nonlocal ordinal
        item = ExtractionItem(
            kind=kind,
            payload=payload,
            confidence=confidence,
            ordinal=ordinal,
        )
        ordinal += 1
        items.append(item)
        return item

    contact = extraction.contact.model_dump()
    if any(v for k, v in contact.items() if k != "confidence"):
        add("contact", contact, extraction.contact.confidence)

    for title in extraction.titles:
        add("title", title.model_dump(), title.confidence)

    if extraction.summary:
        add("summary", extraction.summary.model_dump(), extraction.summary.confidence)

    for role in extraction.work_experience:
        payload = role.model_dump(exclude={"bullets"})
        parent = add("work_experience", payload, role.confidence)
        for bullet in role.bullets:
            child = add("bullet", bullet.model_dump(), bullet.confidence)
            child.parent = parent  # resolved to parent_id on flush

    for collection, kind in (
        (extraction.skills, "skill"),
        (extraction.projects, "project"),
        (extraction.education, "education"),
        (extraction.certifications, "certification"),
        (extraction.languages, "language"),
        (extraction.military_service, "military_service"),
        (extraction.volunteering, "volunteer"),
    ):
        for entry in collection:
            add(kind, entry.model_dump(), entry.confidence)

    return items
