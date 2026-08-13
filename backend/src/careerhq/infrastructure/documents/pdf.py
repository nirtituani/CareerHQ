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


def extract(data: bytes) -> str:
    """Return the document's text, or `""` when it has no text layer.

    An empty string is a legitimate result, not an error: a scanned CV is a
    valid PDF that simply carries images instead of characters. The caller
    decides what that means — and must report it as failure rather than as an
    empty extraction (FR-008).
    """
    with pdfplumber.open(io.BytesIO(data)) as document:
        pages = [page.extract_text() or "" for page in document.pages]

    return "\n".join(pages).strip()
