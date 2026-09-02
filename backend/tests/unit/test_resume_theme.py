"""Theme extraction: what a CV's own geometry says about how it was set.

**The fixture is authored here, in CSS, and then measured back.** That is the whole
design of this file: the test *states* a design — 18pt semibold teal name, 10pt light
body, uppercase extra-light headings, a right-flushed date, a 6pt bullet indent — renders
it with an independent stylesheet, and asserts the extractor recovers those numbers from
the bytes. A fixture produced by the themed renderer would prove only that the two agree
with each other.

**Fictional content, generated at run time.** No CV belongs in this repository; the
subject here is invented and the PDF exists only for the duration of the test.
"""

from __future__ import annotations

import io
import pathlib

import pdfplumber
import pytest
from pydantic import ValidationError

from careerhq.domain.schemas.theme import ResumeTheme
from careerhq.infrastructure.documents import DOCX_TYPE, PDF_TYPE, extract_document
from careerhq.infrastructure.documents.render import _FONT_DIR
from careerhq.infrastructure.documents.theme import extract_theme

_ACCENT = "#00786C"

#: A CV shaped like a real one, written in CSS rather than derived from any document.
#: The numbers here are the assertions below, stated once.
_FIXTURE_CSS = f"""
@font-face {{ font-family: 'Poppins'; font-weight: 200; font-style: normal;
              src: url('{(_FONT_DIR / "Poppins-ExtraLight.ttf").as_uri()}'); }}
@font-face {{ font-family: 'Poppins'; font-weight: 300; font-style: normal;
              src: url('{(_FONT_DIR / "Poppins-Light.ttf").as_uri()}'); }}
@font-face {{ font-family: 'Poppins'; font-weight: 600; font-style: normal;
              src: url('{(_FONT_DIR / "Poppins-SemiBold.ttf").as_uri()}'); }}
@page {{ size: A4; margin: 24pt 18pt 24pt 18pt; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Poppins'; font-size: 10pt; font-weight: 300; line-height: 1.2;
        color: #000; }}
h1 {{ font-size: 18pt; font-weight: 600; color: {_ACCENT}; text-align: center;
      line-height: 1.15; }}
div.contact {{ font-size: 10pt; text-align: center; margin-top: 3pt; }}
h2 {{ font-size: 10pt; font-weight: 200; color: {_ACCENT}; text-transform: uppercase;
      margin-top: 9pt; margin-bottom: 9pt; }}
p.line {{ margin-bottom: 8pt; }}
p.prose {{ margin-bottom: 2pt; }}
div.role-row {{ display: flex; justify-content: space-between; align-items: baseline; }}
p.employer {{ font-size: 11pt; font-weight: 600; }}
p.dates {{ font-size: 10pt; font-weight: 600; white-space: nowrap; }}
p.title {{ font-size: 11pt; font-weight: 600; margin-bottom: 3pt; }}
p.bullet {{ padding-left: 16pt; margin-bottom: 2pt; }}
p.bullet::before {{ content: "\\2022"; display: inline-block; width: 10pt;
                    margin-left: -10pt; }}
span.label {{ font-weight: 600; }}
"""

_FIXTURE_BODY = """
<h1>Dana Levi</h1>
<div class='contact'>Tel Aviv &bull; dana@example.com &bull; +972 50 000 0000</div>
<h2>Summary</h2>
<p class='prose'>Backend engineer with six years on payment platforms, working across
distributed services, asynchronous processing and production support in regulated
environments where reliability matters more than novelty.</p>
<p class='prose'>Comfortable owning a service end to end, from schema design through
deployment and the on-call rotation that follows it.</p>
<h2>Skills</h2>
<p class='line'><span class='label'>Languages:</span> Python, Go, SQL</p>
<p class='line'><span class='label'>Databases:</span> PostgreSQL, Redis</p>
<p class='line'><span class='label'>Infrastructure:</span> Docker, Terraform, AWS</p>
<h2>Experience</h2>
<div class='role-row'><p class='employer'>Northwind Payments</p>
<p class='dates'>03/2019 - 01/2026</p></div>
<p class='title'>Senior Backend Engineer</p>
<p class='bullet'>Owned the settlement service end to end, from schema design to the
on-call rotation, keeping reconciliation correct through three platform migrations.</p>
<p class='bullet'>Cut reconciliation time from six hours to twenty minutes by moving the
nightly batch onto an event-driven pipeline.</p>
<h2>Education</h2>
<p class='line'>B.Sc. in Computer Science, Northern University</p>
"""


