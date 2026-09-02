"""Recovering text — and, for a PDF, the design it was set in — from an upload.

The boundary is narrow on purpose: **bytes in, text and an optional theme out**.
What the text *means* is the model's problem, and whether the extraction
succeeded is the caller's — but the distinction between a file we could not read
and a CV that genuinely lacks a section is drawn here, because this is the only
layer that can see it.

**The contract was widened from "bytes in, text out" deliberately, and only by
one field.** Geometry is a second reading of the same page, and this is the only
layer that ever holds the page: the retained original in object storage may not
be read back to recover it (`tests/unit/test_architecture.py`), so a theme is
either taken here, in the same parse, or not at all. A DOCX carries no geometry
and always yields `None`, which is why the field is optional rather than the
return type being split per format.
"""

from __future__ import annotations

from dataclasses import dataclass

from careerhq.domain.schemas.theme import ResumeTheme
from careerhq.infrastructure.documents import docx, pdf

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

ACCEPTED_TYPES = frozenset({PDF_TYPE, DOCX_TYPE})

#: Leading bytes that identify the formats we accept. DOCX is a ZIP container,
#: so it shares its signature with every other Office format — which is fine,
#: because python-docx refuses the ones that are not documents.
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"


class UnsupportedDocumentError(ValueError):
    """The upload is not a PDF or DOCX, whatever it claims to be."""


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """What one upload yielded: its words, and the design they were set in."""

    text: str
    #: `None` for every DOCX, and for a PDF whose design cannot be reproduced.
    theme: ResumeTheme | None


def _guard(data: bytes, content_type: str) -> None:
    """Refuse anything that is not a CV format, before any parser sees it.

    **The declared content type is checked against the bytes**, not trusted. A
    browser sends whatever it infers from the filename, and an attacker sends
    whatever they like — so a `.pdf` full of something else would otherwise be
    handed straight to a parser. FR-001 is a user-facing rule about accepted
    formats; this is the same rule enforced where it can actually be relied on.
    """
    if content_type not in ACCEPTED_TYPES:
        raise UnsupportedDocumentError(f"{content_type} is not accepted. Upload a PDF or DOCX.")
    if content_type == PDF_TYPE:
        if not data.startswith(_PDF_MAGIC):
            raise UnsupportedDocumentError("That file is not a PDF, whatever its name says.")
    elif not data.startswith(_ZIP_MAGIC):
        raise UnsupportedDocumentError("That file is not a DOCX, whatever its name says.")


def extract_document(data: bytes, *, content_type: str) -> ExtractedDocument:
    """The text of `data`, and its theme when one can be recovered."""
    _guard(data, content_type)

    if content_type == PDF_TYPE:
        try:
            text, theme = pdf.extract_with_theme(data)
        except Exception as exc:
            # A file can begin with %PDF- and still be truncated or corrupt.
            # Letting pdfminer's exception escape would answer a bad upload with
            # a 500 — the user's file is the problem, and the response should say
            # so rather than implying the server broke.
            raise UnsupportedDocumentError(
                "That PDF could not be read — it may be corrupt or incomplete."
            ) from exc
        return ExtractedDocument(text=text, theme=theme)

    try:
        return ExtractedDocument(text=docx.extract(data), theme=None)
    except Exception as exc:  # python-docx raises several types for bad input
        raise UnsupportedDocumentError("That file could not be read as a DOCX.") from exc


def extract_text(data: bytes, *, content_type: str) -> str:
    """Just the words. Kept for callers that have no use for a design."""
    _guard(data, content_type)

    if content_type == PDF_TYPE:
        try:
            return pdf.extract(data)
        except Exception as exc:
            raise UnsupportedDocumentError(
                "That PDF could not be read — it may be corrupt or incomplete."
            ) from exc

    try:
        return docx.extract(data)
    except Exception as exc:  # python-docx raises several types for bad input
        raise UnsupportedDocumentError("That file could not be read as a DOCX.") from exc


__all__ = [
    "ACCEPTED_TYPES",
    "DOCX_TYPE",
    "PDF_TYPE",
    "ExtractedDocument",
    "UnsupportedDocumentError",
    "extract_document",
    "extract_text",
]
