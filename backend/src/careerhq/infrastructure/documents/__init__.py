"""Recovering text from an uploaded document.

The boundary is narrow on purpose: bytes in, text out. What the text *means* is
the model's problem, and whether the extraction succeeded is the caller's — but
the distinction between a file we could not read and a CV that genuinely lacks a
section is drawn here, because this is the only layer that can see it.
"""

from __future__ import annotations

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


def extract_text(data: bytes, *, content_type: str) -> str:
    """Return the text of `data`, refusing anything that is not a CV format.

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
        try:
            return pdf.extract(data)
        except Exception as exc:
            # A file can begin with %PDF- and still be truncated or corrupt.
            # Letting pdfminer's exception escape would answer a bad upload with
            # a 500 — the user's file is the problem, and the response should say
            # so rather than implying the server broke.
            raise UnsupportedDocumentError(
                "That PDF could not be read — it may be corrupt or incomplete."
            ) from exc

    if not data.startswith(_ZIP_MAGIC):
        raise UnsupportedDocumentError("That file is not a DOCX, whatever its name says.")

    try:
        return docx.extract(data)
    except Exception as exc:  # python-docx raises several types for bad input
        raise UnsupportedDocumentError("That file could not be read as a DOCX.") from exc


__all__ = [
    "ACCEPTED_TYPES",
    "DOCX_TYPE",
    "PDF_TYPE",
    "UnsupportedDocumentError",
    "extract_text",
]
