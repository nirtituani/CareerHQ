"""T031 — the ATS assertions, verified with `pdfplumber`.

**An independent extractor, not the renderer attesting to itself.** WeasyPrint reporting
that it produced a single-column document with no tables is not evidence; a second tool
reading the finished bytes is. `pdfplumber` is already a dependency and is already
trusted for CV import, so no new trust is being extended here.

**Scope: assertions 1-5.** Assertion 6 — byte-determinism — is **T032**, and is
deliberately not asserted here: it is a comparison of bytes, not anything `pdfplumber`
can see, and T035's metadata pinning is what will make it hold.

**Assertion 1 as amended (2026-08-28).** The contract said *"text equals approved items,
in approved order"*, which no conforming document can satisfy: a résumé also carries a
name, contact details and section headings, and T034 requires the contact block to be in
the body. The claim that was meant, and that is asserted here, is:

    Every approved resume item appears in the rendered document in approved order, and
    no unapproved resume item is presented as resume content.

Document structure — the name, the contact line, section headings — is legitimate
non-item content. **The test still has to catch an unapproved item being rendered**, and
that is drilled rather than assumed.
"""

from __future__ import annotations

import io

import pdfplumber
import pytest

from careerhq.domain.schemas.document import ResumeDocument, ResumeSection
from careerhq.infrastructure.documents.render import render_resume_pdf

#: Text chosen to make assertion 5 able to fail. `ffi` and `fl` are the sequences a font
#: will substitute a single ligature glyph for; the en dash and the curly apostrophe are
#: the characters a bad encoding turns into `?` or mojibake. A fixture made only of plain
#: ASCII would pass assertion 5 against a renderer that mangles everything interesting.
_LIGATURE_LINE = "Reduced office workflow inefficiencies by 40% — the team's first fix."
# The en dash and curly quotes are the payload, not decoration: RUF001 is suppressed by
# code (never blanket) because replacing them with ASCII would delete the only thing
# assertion 5 has to detect.
_UNICODE_LINE = "Built a “flag-first” pipeline; latency fell 30–40% across affiliates."  # noqa: RUF001

_APPROVED = (
    "Senior Backend Engineer with six years on payment platforms.",
    _LIGATURE_LINE,
    "Owned the settlement service end to end, from schema to on-call.",
    _UNICODE_LINE,
    "Python, PostgreSQL, Kubernetes, distributed systems.",
)

#: Never passed to the renderer. Assertion 1's second half is the claim that nothing like
#: this can appear, so the test needs a string it can search for and not find.
_UNAPPROVED = "Led a team of forty engineers across three continents."


def _document() -> ResumeDocument:
    return ResumeDocument(
        full_name="Dana Levi",
        contact=("dana@example.com", "+972 50 000 0000", "Tel Aviv"),
        sections=(
            ResumeSection(heading="Summary", lines=(_APPROVED[0],)),
            ResumeSection(heading="Experience", lines=(_APPROVED[1], _APPROVED[2], _APPROVED[3])),
            ResumeSection(heading="Skills", lines=(_APPROVED[4],)),
        ),
    )


@pytest.fixture(scope="module")
def rendered() -> bytes:
    return render_resume_pdf(_document())


