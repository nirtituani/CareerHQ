"""The visual identity of an imported résumé, as a closed vocabulary.

**A theme is not CSS, and that is the whole point.** Every field below is a bounded
scalar drawn from an enumerated set, so the set of documents this can produce is finite
and inspectable. There is no rule string, no selector, no length unit the caller chooses
and no escape hatch — which is what keeps ADR-013's "no resume designer" non-goal intact
while still letting an import keep its own typography. Widening it is a deliberate act:
add a field here, bound it, and drill the ATS assertions against the new range.

**Why a Pydantic model rather than a dataclass.** It is persisted as JSON and read back
from the database, so it re-enters the process as untrusted-shaped data. Validation on
load is what makes a hand-edited row or a schema that has moved on fail loudly instead of
rendering something nobody chose. The rest of `domain/schemas/` splits the same way:
`document.py` is in-process content and uses dataclasses; `extraction.py` crosses a
boundary and uses Pydantic.

**`font_family` is a whitelist of what the image actually carries**, not a free string.
A family that is merely *named* resolves to whatever fontconfig has, which silently
changes the rendered bytes — the failure T032 already paid for once. Adding a family
means adding its files under `infrastructure/documents/fonts/` and a member here, in the
same change.

**Every theme is optional and every renderer must work without one.** A DOCX import has
no geometry to recover, a PDF in an unbundled family yields `None`, and both must export
exactly as they did before this existed.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Families whose files are bundled under `infrastructure/documents/fonts/`.
#:
#: One member today, and that is honest rather than provisional: the only design this
#: has been drilled against is the Poppins CV the spike measured. A CV set in anything
#: else extracts to `None` and exports on the plain template, which is a correct answer
#: and not a degraded one.
FontFamily = Literal["Poppins"]

#: The weights bundled for every family. A weight with no file would fall back to a
#: synthesised face, which is a different document than the one that was measured.
FontWeight = Literal[200, 300, 400, 600, 700]

Alignment = Literal["left", "center", "right"]
TextTransform = Literal["none", "uppercase"]
PageSize = Literal["A4", "Letter"]

#: The one bullet glyph. A closed set because a marker is also a character a parser
#: reads: an icon-font glyph here would land in the extracted text as a private-use
#: codepoint, which `test_export_template.py` refuses.
BulletGlyph = Literal["•"]

#: `#RRGGBB`, uppercase. Bounded so a stored value cannot become a CSS expression.
HexColor = Annotated[str, Field(pattern=r"^#[0-9A-F]{6}$")]

#: Longest run before a colon that still reads as a label rather than a sentence that
#: happens to contain one. "Distributed Systems:" is 20 characters.
#:
#: **Here rather than in either module that uses it.** Detection (`documents/theme.py`)
#: and application (`documents/render.py`) must agree, and they did not: one admitted 39
#: characters and the other 40, so a 40-character label was detected as emphasis and then
#: rendered without it. One constant, in the contract both sides read.
MAX_LABEL_CHARS = 40

#: The largest line-height the theme may carry. Extraction filters its candidate line
#: deltas against this same value, so a document cannot produce a leading the model then
#: refuses — which discarded the whole theme rather than the one field.
MAX_LINE_HEIGHT = 2.5

_Pt = Annotated[float, Field(ge=0.0, le=200.0)]
_FontPt = Annotated[float, Field(ge=5.0, le=48.0)]
_Space = Annotated[float, Field(ge=0.0, le=72.0)]


class ResumeTheme(BaseModel):
    """One reproducible résumé design.

    Field order follows the document: page, body, name, contact, headings, roles,
    bullets, spacing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # -- page ---------------------------------------------------------------
    page_size: PageSize = "A4"
    margin_top_pt: _Pt = 51.0
    margin_right_pt: _Pt = 45.0
    margin_bottom_pt: _Pt = 51.0
    margin_left_pt: _Pt = 45.0

    # -- body ---------------------------------------------------------------
    font_family: FontFamily = "Poppins"
    body_font_size_pt: _FontPt = 10.0
    body_font_weight: FontWeight = 300
    body_line_height: Annotated[float, Field(ge=1.0, le=MAX_LINE_HEIGHT)] = 1.2

    # -- name and contact ---------------------------------------------------
    name_font_size_pt: _FontPt = 18.0
    name_font_weight: FontWeight = 600
    name_color: HexColor = "#000000"
    name_alignment: Alignment = "left"
    contact_font_size_pt: _FontPt = 10.0
    contact_alignment: Alignment = "left"

    # -- section headings ---------------------------------------------------
    section_heading_font_size_pt: _FontPt = 10.0
    section_heading_font_weight: FontWeight = 600
    section_heading_color: HexColor = "#000000"
    section_heading_transform: TextTransform = "uppercase"
    section_heading_space_before_pt: _Space = 8.0
    section_heading_space_after_pt: _Space = 8.0

    # -- roles --------------------------------------------------------------
    role_font_size_pt: _FontPt = 11.0
    role_font_weight: FontWeight = 600
    date_alignment: Literal["right", "inline"] = "inline"
    date_font_size_pt: _FontPt = 10.0
    date_font_weight: FontWeight = 400

    # -- bullets ------------------------------------------------------------
    bullet_glyph: BulletGlyph = "•"
    #: Distance from the text's left edge to the marker, and to the wrapped text
    #: beneath it. The difference between them is the marker's own box, so
    #: `bullet_text_indent_pt` must not be less than `bullet_marker_indent_pt`.
    bullet_marker_indent_pt: _Space = 0.0
    bullet_text_indent_pt: _Space = 12.0

    # -- spacing ------------------------------------------------------------
    #: Between paragraphs of prose, and between entries in a list section. They are
    #: separate because a single value cannot serve both: measured on a real CV, prose
    #: ran at 2pt and Skills entries at 8pt, and collapsing them put the following
    #: heading 30pt out of place.
    paragraph_space_pt: _Space = 3.0
    list_item_space_pt: _Space = 3.0

    #: Weight for the label before the first colon of a list entry
    #: ("Databases: ..."), or `None` for no label emphasis. **Positional, never
    #: author-chosen**: it is derived from where the colon is, so a Tailor rewrite of
    #: the value cannot invalidate it and no markup enters item text.
    label_emphasis_weight: FontWeight | None = None

    def bullet_marker_width_pt(self) -> float:
        """The marker's own box — what the hanging indent has to pull back."""
        return max(0.0, self.bullet_text_indent_pt - self.bullet_marker_indent_pt)


__all__ = [
    "MAX_LABEL_CHARS",
    "MAX_LINE_HEIGHT",
    "Alignment",
    "BulletGlyph",
    "FontFamily",
    "FontWeight",
    "HexColor",
    "PageSize",
    "ResumeTheme",
    "TextTransform",
]