def _fixture_pdf() -> bytes:
    from careerhq.infrastructure.documents.render import _HTML

    rendered = _HTML(
        string=f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_FIXTURE_CSS}</style></head><body>{_FIXTURE_BODY}</body></html>"
    ).write_pdf()
    assert rendered is not None
    return bytes(rendered)


@pytest.fixture(scope="module")
def themed_cv() -> bytes:
    return _fixture_pdf()


@pytest.fixture(scope="module")
def theme(themed_cv: bytes) -> ResumeTheme:
    extracted = extract_document(themed_cv, content_type=PDF_TYPE)
    assert extracted.theme is not None, "the fixture's design was not recovered at all"
    return extracted.theme


def test_the_page_and_its_margins_are_recovered(theme: ResumeTheme) -> None:
    """Margins are read off the inked bounding box, so they match the CSS to the point."""
    assert theme.page_size == "A4"
    assert theme.margin_left_pt == pytest.approx(18.0, abs=1.0)
    assert theme.margin_right_pt == pytest.approx(18.0, abs=1.5)
    assert theme.margin_top_pt == pytest.approx(24.0, abs=6.0)


def test_the_body_face_is_the_one_covering_the_most_characters(theme: ResumeTheme) -> None:
    assert theme.font_family == "Poppins"
    assert theme.body_font_size_pt == 10.0
    assert theme.body_font_weight == 300


def test_the_leading_is_the_tightest_recurring_line_delta(theme: ResumeTheme) -> None:
    """The correction that cost a page break, and then a second one.

    The fixture sets `line-height: 1.2` and separates paragraphs and list entries, so the
    deltas form three populations. A median lands between them and reads high; a mode
    returns whichever population is largest, which on this list-heavy fixture is the 21pt
    Skills spacing. The lower quartile is the tightest recurring delta and returns the
    leading the stylesheet actually asked for.
    """
    assert theme.body_line_height == pytest.approx(1.2, abs=0.06)


def test_the_accent_colour_is_the_one_that_is_not_black(theme: ResumeTheme) -> None:
    """The accent reaches the theme through the rows that carry it.

    There is no `accent_color` field: the discriminator that separates a heading from
    body text is a local in the extractor, and what the renderer needs is the colour of
    each element it actually paints.
    """
    assert theme.name_color == _ACCENT
    assert theme.section_heading_color == _ACCENT


def test_the_name_is_the_largest_row_and_its_alignment_is_measured(theme: ResumeTheme) -> None:
    assert theme.name_font_size_pt == 18.0
    assert theme.name_font_weight == 600
    assert theme.name_alignment == "center"


def test_the_header_block_is_recognised_as_centred(theme: ResumeTheme) -> None:
    """The header ends at the first row that starts at the left margin.

    Reading it as "everything before the first heading" swept the summary in and the
    median offset then reported the block as left-aligned.
    """
    assert theme.contact_alignment == "center"


def test_section_headings_are_uppercase_in_a_face_other_than_the_body(
    theme: ResumeTheme,
) -> None:
    assert theme.section_heading_font_weight == 200
    assert theme.section_heading_transform == "uppercase"
    assert theme.section_heading_space_before_pt > 0


def test_a_date_flush_to_the_right_edge_is_recognised(theme: ResumeTheme) -> None:
    """Right-alignment is a measurement, not an assumption: the run has to end at the
    text's right edge *and* share its row with something on the left."""
    assert theme.date_alignment == "right"
    assert theme.role_font_size_pt == 11.0
    assert theme.role_font_weight == 600


def test_the_bullet_indents_are_recovered(theme: ResumeTheme) -> None:
    """16pt of padding with a 10pt marker pulled back puts the glyph at 6pt."""
    assert theme.bullet_glyph == "•"
    assert theme.bullet_marker_indent_pt == pytest.approx(6.0, abs=1.5)
    assert theme.bullet_text_indent_pt == pytest.approx(16.0, abs=1.5)
    assert theme.bullet_text_indent_pt >= theme.bullet_marker_indent_pt


def test_prose_and_list_spacing_are_carried_separately(theme: ResumeTheme) -> None:
    """The correction that put a heading 30pt out of place.

    The fixture sets 2pt between prose paragraphs and 8pt between list entries. One
    scalar cannot express both, so the theme carries two — and the list value must be
    the larger.
    """
    assert theme.list_item_space_pt > theme.paragraph_space_pt
    assert theme.list_item_space_pt == pytest.approx(8.0, abs=2.0)


def test_label_emphasis_is_detected_positionally(theme: ResumeTheme) -> None:
    """The label runs are heavier than the values that follow them, in several entries."""
    assert theme.label_emphasis_weight == 600


