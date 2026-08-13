"""Text extraction from the uploaded file (T023, T024).

This layer is deliberately dumb: it recovers text and says how much it found.
Deciding what the text *means* is the model's job, and deciding whether the
extraction succeeded is the caller's — but the distinction between "a CV with no
skills section" and "a file we could not read" is made here, because only here
is the difference visible.
"""

from __future__ import annotations

import pathlib

import pytest

from careerhq.infrastructure.documents import UnsupportedDocumentError, extract_text

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def test_text_is_recovered_from_a_pdf() -> None:
    """T023 — the ordinary case."""
    text = extract_text((FIXTURES / "sample_cv.pdf").read_bytes(), content_type="application/pdf")

    assert "ALEX MORGAN" in text
    assert "Northwind Payments" in text
    assert "idempotency layer" in text, "per-bullet detail must survive"


def test_text_is_recovered_from_a_docx() -> None:
    """T023 — the other accepted format."""
    text = extract_text(
        (FIXTURES / "sample_cv.docx").read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert "ALEX MORGAN" in text
    assert "Calder Logistics" in text


def test_a_pdf_with_no_text_layer_yields_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """T024, FR-008 — the failure that must not look like success.

    A scan is a PDF in every respect except the one that matters. Returning ""
    here lets the caller report extraction failure; returning "" *and* being
    treated as a successful empty extraction is the bug this guards, because the
    user would be shown an empty review form implying their CV was read and
    found to contain nothing.
    """
    text = extract_text(
        (FIXTURES / "scanned_no_text.pdf").read_bytes(), content_type="application/pdf"
    )

    assert text.strip() == ""


def test_an_unsupported_type_is_refused_by_content_not_by_name() -> None:
    """FR-001 — and the check is on the bytes, not the declared type.

    A file named .pdf containing something else is the interesting case: trusting
    the declared content type would hand arbitrary bytes to a parser.
    """
    with pytest.raises(UnsupportedDocumentError):
        extract_text(b"MZ\x90\x00 this is a windows executable", content_type="application/pdf")


def test_a_declared_type_we_do_not_accept_is_refused() -> None:
    with pytest.raises(UnsupportedDocumentError):
        extract_text(b"plain text", content_type="text/plain")


def test_a_corrupt_pdf_is_refused_rather_than_crashing() -> None:
    """A file may begin with %PDF- and still be unreadable.

    Letting the parser's exception escape would answer a bad upload with a 500,
    implying the server broke when the file is the problem.
    """
    with pytest.raises(UnsupportedDocumentError):
        extract_text(b"%PDF-1.4 truncated and meaningless", content_type="application/pdf")
