"""The themed renderer: the imported design, without losing the ATS guarantees.

**The claim under test is that typography is orthogonal to the six assertions.** Every
structural guarantee `test_export_ats.py` and `test_export_template.py` make about the
plain template is re-made here against a document set in Poppins, in teal, with a
right-flushed date and hanging-indent bullets. What changes is family, size, weight,
colour and space; what does not change is that the page is real text, in one column, in
reading order, with no image, no table, no vector object and no glyph a parser cannot
read.

**The plain path is asserted to be untouched**, because FR-021 records a checksum over an
exported document and FR-031 requires a re-render to reproduce it. A document exported
before themes existed must still render to the same bytes.
"""

from __future__ import annotations

import hashlib
import io
import time
import unicodedata

import pdfplumber
import pytest

from careerhq.domain.schemas.document import (
    ResumeDocument,
    ResumeGroup,
    ResumeRole,
    ResumeSection,
)
from careerhq.domain.schemas.theme import ResumeTheme
from careerhq.infrastructure.documents.render import (
    _render_html,
    _render_themed_html,
    render_resume_pdf,
)

_NAME = "Dana Levi"
_EMAIL = "dana@example.com"
_PHONE = "+972 50 000 0000"
_LAST_LINE = "B.Sc. in Computer Science, Northern University"
_UNAPPROVED = "Led a team of forty engineers across three continents."

_BULLETS = (
    "Owned the settlement service end to end, from schema design to the on-call rotation, "
    "keeping reconciliation correct through three separate platform migrations.",
    "Cut reconciliation time from six hours to twenty minutes by moving the nightly batch "
    "onto an event-driven pipeline.",
)

#: The design under test, stated rather than extracted — the values the real CV measured.
_THEME = ResumeTheme(
    page_size="A4",
    margin_top_pt=22.8,
    margin_right_pt=17.7,
    margin_bottom_pt=23.2,
    margin_left_pt=18.0,
    font_family="Poppins",
    body_font_size_pt=10.0,
    body_font_weight=300,
    body_line_height=1.2,
    name_font_size_pt=18.0,
    name_font_weight=600,
    name_color="#00786C",
    name_alignment="center",
    contact_font_size_pt=10.0,
    contact_alignment="center",
    section_heading_font_size_pt=10.0,
    section_heading_font_weight=200,
    section_heading_color="#00786C",
    section_heading_transform="uppercase",
    section_heading_space_before_pt=8.0,
    section_heading_space_after_pt=8.9,
    role_font_size_pt=11.0,
    role_font_weight=600,
    date_alignment="right",
    date_font_size_pt=10.0,
    date_font_weight=600,
    bullet_glyph="•",
    bullet_marker_indent_pt=6.0,
    bullet_text_indent_pt=15.6,
    paragraph_space_pt=2.5,
    list_item_space_pt=8.5,
    label_emphasis_weight=600,
)


def _document(bullets: tuple[str, ...] = _BULLETS) -> ResumeDocument:
    return ResumeDocument(
        full_name=_NAME,
        contact=(_EMAIL, _PHONE, "Tel Aviv"),
        sections=(
            ResumeSection.of_lines(
                "Summary",
                ("Backend engineer with six years on payment platforms.",),
                "prose",
            ),
            ResumeSection(
                heading="Experience",
                groups=(
                    ResumeGroup(
                        role=ResumeRole(
                            employer="Northwind Payments",
                            title="Senior Backend Engineer",
                            dates="03/2019 – 01/2026",  # noqa: RUF001
                        ),
                        lines=bullets,
                    ),
                ),
                style="roles",
            ),
            ResumeSection.of_lines(
                "Skills",
                ("Languages: Python, Go, SQL", "Databases: PostgreSQL, Redis"),
                "list",
            ),
            ResumeSection.of_lines("Education", (_LAST_LINE,), "list"),
        ),
    )


@pytest.fixture(scope="module")
def themed() -> bytes:
    return render_resume_pdf(_document(), _THEME)


@pytest.fixture(scope="module")
def page(themed: bytes) -> dict[str, object]:
    with pdfplumber.open(io.BytesIO(themed)) as pdf:
        p = pdf.pages[0]
        return {
            "pages": len(pdf.pages),
            "words": p.extract_words(),
            "text": "\n".join(page.extract_text() or "" for page in pdf.pages),
            "rects": list(p.rects),
            "curves": list(p.curves),
            "images": list(p.images),
            "chars": [c for c in p.chars if str(c["text"]).strip()],
            "width": p.width,
        }