@pytest.fixture(scope="module")
def text(rendered: bytes) -> str:
    with pdfplumber.open(io.BytesIO(rendered)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_assertion_1_every_approved_item_appears_in_approved_order(text: str) -> None:
    """FR-017, as amended. Presence **and** order, and nothing unapproved.

    Order is checked by walking the extracted text once with a moving cursor rather than
    by comparing index lists: `str.find` from the start would report a correct order for
    a document that rendered the items backwards but repeated the first one.
    """
    flattened = " ".join(text.split())
    cursor = 0
    for item in _APPROVED:
        normalised = " ".join(item.split())
        found = flattened.find(normalised, cursor)
        assert found != -1, (
            f"approved item missing from the rendered document, or out of order: {item!r}"
        )
        cursor = found + len(normalised)

    assert _UNAPPROVED not in flattened, "an item nobody approved was rendered as resume content"


def test_assertion_2_the_document_carries_real_text_not_pictures_of_text(
    rendered: bytes, text: str
) -> None:
    """An image of a résumé extracts to nothing and is rejected by every parser."""
    assert text.strip(), "the document extracted to no text at all"

    with pdfplumber.open(io.BytesIO(rendered)) as pdf:
        images = [image for page in pdf.pages for image in page.images]
    assert images == [], f"the document embeds {len(images)} image object(s)"


#: **Measured, not guessed, and the first value here was wrong.** A single column of
#: running text covers a contiguous x-range, because lines end at varying points: the
#: correct render measures **0.0pt** of aggregate gap. The same document with
#: `column-count: 2; column-gap: 24pt` measures a **39pt** hole. 10pt sits between them
#: with room on both sides, and is far wider than a word space at the 10.5pt body size.
#:
#: The first version of this test used 12% of the page width (~71pt) and **passed the
#: two-column drill** — the check existed, named the right thing, and could not catch the
#: defect it was written for.
_MAX_COVERAGE_GAP_PT = 10.0


def _horizontal_gaps(words: list[dict[str, object]]) -> list[tuple[float, float]]:
    """Empty vertical bands, found by merging every word's x-extent and reading the holes.

    **Not "are any words past the midpoint"** — that was the first version of this test
    and it was simply wrong: a single-column line of running text crosses the midpoint on
    every line, so it failed against a correct document. What distinguishes two columns is
    a *gutter*: a band of x that no glyph on the page occupies.
    """
    spans = sorted((float(w["x0"]), float(w["x1"])) for w in words)  # type: ignore[arg-type]
    gaps: list[tuple[float, float]] = []
    reach = spans[0][1]
    for x0, x1 in spans[1:]:
        if x0 > reach:
            gaps.append((reach, x0))
        reach = max(reach, x1)
    return gaps


def test_assertion_3_the_reading_order_is_a_single_column(rendered: bytes) -> None:
    """A parser reading a two-column page top-to-bottom interleaves the two into nonsense.

    The document is single-column when no vertical gutter divides the text — checked by
    merging every word's x-extent on the page and asserting the covered region has no
    hole wide enough to be a column break.
    """
    with pdfplumber.open(io.BytesIO(rendered)) as pdf:
        pages = [(page.width, page.extract_words()) for page in pdf.pages]

    examined = sum(len(words) for _, words in pages)
    assert examined > 0, "no words to examine — the gutter check would pass on any document"

    for width, words in pages:
        for start, end in _horizontal_gaps(words):
            assert end - start < _MAX_COVERAGE_GAP_PT, (
                f"a {end - start:.0f}pt gutter runs down the page at x={start:.0f}-{end:.0f} "
                f"of width {width:.0f}; this is a second column, and a parser reading "
                "top-to-bottom will interleave the two"
            )


def test_assertion_4_the_document_contains_no_table_structures(rendered: bytes) -> None:
    """FR-018. A table is the classic ATS failure: the parser reads it cell-by-cell.

    **What this catches, measured by drilling: a *bordered* table.** `find_tables()` is
    line-based, so a **borderless** grid is invisible to it — and the drill proved that,
    passing against a two-column borderless table until it was given borders. Assertion 3
    does not rescue that case either: the narrow first column left only a 3pt coverage
    gap, well under the gutter boundary.

    **pdfplumber's text-based strategy is not the fix.** It reports one table for the
    *correct* single-column document too, so it cannot discriminate and would fail every
    conforming résumé.

    So the borderless grid is prevented by the template rather than detected here — the
    renderer emits `<p>`, never `<table>` — and this assertion is the regression guard for
    the bordered case. Recorded as a limitation of the six assertions as specified, not
    papered over.
    """
    with pdfplumber.open(io.BytesIO(rendered)) as pdf:
        tables = [table for page in pdf.pages for table in page.find_tables()]
    assert tables == [], f"the document contains {len(tables)} table structure(s)"


def test_assertion_5_characters_survive_the_round_trip(text: str) -> None:
    """Ligatures and typographic punctuation, which is where this actually breaks.

    A font substituting one glyph for `ffi` extracts as `ﬃ` unless ligatures are off,
    and an employer's parser then searches for `inefficiencies` and does not find it.
    """
    flattened = " ".join(text.split())

    for line in (_LIGATURE_LINE, _UNICODE_LINE):
        assert " ".join(line.split()) in flattened, f"round trip altered: {line!r}"

    # **Not drilled successfully, and that is recorded rather than hidden.** Removing
    # `font-variant-ligatures: none`, and then forcing a font that does ligate, both left
    # extraction correct: WeasyPrint maps the glyph back through the PDF's `ToUnicode`
    # table. This clause is a guard against a defect this renderer does not currently
    # exhibit — kept, because the guarantee should not rest on that table staying right.
    for ligature in ("ﬃ", "ﬁ", "ﬂ", "ﬀ"):
        assert ligature not in flattened, (
            f"the renderer emitted the ligature {ligature!r}; a parser searching for the "
            "plain letters will not match it"
        )
    assert "�" not in flattened, "a replacement character survived into the document"
