"""T034 — the ATS-safe template's guarantees, traced clause by clause.

**Most of the template landed at T031**, because assertions 1-5 needed a real PDF to
measure. T034's job is therefore not to write it again but to check each clause of the
requirement against an actual guarantee, and add the ones nothing was asserting. What
each clause traces to:

| T034 / FR-018 clause | Where it is guaranteed |
|---|---|
| single column | **T031** `test_assertion_3_the_reading_order_is_a_single_column` |
| no tables | **T031** `test_assertion_4_...` (bordered; the borderless limit is recorded there) |
| no graphics (as content) | **T031** `test_assertion_2_...` — no image objects |
| **no graphics (as decoration)** | here — hairline rules only, no filled panels |
| **contact details in the body, not a header/footer** | here |
| **standard headings survive as words** | here |
| **no icons** | here — icon fonts are glyphs, not images, so T031's check cannot see them |

**The heading *vocabulary* is not the template's to enforce.** The corpus rule is *"use
conventional section headings — Experience, Education, Skills, Projects"*, and headings
arrive on `ResumeDocument.sections`. Constraining them here would put domain vocabulary in
the renderer and contradict the rule that structure comes from the document rather than
from renderer-side inference. **T036 builds the document and owns which headings it uses.**
What the template owes is that a heading it is given survives as a recognisable word —
which is the corpus rule about letter-spacing, and is asserted below.

Byte-determinism is **T032** and is not re-asserted here.
"""

from __future__ import annotations

import io
import unicodedata

import pdfplumber
import pytest

from careerhq.domain.schemas.document import ResumeDocument, ResumeSection
from careerhq.infrastructure.documents.render import render_resume_pdf

_NAME = "Dana Levi"
_EMAIL = "dana@example.com"
_PHONE = "+972 50 000 0000"
_FIRST_HEADING = "Experience"
_LAST_LINE = "Cut reconciliation time from six hours to twenty minutes."


def _document() -> ResumeDocument:
    return ResumeDocument(
        full_name=_NAME,
        contact=(_EMAIL, _PHONE, "Tel Aviv"),
        sections=(
            ResumeSection.of_lines(
                _FIRST_HEADING,
                (
                    "Owned the settlement service end to end, from schema to on-call.",
                    _LAST_LINE,
                ),
            ),
        ),
    )


@pytest.fixture(scope="module")
def page() -> dict[str, object]:
    """One rendered page, decomposed into what the assertions below need."""
    rendered = render_resume_pdf(_document())
    with pdfplumber.open(io.BytesIO(rendered)) as pdf:
        assert len(pdf.pages) == 1, "the fixture should fit one page"
        p = pdf.pages[0]
        return {
            "words": p.extract_words(),
            "text": p.extract_text() or "",
            "rects": list(p.rects),
            "curves": list(p.curves),
            "images": list(p.images),
            "height": p.height,
        }


def _top_of(words: list[dict[str, object]], needle: str) -> float:
    """The vertical position of the first word of `needle`."""
    first = needle.split()[0]
    for word in words:
        if word["text"] == first:
            return float(word["top"])  # type: ignore[arg-type]
    raise AssertionError(f"{needle!r} was not rendered at all")