# --------------------------------------------------------------------------
# The plain path must be exactly what it was
# --------------------------------------------------------------------------


#: A frozen document for the plain-template gate, deliberately separate from
#: `_document()`. That fixture belongs to the themed tests and will grow; a baseline that
#: moves whenever an unrelated fixture gains a line is not a baseline.
_BASELINE_DOCUMENT = ResumeDocument(
    full_name="Dana Levi",
    contact=("dana@example.com", "+972 50 000 0000", "Tel Aviv"),
    sections=(
        ResumeSection.of_lines(
            "Summary", ("Backend engineer with six years on payment platforms.",)
        ),
        ResumeSection(
            heading="Experience",
            groups=(
                ResumeGroup(
                    role=ResumeRole(
                        employer="Northwind Payments",
                        title="Senior Backend Engineer",
                        dates="03/2019 - 01/2026",
                    ),
                    lines=("Owned the settlement service end to end, from schema to on-call.",),
                ),
            ),
        ),
        ResumeSection.of_lines("Skills", ("Languages: Python, Go, SQL",)),
    ),
)

#: SHA-256 of `_render_html(_BASELINE_DOCUMENT)`, recorded 2026-09-02.
#:
#: **The markup, not the rendered bytes, and that is forced rather than chosen.** Which
#: font resolves decides the PDF bytes, and the plain template names a family this host
#: may not carry — Verdana on macOS, DejaVu on the Linux image — so a PDF hash would be
#: green on one machine and red on the other. That is the T032 trap, and it is recorded in
#: `render.py`. The markup is the part this repository controls and the part that decides
#: the bytes given a fixed runtime, so pinning it is the portable form of the claim.
#:
#: **Changing this value is the point.** If an edit to `_CSS` or `_render_html` makes this
#: fail, that edit alters every document already exported on the plain template: FR-021
#: recorded a checksum over those bytes and FR-031 requires a re-render to reproduce them.
#: Re-record it only with that consequence understood.
_PLAIN_MARKUP_SHA256 = "38464b9601de97bcd8a2e3cbfe980faaf6233a86062a30ac4ed53434b7e3cba2"


def test_the_plain_template_markup_is_unchanged() -> None:
    """The regression gate the previous version of this file did not have.

    It asserted `_render_html(d) == _render_html(d)` — a function compared with itself,
    which cannot fail — while the module docstring claimed the plain path was pinned. The
    property held, but nothing was checking it.
    """
    markup = _render_html(_BASELINE_DOCUMENT)
    assert hashlib.sha256(markup.encode("utf-8")).hexdigest() == _PLAIN_MARKUP_SHA256, (
        "the plain template's markup changed; every document already exported on it "
        "re-renders to different bytes than its recorded checksum (FR-021, FR-031)"
    )


def test_no_theme_routes_to_the_plain_template() -> None:
    """`theme=None` takes the original code path, not a themed one configured to look plain.

    The final assertion is what stops the gate above from being vacuous: if both emitters
    produced the same markup, pinning one of them would prove nothing about the other.
    """
    plain = _render_html(_BASELINE_DOCUMENT)
    assert "DejaVu Sans" in plain
    assert "Poppins" not in plain
    assert _render_themed_html(_BASELINE_DOCUMENT, _THEME) != plain


def test_the_default_argument_keeps_the_pre_theme_call_signature() -> None:
    """Every existing caller passes one argument; that must keep working."""
    assert render_resume_pdf(_document()).startswith(b"%PDF")


def test_both_render_paths_carry_the_same_lines_in_the_same_order() -> None:
    """A second render path is a place for the two to drift.

    They are allowed to differ in markup — the themed one wraps a label in a `<span>` —
    but never in *what* is said or the order it is said in, which is FR-017's claim. So
    this is asserted on the rendered text of both, not on their markup.

    **Matched on each line's opening words rather than the whole line**, because a soft
    break at an existing hyphen puts a space into the extracted text (`cross-functional`
    becomes `cross- functional`). That is a known fragility of exact-substring matching,
    it is unrelated to themes, and reproducing it here would test the wrapper rather than
    the ordering.
    """
    document = _document()

    def flattened(data: bytes) -> str:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return " ".join("\n".join(p.extract_text() or "" for p in pdf.pages).split())

    openings = [" ".join(line.split()[:4]) for line in document.lines_in_order()]
    assert len(openings) >= 5, "nothing to compare — this walk would pass on any document"
    for label, data in (
        ("plain", render_resume_pdf(document)),
        ("themed", render_resume_pdf(document, _THEME)),
    ):
        text, cursor = flattened(data), 0
        for opening in openings:
            found = text.find(opening, cursor)
            assert found != -1, f"{label}: {opening!r} is missing or out of order"
            cursor = found + len(opening)


