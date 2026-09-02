"""PDF text extraction, via pdfplumber.

pdfplumber and python-docx are MIT. **PyMuPDF is the better extractor and is
deliberately not used**: it is dual-licensed AGPL-3.0 or commercial, which is a
real obligation for a deployed web application and not a decision that should be
made by whoever happens to write the import (research.md R4). The quality gap
matters less here than it would elsewhere, because a model does the structuring
— this layer only has to recover the words.
"""

from __future__ import annotations

import io

import pdfplumber
from pdfplumber.pdf import PDF

from careerhq.domain.schemas.theme import ResumeTheme
from careerhq.infrastructure.documents.theme import extract_theme


def _text(document: PDF) -> str:
    return "\n".join(page.extract_text() or "" for page in document.pages).strip()


def extract(data: bytes) -> str:
    """Return the document's text, or `""` when it has no text layer.

    An empty string is a legitimate result, not an error: a scanned CV is a
    valid PDF that simply carries images instead of characters. The caller
    decides what that means — and must report it as failure rather than as an
    empty extraction (FR-008).
    """
    with pdfplumber.open(io.BytesIO(data)) as document:
        return _text(document)


def extract_with_theme(data: bytes) -> tuple[str, ResumeTheme | None]:
    """The document's text **and** the design it was set in, from one open.

    **One parse, because the second would have to come from somewhere.** The
    only other copy of these bytes is the retained original in object storage,
    and reading that back to recover layout is the "deriving from the upload"
    case `tests/unit/test_architecture.py` exists to refuse. Text and geometry
    are two readings of the page in front of us, so they are taken together.

    The theme is `None` whenever the design cannot be reproduced faithfully —
    see `theme.py`. That is an ordinary outcome, and the caller exports on the
    plain ATS template exactly as it did before themes existed.
    """
    with pdfplumber.open(io.BytesIO(data)) as document:
        return _text(document), extract_theme(document)