def test_contact_details_render_in_the_body_not_a_header_or_footer(
    page: dict[str, object],
) -> None:
    """T034, and the corpus's first ATS rule — the fields a parser extracts.

    **Asserted by flow position, not by margin arithmetic.** A `@page` margin box renders
    *outside* the flow, above the first body content; a footer renders below the last. So
    the claim is that nothing precedes the name and nothing follows the final line, and
    that the contact fragments sit between the name and the first heading. That stays
    true if the page margins are ever changed, which a "no words in the top 40pt" test
    would not.

    Why it matters more than layout taste: parsers routinely drop header and footer
    content, and the field that goes missing is the one nobody notices — the email
    address. The résumé still looks perfect.
    """
    words = page["words"]  # type: ignore[assignment]
    assert words, "nothing was rendered"

    name_top = _top_of(words, _NAME)  # type: ignore[arg-type]
    heading_top = _top_of(words, _FIRST_HEADING.upper())  # type: ignore[arg-type]
    last_top = _top_of(words, _LAST_LINE)  # type: ignore[arg-type]

    highest = min(float(w["top"]) for w in words)  # type: ignore[arg-type]
    assert highest == pytest.approx(name_top, abs=1.0), (
        "something is rendered above the candidate's name — a page header, which parsers "
        "routinely drop"
    )

    for fragment in (_EMAIL, _PHONE):
        position = _top_of(words, fragment)  # type: ignore[arg-type]
        assert name_top < position < heading_top, (
            f"{fragment!r} is not in the body between the name and the first heading"
        )

    lowest = max(float(w["top"]) for w in words)  # type: ignore[arg-type]
    assert lowest == pytest.approx(last_top, abs=1.0), (
        "something is rendered below the last line of content — a page footer"
    )


def test_section_headings_survive_as_recognisable_words(page: dict[str, object]) -> None:
    """The corpus rule, sourced to S-006: never space the letters of a word.

    *"A heading spaced as `E X P E R I E N C E` can fail to register as the word
    Experience."* `text-transform: uppercase` is fine — the extracted text is still one
    token. `letter-spacing` is not, and it is a CSS property this template controls.
    """
    text = page["text"]  # type: ignore[assignment]

    assert _FIRST_HEADING.upper() in text, (  # type: ignore[operator]
        f"the heading did not extract as the single word {_FIRST_HEADING.upper()!r}; "
        "letter-spacing inside a word breaks the parser's word recognition"
    )

    spaced = " ".join(_FIRST_HEADING.upper())
    assert spaced not in text, f"the heading extracted as {spaced!r}"  # type: ignore[operator]


def test_the_document_uses_no_icon_glyphs(page: dict[str, object]) -> None:
    """FR-018's "no icons", which T031's image check cannot see.

    An icon font draws a glyph, not an image — `page.images` stays empty while the
    extracted text carries a Private Use Area codepoint that no parser can interpret and
    no keyword search will ever match. Checked by Unicode category rather than by a list
    of known icon fonts.
    """
    text = page["text"]  # type: ignore[assignment]

    offenders = [
        char
        for char in text  # type: ignore[union-attr]
        if unicodedata.category(char) == "Co" or 0xE000 <= ord(char) <= 0xF8FF
    ]
    assert not offenders, (
        f"private-use glyphs in the extracted text: {[hex(ord(c)) for c in offenders]}; "
        "an icon font renders as a codepoint no parser can read"
    )

    assert text.strip(), "no text to examine — the scan would pass on an empty document"


def test_the_document_is_text_and_nothing_else(page: dict[str, object]) -> None:
    """FR-018's "no graphics", as the strongest form that is actually checkable.

    **The first version of this test tried to permit hairline rules and forbid filled
    panels, and could not.** The template had a `border-bottom` under each heading;
    WeasyPrint paints that as two **filled rectangles spanning the whole heading box**,
    which is indistinguishable from a shaded panel to anything inspecting the page. A
    height threshold could not separate them, and loosening it until the border passed
    would have admitted the panels the assertion exists to refuse.

    So the decoration went instead. It bought nothing a parser can read — separation
    comes from weight, capitals and space — and its removal turns a threshold nobody
    could defend into an exact property: **the page carries no vector objects at all.**
    A shaded band, a sidebar, a rule or a logo each break it.
    """
    assert page["images"] == [], f"{len(page['images'])} image object(s)"  # type: ignore[arg-type]
    assert page["curves"] == [], f"{len(page['curves'])} curve(s)"  # type: ignore[arg-type]
    assert page["rects"] == [], (  # type: ignore[arg-type]
        f"{len(page['rects'])} filled or stroked rectangle(s) — the template should emit "  # type: ignore[arg-type]
        "text and nothing else"
    )

    assert page["text"], "no text either; the assertions above would pass on a blank page"