# --------------------------------------------------------------------------
# The ATS guarantees, restated against the themed document
# --------------------------------------------------------------------------


def test_the_themed_document_is_real_text_in_approved_order(page: dict[str, object]) -> None:
    """Assertions 1 and 2, against a themed render."""
    text = str(page["text"])
    assert text.strip(), "the document extracted to no text at all"
    assert page["images"] == []

    flattened = " ".join(text.split())
    approved = _document().lines_in_order()
    assert len(approved) >= 5, "no approved items — the order walk would pass on anything"
    cursor = 0
    for line in approved:
        normalised = " ".join(line.split())
        found = flattened.find(normalised, cursor)
        assert found != -1, f"approved item missing or out of order: {line!r}"
        cursor = found + len(normalised)
    assert _UNAPPROVED not in flattened


def test_the_themed_document_is_still_a_single_column(page: dict[str, object]) -> None:
    """Assertion 3, and the one clause a right-flushed date could plausibly break.

    The dates sit in a flex row opposite the employer, which opens a horizontal hole on
    *that row*. It is not a gutter: the check merges every word's x-extent across the
    whole page, and body lines span the measure, so the covered region has no hole. This
    is the assertion that says the flex row is safe.
    """
    words = list(page["words"])  # type: ignore[arg-type]
    assert words, "no words to examine"
    spans = sorted((float(w["x0"]), float(w["x1"])) for w in words)
    gaps: list[tuple[float, float]] = []
    reach = spans[0][1]
    for x0, x1 in spans[1:]:
        if x0 > reach:
            gaps.append((reach, x0))
        reach = max(reach, x1)
    for start, end in gaps:
        assert end - start < 10.0, (
            f"a {end - start:.0f}pt gutter runs down the page at x={start:.0f}-{end:.0f}"
        )


def test_the_themed_document_contains_no_table_structures(themed: bytes) -> None:
    """Assertion 4. Flex, not a table — and this is what says so about the bytes."""
    with pdfplumber.open(io.BytesIO(themed)) as pdf:
        tables = [table for page in pdf.pages for table in page.find_tables()]
    assert tables == [], f"the document contains {len(tables)} table structure(s)"


def test_the_themed_document_emits_no_vector_objects(page: dict[str, object]) -> None:
    """T034's strongest clause, and the one a "designed" template is most likely to break.

    The theme's vocabulary has no border, no rule and no background, so there is nothing
    to paint. If a future field adds one, this is the assertion that will say so.
    """
    assert page["images"] == [], f"{len(page['images'])} image object(s)"  # type: ignore[arg-type]
    assert page["curves"] == [], f"{len(page['curves'])} curve(s)"  # type: ignore[arg-type]
    assert page["rects"] == [], f"{len(page['rects'])} rectangle(s)"  # type: ignore[arg-type]
    assert page["text"], "no text either; the assertions above would pass on a blank page"


def test_the_themed_document_uses_no_icon_glyphs(page: dict[str, object]) -> None:
    """The bullet is U+2022, a real character. An icon font would land in the PUA."""
    text = str(page["text"])
    offenders = [
        char for char in text if unicodedata.category(char) == "Co" or 0xE000 <= ord(char) <= 0xF8FF
    ]
    assert not offenders, f"private-use glyphs: {[hex(ord(c)) for c in offenders]}"
    assert text.strip()


def test_headings_survive_uppercasing_as_single_words(page: dict[str, object]) -> None:
    text = str(page["text"])
    assert "EXPERIENCE" in text
    assert " ".join("EXPERIENCE") not in text


def test_contact_details_render_in_the_body(page: dict[str, object]) -> None:
    """Nothing above the name and nothing below the last line — no header, no footer."""
    words = list(page["words"])  # type: ignore[arg-type]

    def top_of(needle: str) -> float:
        first = needle.split()[0]
        for word in words:
            if word["text"] == first:
                return float(word["top"])
        raise AssertionError(f"{needle!r} was not rendered at all")

    name_top = top_of(_NAME)
    heading_top = top_of("SUMMARY")
    highest = min(float(w["top"]) for w in words)
    assert highest == pytest.approx(name_top, abs=1.0)
    for fragment in (_EMAIL, _PHONE):
        assert name_top < top_of(fragment) < heading_top
    lowest = max(float(w["top"]) for w in words)
    assert lowest == pytest.approx(top_of(_LAST_LINE), abs=1.0)