def test_a_docx_yields_no_theme_and_still_extracts_its_text() -> None:
    """DOCX has no geometry, and that must be an ordinary answer rather than a failure."""
    fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sample_cv.docx"
    extracted = extract_document(fixture.read_bytes(), content_type=DOCX_TYPE)
    assert extracted.theme is None
    assert extracted.text.strip()


def test_a_cv_in_an_unbundled_family_yields_no_theme(themed_cv: bytes) -> None:
    """A family we cannot render must not be described as one we can.

    Naming a font the image lacks resolves to a substitute, so the export would claim to
    reproduce a design while rendering a different one. `None` sends it to the plain
    template instead, which is honest.
    """
    from careerhq.infrastructure.documents.render import _HTML

    css = _FIXTURE_CSS.replace("'Poppins'", "'DejaVu Sans'")
    rendered = _HTML(
        string=f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head><body>{_FIXTURE_BODY}</body></html>"
    ).write_pdf()
    assert rendered is not None
    assert extract_document(bytes(rendered), content_type=PDF_TYPE).theme is None


def test_a_page_with_almost_no_text_yields_no_theme() -> None:
    from careerhq.infrastructure.documents.render import _HTML

    rendered = _HTML(string="<html><body><p>Hello.</p></body></html>").write_pdf()
    assert rendered is not None
    assert extract_document(bytes(rendered), content_type=PDF_TYPE).theme is None


def test_extraction_never_raises_into_the_import_path(themed_cv: bytes, monkeypatch) -> None:
    """A theme is an enhancement; an import must succeed without one.

    Drilled rather than asserted by inspection: the internals are made to raise, and the
    caller must still get a document back.
    """
    import careerhq.infrastructure.documents.theme as theme_module

    def explode(*_: object, **__: object) -> None:
        raise RuntimeError("geometry is unreadable")

    monkeypatch.setattr(theme_module, "_extract", explode)
    with pdfplumber.open(io.BytesIO(themed_cv)) as document:
        assert extract_theme(document) is None


def test_theme_extraction_reads_no_object_storage(themed_cv: bytes, monkeypatch) -> None:
    """The design comes from the bytes in hand, never from the retained original.

    Re-reading `imported_resumes.storage_key` to derive a capability is the case
    `test_architecture.py` refuses. Asserted by execution rather than by reading the
    source: object storage is made to raise, and extraction must still succeed.
    """
    from careerhq.infrastructure import storage

    async def refuse(*_: object, **__: object) -> bytes:
        raise AssertionError("theme extraction read object storage")

    monkeypatch.setattr(storage, "get_object", refuse)
    extracted = extract_document(themed_cv, content_type=PDF_TYPE)
    assert extracted.theme is not None


def test_the_vocabulary_is_closed() -> None:
    """A theme cannot carry CSS, an unbundled family, or an out-of-range size."""
    with pytest.raises(ValidationError):
        ResumeTheme(font_family="Comic Sans")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ResumeTheme(name_color="red")
    with pytest.raises(ValidationError):
        ResumeTheme(section_heading_color="#00786C; } body { display: none")
    with pytest.raises(ValidationError):
        ResumeTheme(body_font_size_pt=400.0)
    with pytest.raises(ValidationError):
        ResumeTheme(body_font_weight=317)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ResumeTheme(bullet_glyph="")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ResumeTheme(extra_rule="body { color: red }")  # type: ignore[call-arg]


def test_a_theme_round_trips_through_json(theme: ResumeTheme) -> None:
    """It is persisted as JSONB and read back, so this is the storage contract."""
    assert ResumeTheme.model_validate(theme.model_dump(mode="json")) == theme


def test_the_extraction_filter_and_the_schema_bound_cannot_drift() -> None:
    """Two constants that must agree, sixty lines apart in different modules.

    Extraction filtered candidate line deltas at `body_size * 2.6` while the model
    refused a line-height above 2.5, so a document whose lower quartile landed between
    them was extracted successfully and then rejected by validation — discarding the
    whole design over one field. They now read the same constant; this is what stops one
    of them from being edited alone.
    """
    from careerhq.domain.schemas import theme as schema
    from careerhq.infrastructure.documents import theme as extractor

    assert extractor.MAX_LINE_HEIGHT is schema.MAX_LINE_HEIGHT
    assert extractor.MAX_LABEL_CHARS is schema.MAX_LABEL_CHARS
    field = ResumeTheme.model_fields["body_line_height"]
    bounds = [m for m in field.metadata if getattr(m, "le", None) is not None]
    assert bounds and bounds[0].le == schema.MAX_LINE_HEIGHT, (
        "body_line_height's upper bound no longer matches the constant extraction filters on"
    )