def test_the_themed_role_row_orders_employer_dates_then_title(page: dict[str, object]) -> None:
    """Where the two emitters deliberately differ, stated rather than left implicit.

    `lines_in_order()` excludes employer, title and dates — a role heading is document
    structure, not an approved item — so the same-lines test above is blind here, and the
    two paths genuinely diverge: plain stacks employer, title, dates as three blocks;
    themed puts employer and dates on one flex row and the title beneath. Nothing was
    asserting that, so a change to either could pass unnoticed.

    The ATS-relevant half is unchanged either way and is asserted below: employer and
    title never share an extracted line.
    """
    lines = [" ".join(line.split()) for line in str(page["text"]).splitlines() if line.strip()]

    employer_row = next(i for i, line in enumerate(lines) if "Northwind Payments" in line)
    title_row = next(i for i, line in enumerate(lines) if "Senior Backend Engineer" in line)

    assert "03/2019" in lines[employer_row], (
        "the themed role row should carry the dates beside the employer; "
        f"got {lines[employer_row]!r}"
    )
    assert title_row == employer_row + 1, "the title should follow the employer row"
    assert "03/2019" not in lines[title_row]


def test_employer_and_title_stay_separate_readable_text(page: dict[str, object]) -> None:
    """T051's rule, which the flex row must not quietly undo by joining the employer to
    something else on its line. The date may share the row; the title may not."""
    for line in str(page["text"]).splitlines():
        stripped = " ".join(line.split())
        assert not ("Northwind Payments" in stripped and "Senior Backend Engineer" in stripped)


# --------------------------------------------------------------------------
# The theme is actually applied
# --------------------------------------------------------------------------


def test_the_themed_document_is_set_in_the_theme_s_faces(page: dict[str, object]) -> None:
    """The design reaches the page: the family, the accent colour and the name size."""
    chars = list(page["chars"])  # type: ignore[arg-type]
    assert len(chars) > 100, "too little text to judge the faces from"
    assert all("Poppins" in str(c["fontname"]) for c in chars), "the bundled family is not in use"

    def hex_of(char: dict[str, object]) -> str:
        colour = char.get("non_stroking_color") or (0, 0, 0)
        return "#" + "".join(f"{round(float(v) * 255):02X}" for v in tuple(colour)[:3])  # type: ignore[arg-type]

    name_chars = [c for c in chars if round(float(c["size"]), 1) == 18.0]
    assert name_chars, "the name did not render at the theme's size"
    assert {hex_of(c) for c in name_chars} == {"#00786C"}


def test_a_list_section_sets_its_entries_further_apart_than_prose(
    page: dict[str, object],
) -> None:
    """`SectionStyle` earning its place, measured on the page rather than asserted in CSS.

    The two Skills entries are one line each and must sit `list_item_space_pt` apart —
    materially more than the leading. This is the spacing that a single scalar could not
    express and that put a real CV's next heading 30pt out of place.
    """
    words = list(page["words"])  # type: ignore[arg-type]

    def top_of(token: str) -> float:
        for word in words:
            if word["text"] == token:
                return float(word["top"])
        raise AssertionError(f"{token!r} was not rendered")

    gap = top_of("Databases:") - top_of("Languages:")
    leading = _THEME.body_font_size_pt * _THEME.body_line_height
    assert gap > leading + 4.0, f"list entries are {gap:.1f}pt apart, barely more than the leading"


def test_label_emphasis_changes_the_face_and_not_the_text() -> None:
    """Positional emphasis must be invisible to every text-based assertion.

    A parser reads characters, so setting "Databases:" in a heavier face must leave the
    extracted text byte-identical. If it did not, FR-017's exact-substring walk would
    start failing on documents that merely look different.
    """
    plain_theme = _THEME.model_copy(update={"label_emphasis_weight": None})
    with_label = render_resume_pdf(_document(), _THEME)
    without = render_resume_pdf(_document(), plain_theme)

    def text_of(data: bytes) -> str:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)

    assert text_of(with_label) == text_of(without)

    def face_of(data: bytes, token: str) -> str:
        """The embedded face the given word is set in.

        **Per word, not per document.** A set of the faces on the page does not move:
        the heavier one is already in use for the role heading, so a document-wide
        comparison passes whether or not the label was emphasised at all — a gate with
        nothing to examine.
        """
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for word in pdf.pages[0].extract_words(extra_attrs=["fontname"]):
                if word["text"] == token:
                    return str(word["fontname"]).split("+")[-1]
        raise AssertionError(f"{token!r} was not rendered")

    assert face_of(with_label, "Databases:") != face_of(without, "Databases:"), (
        "the label is set in the same face with and without label emphasis"
    )
    # ...and only the label moved: the value after the colon keeps the body face.
    assert face_of(with_label, "PostgreSQL,") == face_of(without, "PostgreSQL,")


# --------------------------------------------------------------------------
# Determinism and reflow
# --------------------------------------------------------------------------


def test_two_themed_renders_more_than_a_second_apart_are_byte_identical() -> None:
    """FR-031, for the bundled faces.

    **The gap is deliberate and is the whole test.** `fontTools` stamps an embedded
    subset with the wall-clock time unless `SOURCE_DATE_EPOCH` is set, so two renders in
    the same second would agree by luck. Drilled on Linux with these exact font files:
    unpinned, the two differ; pinned, they do not.
    """
    first = render_resume_pdf(_document(), _THEME)
    time.sleep(1.2)
    second = render_resume_pdf(_document(), _THEME)
    assert first == second

    for marker in (b"/CreationDate", b"/ModDate", b"/ID"):
        assert marker not in first, f"{marker.decode()} varies per render"


def test_a_longer_tailored_bullet_reflows_without_disturbing_the_design() -> None:
    """The product requirement is not "reproduce the PDF" — it is "keep the design while
    Tailor changes the content".

    Growing a bullet must move text and nothing else: the marker indent, the wrapped-line
    indent and the right-flushed date are properties of the theme, not of the string.
    Page count is deliberately *not* asserted — spilling to a second page is correct
    reflow, and forcing one page would mean shrinking type nobody chose.
    """
    longer = (
        _BULLETS[0].rstrip(".")
        + ", partnering with platform teams to introduce idempotent retry semantics and "
        "observability instrumentation that cut mean time to recovery for settlement "
        "incidents while sustaining throughput under peak seasonal load.",
        _BULLETS[1],
    )

    def geometry(document: ResumeDocument) -> tuple[float, float, float]:
        data = render_resume_pdf(document, _THEME)
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            words = pdf.pages[0].extract_words()
            width = pdf.pages[0].width
        markers = [float(w["x0"]) for w in words if w["text"].startswith("•")]
        dates = [float(w["x1"]) for w in words if w["text"].startswith("03/2019")]
        wrapped = [
            float(w["x0"])
            for w in words
            if 20.0 < float(w["x0"]) < width / 2 and not w["text"].startswith("•")
        ]
        return min(markers), max(dates), min(wrapped)

    baseline = geometry(_document())
    grown = geometry(_document(longer))
    assert baseline[0] == pytest.approx(grown[0], abs=0.5), "the bullet marker moved"
    assert baseline[1] == pytest.approx(grown[1], abs=0.5), "the right-flushed date moved"
    assert baseline[2] == pytest.approx(grown[2], abs=0.5), "the hanging indent moved"


def test_the_bullet_marker_sits_where_the_theme_says() -> None:
    """The hanging indent, measured — `text-indent` put this a marker-width too far left."""
    data = render_resume_pdf(_document(), _THEME)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        words = pdf.pages[0].extract_words()
    markers = [float(w["x0"]) for w in words if w["text"].startswith("•")]
    assert markers, "no bullet marker was rendered"
    expected = _THEME.margin_left_pt + _THEME.bullet_marker_indent_pt
    assert min(markers) == pytest.approx(expected, abs=1.0)


def test_a_missing_bundled_font_is_logged_rather_than_rendered_silently(
    tmp_path, monkeypatch, caplog
) -> None:
    """A face that fails to ship must leave a trace.

    A skipped `@font-face` degrades to whatever fontconfig resolves: the document looks
    "a bit wrong" and its bytes change, while both renders in one environment fall back
    identically — so the determinism test stays green and nothing says why. The likeliest
    cause is a build that ships the package without its data files, which is exactly the
    kind of failure this repository keeps paying for silently.

    **Filtered by logger name**, because asserting on "a warning was emitted" passes
    against a warning some other module logged.
    """
    import logging

    from careerhq.infrastructure.documents import render as render_module

    monkeypatch.setattr(render_module, "_FONT_DIR", tmp_path)
    with caplog.at_level(logging.WARNING, logger=render_module.__name__):
        css = render_module._themed_css(_THEME)

    records = [r for r in caplog.records if r.name == render_module.__name__]
    assert len(records) == 1, f"expected exactly one warning from the renderer, got {records}"
    assert set(records[0].missing) == set(  # type: ignore[attr-defined]
        render_module._FONT_FILES.values()
    ), "the warning should name every face it could not find"
    assert "@font-face" not in css, "no face should be declared when no file exists"
