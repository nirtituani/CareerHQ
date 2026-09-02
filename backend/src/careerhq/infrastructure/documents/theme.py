"""Recovering an imported CV's visual design from its own geometry.

**Deterministic, and deliberately so.** Every value here comes from a stated rule over
pdfplumber's character coordinates — font name, size, colour, x, top. No model is asked
what a heading looks like, because a heading *is* a measurable thing (larger or
differently-weighted text, set apart) and a completion would cost money, latency and
reproducibility to answer a question arithmetic already answers. The extraction seam is
for reading meaning out of prose; this is reading geometry out of a page.

**It runs on the bytes the request already holds.** `pdf.extract` has the upload open;
this walks the same `Page` objects before that context closes. Nothing here reads
`imported_resumes.storage_key`, and nothing may: re-reading the retained original to
derive a capability is the case `tests/unit/test_architecture.py` names as forbidden —
*looking at* the upload is not *deriving from* it.

**`None` is the normal answer, not a failure.** A DOCX has no geometry; a CV set in a
family this image does not carry would resolve to a substitute and render as a document
nobody measured; a page that yields no section headings was not understood well enough to
reproduce. Each returns `None`, and the caller exports on the plain ATS template exactly
as it did before themes existed. This module therefore never raises into the import path.

**Three inference rules were wrong first, and each was measured wrong rather than
reasoned wrong.** They are the load-bearing comments below: the leading is the *lower
quartile* of line deltas (a median lands between the wrapped-line and new-paragraph
populations and compounds into a spurious page break; a mode returns whichever population
is largest, which on a list-heavy CV is the entry spacing); prose and list spacing must be
carried separately (one value put a real CV's following heading 30pt out of place); and
the bottom margin is only measurable when the content reaches the bottom of the page.
"""

from __future__ import annotations

import collections
import itertools
import logging
import re
import statistics
from typing import Any, cast

from pdfplumber.pdf import PDF

from careerhq.domain.schemas.theme import (
    MAX_LABEL_CHARS,
    MAX_LINE_HEIGHT,
    ResumeTheme,
)

logger = logging.getLogger(__name__)

#: pdfplumber reports embedded subsets as `BAAAAA+Poppins-Light`.
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

#: Style token in a PostScript name -> CSS weight. Longest token wins, so
#: "ExtraLight" is not matched as "Light".
_WEIGHTS: dict[str, int] = {
    "Thin": 200,
    "ExtraLight": 200,
    "UltraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Normal": 400,
    "Book": 400,
    "Medium": 400,
    "SemiBold": 600,
    "DemiBold": 600,
    "Bold": 700,
    "ExtraBold": 700,
    "Black": 700,
}
_WEIGHT_TOKENS = sorted(_WEIGHTS, key=len, reverse=True)

#: The weights `ResumeTheme.FontWeight` allows. A measured weight is snapped to the
#: nearest of these, because the theme may only name a face the image actually carries.
_ALLOWED_WEIGHTS = (200, 300, 400, 600, 700)

_PAGE_SIZES: tuple[tuple[str, float, float], ...] = (
    ("A4", 595.276, 841.89),
    ("Letter", 612.0, 792.0),
)

_BULLET_GLYPHS = "•◦▪·"

#: Below this luminance a colour is "black" for accent purposes. Body text is not an
#: accent however slightly off-black it is set.
_ACCENT_MIN_LUMA = 24.0

#: Lines are grouped into one visual row when their `top` values are within this.
_ROW_TOLERANCE_PT = 2.5


def _normalise_font(fontname: str) -> tuple[str, int]:
    """`'BAAAAA+Poppins-Light'` -> `('Poppins', 300)`.

    **The style token is stripped of punctuation before it is matched, and that is not
    cosmetic.** Producers disagree about how to write a two-word weight: the CV this was
    built for carries `Poppins-ExtraLight`, while WeasyPrint embeds the same face as
    `Poppins-Ultra-Light`. Matching the raw string finds `Light` inside `Ultra-Light` and
    reports 300 — which made the extra-light section headings indistinguishable from body
    text, so no headings were found and the whole design came back as `None`. Caught by
    the fixture in `tests/unit/test_resume_theme.py`, which is rendered by WeasyPrint and
    therefore hits the hyphenated spelling.

    Longest token first, so `ExtraLight` is never matched as `Light`.
    """
    base = _SUBSET_PREFIX.sub("", fontname or "")
    family, _, style = base.partition("-")
    condensed = re.sub(r"[^A-Za-z]", "", style).lower()
    for token in _WEIGHT_TOKENS:
        if token.lower() in condensed:
            return family, _WEIGHTS[token]
    return family, 400


def _snap_weight(weight: int) -> int:
    return min(_ALLOWED_WEIGHTS, key=lambda allowed: abs(allowed - weight))


def _to_hex(colour: object) -> str:
    """A pdfplumber colour, in whatever space the PDF used, as `#RRGGBB`."""
    if colour is None:
        return "#000000"
    values: tuple[float, ...]
    if isinstance(colour, (int, float)):
        values = (float(colour),) * 3
    else:
        try:
            values = tuple(float(component) for component in cast("Any", colour))
        except (TypeError, ValueError):
            return "#000000"
    if len(values) == 1:
        values = values * 3
    elif len(values) == 4:  # CMYK
        c, m, y, k = values
        values = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    elif len(values) < 3:
        return "#000000"
    return "#" + "".join(f"{round(max(0.0, min(1.0, v)) * 255):02X}" for v in values[:3])


def _luma(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[index : index + 2], 16) for index in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class _Line:
    """One visual row of characters, with its dominant face."""

    __slots__ = ("bottom", "chars", "colour", "family", "size", "text", "top", "weight", "x0", "x1")

    def __init__(self, chars: list[dict[str, Any]]) -> None:
        self.chars = sorted(chars, key=lambda c: float(c["x0"]))
        inked = [c for c in self.chars if str(c["text"]).strip()]
        self.text = "".join(str(c["text"]) for c in self.chars)
        self.top = min(float(c["top"]) for c in inked)
        self.bottom = max(float(c["bottom"]) for c in inked)
        self.x0 = min(float(c["x0"]) for c in inked)
        self.x1 = max(float(c["x1"]) for c in inked)
        faces = collections.Counter(
            (*_normalise_font(str(c["fontname"])), round(float(c["size"]), 1)) for c in inked
        )
        self.family, self.weight, self.size = faces.most_common(1)[0][0]
        self.colour = collections.Counter(
            _to_hex(c.get("non_stroking_color")) for c in inked
        ).most_common(1)[0][0]


def _build_lines(chars: list[dict[str, Any]]) -> list[_Line]:
    """Cluster characters into visual rows by `top`.

    Rows rather than pdfplumber's `extract_text` lines because a superscript, a
    separator glyph set a point higher, or a right-flushed date must stay on the row a
    reader sees them on — that is what makes "the dates share the employer's line"
    measurable at all.
    """
    buckets: dict[float, list[dict[str, Any]]] = {}
    for char in chars:
        top = float(char["top"])
        for key in buckets:
            if abs(key - top) <= _ROW_TOLERANCE_PT:
                buckets[key].append(char)
                break
        else:
            buckets[top] = [char]
    lines = [_Line(group) for group in (buckets[key] for key in sorted(buckets))]
    return [line for line in lines if line.text.strip()]


def _page_size(width: float, height: float) -> str | None:
    for name, w, h in _PAGE_SIZES:
        if abs(width - w) < 3.0 and abs(height - h) < 3.0:
            return name
    return None


def extract_theme(document: PDF) -> ResumeTheme | None:
    """The design of `document`, or `None` when it cannot be reproduced faithfully.

    Never raises: a theme is an enhancement to an import that must succeed without one.
    """
    try:
        return _extract(document)
    except Exception:  # an unreadable layout must not fail the import
        logger.info("theme extraction found no reproducible design", exc_info=True)
        return None


def _extract(document: PDF) -> ResumeTheme | None:
    if not document.pages:
        return None
    page = document.pages[0]
    width, height = float(page.width), float(page.height)

    size_name = _page_size(width, height)
    if size_name is None:
        return None

    chars = [c for c in page.chars if str(c["text"]).strip()]
    if len(chars) < 200:  # a cover page or a near-empty scan: nothing to learn
        return None

    # -- family: dominant across the page, and it must be one we carry ------
    families = collections.Counter(_normalise_font(str(c["fontname"]))[0] for c in chars)
    family = families.most_common(1)[0][0]
    if family != "Poppins":
        return None

    lines = _build_lines(chars)
    if len(lines) < 8:
        return None

    # -- body: the face covering the most characters -----------------------
    faces = collections.Counter(
        (_normalise_font(str(c["fontname"]))[1], round(float(c["size"]), 1)) for c in chars
    )
    body_weight, body_size = faces.most_common(1)[0][0]
    body_weight = _snap_weight(body_weight)

    # -- margins: the inked bounding box against the page edges ------------
    margin_left = min(float(c["x0"]) for c in chars)
    margin_right = width - max(float(c["x1"]) for c in chars)
    margin_top = min(float(c["top"]) for c in chars)

    # **The bottom margin is only measurable when the content reaches the bottom.**
    # Otherwise the gap below the last line is unused page, not a design choice, and
    # reading it as one produced a 468pt "margin" on a half-full page. There is no way to
    # tell a deliberately deep bottom margin from a short CV, so a plausible measurement
    # is trusted and an implausible one mirrors the top — which is what a page set with
    # symmetric vertical margins actually has.
    measured_bottom = height - max(float(c["bottom"]) for c in chars)
    margin_bottom = (
        measured_bottom if margin_top * 0.5 <= measured_bottom <= margin_top * 2.0 else margin_top
    )

    # -- accent: the most common colour that is not near-black -------------
    # **A local, not a theme field.** The colours the renderer uses are read off the
    # rows that carry them (`name_color`, `section_heading_color`); this is only the
    # discriminator that tells a heading apart from body text below.
    colours = collections.Counter(_to_hex(c.get("non_stroking_color")) for c in chars)
    accents = [value for value, _ in colours.most_common() if _luma(value) > _ACCENT_MIN_LUMA]
    accent = accents[0] if accents else "#000000"

    # -- name: the largest row on the page ---------------------------------
    name_line = max(lines, key=lambda line: (line.size, -line.top))
    name_centre_offset = abs(((name_line.x0 + name_line.x1) / 2) - width / 2)
    name_alignment = "center" if name_centre_offset < 12.0 else "left"

    # -- section headings --------------------------------------------------
    # All-uppercase **and** a face other than the body's **and** the accent colour.
    # Any one of those alone is common in ordinary text; together they have picked out
    # exactly the real headings on every document measured.
    def is_heading(line: _Line) -> bool:
        letters = [c for c in line.text if c.isalpha()]
        return (
            bool(letters)
            and all(c.isupper() for c in letters)
            and (_snap_weight(line.weight), line.size) != (body_weight, body_size)
            and line.colour == accent
        )

    headings = [line for line in lines if is_heading(line)]
    if not headings:
        return None
    heading = headings[0]

    def gap_before(line: _Line) -> float:
        earlier = [other.bottom for other in lines if other.bottom <= line.top + 0.5]
        return line.top - max(earlier) if earlier else 0.0

    def gap_after(line: _Line) -> float:
        later = [other.top for other in lines if other.top >= line.bottom - 0.5]
        return min(later) - line.bottom if later else 0.0

    heading_before = statistics.median([gap_before(line) for line in headings])
    heading_after = statistics.median([gap_after(line) for line in headings])

    # -- the header block: rows after the name until the first at the margin
    # A centred header is inset on both sides; body copy starts at the margin.
    contact_lines: list[_Line] = []
    for line in (other for other in lines if other.top > name_line.bottom):
        if line.x0 <= margin_left + 2.0:
            break
        contact_lines.append(line)
    if contact_lines:
        offsets = [abs(((line.x0 + line.x1) / 2) - width / 2) for line in contact_lines]
        contact_alignment = "center" if statistics.median(offsets) < 20.0 else "left"
        contact_size = min(line.size for line in contact_lines)
    else:
        contact_alignment, contact_size = "left", body_size

    # -- roles: rows larger than the body that are not the name or a heading
    role_lines = [
        line
        for line in lines
        if line.size > body_size and line is not name_line and not is_heading(line)
    ]
    if role_lines:
        role_size = statistics.median([line.size for line in role_lines])
        role_weight = _snap_weight(
            collections.Counter(line.weight for line in role_lines).most_common(1)[0][0]
        )
    else:
        role_size, role_weight = body_size, 600

    # -- dates: a run flush to the text's right edge sharing a row with a left run
    right_edge = width - margin_right
    date_runs: list[list[dict[str, Any]]] = []
    for line in lines:
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for char in line.chars:
            if current and float(char["x0"]) - float(current[-1]["x1"]) > 8.0:
                groups.append(current)
                current = []
            current.append(char)
        if current:
            groups.append(current)
        if len(groups) >= 2:
            last = groups[-1]
            if abs(float(last[-1]["x1"]) - right_edge) < 6.0 and float(last[0]["x0"]) > width / 2:
                date_runs.append(last)
    if date_runs:
        date_alignment = "right"
        date_size = round(statistics.median([float(run[0]["size"]) for run in date_runs]), 1)
        date_weight = _snap_weight(
            collections.Counter(
                _normalise_font(str(run[0]["fontname"]))[1] for run in date_runs
            ).most_common(1)[0][0]
        )
    else:
        date_alignment, date_size, date_weight = "inline", body_size, body_weight

    # -- bullets -----------------------------------------------------------
    bullet_lines = [
        line
        for line in lines
        if line.text.lstrip()
        and line.text.lstrip()[0] in _BULLET_GLYPHS
        and line.x0 < width / 2
        and any(c.isalnum() for c in line.text)
    ]
    if bullet_lines:
        marker_indent = statistics.median([line.x0 for line in bullet_lines]) - margin_left
        wrapped = [
            line
            for line in lines
            if margin_left + 4.0 < line.x0 < width / 2
            and line not in bullet_lines
            and line.size <= body_size + 0.5
        ]
        text_indent = (
            statistics.median([line.x0 for line in wrapped]) - margin_left
            if wrapped
            else marker_indent
        )
    else:
        marker_indent = text_indent = 0.0
    marker_indent = max(0.0, marker_indent)
    text_indent = max(marker_indent, text_indent)

    # -- leading and the two spacings --------------------------------------
    body_lines = [line for line in lines if abs(line.size - body_size) < 0.3]
    deltas = [
        later.top - earlier.top
        for earlier, later in itertools.pairwise(body_lines)
        if 0 < later.top - earlier.top < body_size * MAX_LINE_HEIGHT
    ]
    if not deltas:
        return None
    # **The lower quartile — and both simpler rules were tried and measured wrong.**
    # These deltas are two or three populations: lines wrapped inside one paragraph (the
    # leading), lines starting a new paragraph, and entries in a list section. Only the
    # first is the leading, and it is always the tightest.
    #
    #   - The *median* lands between the populations: on a real CV it read 12.55pt
    #     against a true 12.0pt, and 0.55pt compounded over forty lines produced a page
    #     break the original does not have.
    #   - The *mode* is the largest population, which is only the leading when wrapped
    #     lines outnumber entries. On a list-heavy CV it returned 21.0pt — the Skills
    #     spacing — and read the leading as 2.1.
    #
    # The lower quartile is the tightest *recurring* delta, so it survives both shapes
    # and the rounding spread that row-clustering introduces. Measured at exactly 12.0pt
    # on both documents this was drilled against.
    ordered = sorted(deltas)
    quartile = statistics.quantiles(ordered, n=4)[0] if len(ordered) >= 4 else ordered[0]
    leading = round(quartile * 2) / 2
    if leading <= 0:
        return None

    # **Prose and list spacing are separate, because one scalar cannot serve both.**
    # A document sets wrapped prose tighter than it sets one-line entries; measured,
    # 2pt against 8pt. Collapsing them put the next heading 30pt out of place.
    # The 1pt floor keeps rounding jitter around the leading from reading as a gap.
    above = collections.Counter(round(delta * 2) / 2 for delta in deltas if delta > leading + 1.0)
    repeated = sorted(value for value, count in above.items() if count >= 2)
    paragraph_space = round(repeated[0] - leading, 1) if repeated else 0.0
    list_space = round(repeated[-1] - leading, 1) if repeated else paragraph_space

    # -- label emphasis: the run before the first colon of an entry --------
    # Positional, so a Tailor rewrite of the value cannot invalidate it.
    label_weights: list[int] = []
    for line in lines:
        index = line.text.find(":")
        if not 0 < index <= MAX_LABEL_CHARS:
            continue
        before = [c for c in line.chars[:index] if str(c["text"]).strip()]
        after = [c for c in line.chars[index + 1 :] if str(c["text"]).strip()]
        if not before or not after:
            continue
        heavy = collections.Counter(_normalise_font(str(c["fontname"]))[1] for c in before)
        light = collections.Counter(_normalise_font(str(c["fontname"]))[1] for c in after)
        label_weight = heavy.most_common(1)[0][0]
        if label_weight > light.most_common(1)[0][0]:
            label_weights.append(_snap_weight(label_weight))
    label_emphasis = (
        collections.Counter(label_weights).most_common(1)[0][0] if len(label_weights) >= 2 else None
    )

    return ResumeTheme(
        page_size=cast("Any", size_name),
        margin_top_pt=round(margin_top, 1),
        margin_right_pt=round(margin_right, 1),
        margin_bottom_pt=round(margin_bottom, 1),
        margin_left_pt=round(margin_left, 1),
        font_family="Poppins",
        body_font_size_pt=body_size,
        body_font_weight=cast("Any", body_weight),
        body_line_height=round(leading / body_size, 3),
        name_font_size_pt=name_line.size,
        name_font_weight=cast("Any", _snap_weight(name_line.weight)),
        name_color=name_line.colour,
        name_alignment=cast("Any", name_alignment),
        contact_font_size_pt=contact_size,
        contact_alignment=cast("Any", contact_alignment),
        section_heading_font_size_pt=heading.size,
        section_heading_font_weight=cast("Any", _snap_weight(heading.weight)),
        section_heading_color=heading.colour,
        section_heading_transform="uppercase",
        section_heading_space_before_pt=round(max(0.0, heading_before), 1),
        section_heading_space_after_pt=round(max(0.0, heading_after), 1),
        role_font_size_pt=role_size,
        role_font_weight=cast("Any", role_weight),
        date_alignment=cast("Any", date_alignment),
        date_font_size_pt=date_size,
        date_font_weight=cast("Any", date_weight),
        bullet_glyph="•",
        bullet_marker_indent_pt=round(marker_indent, 1),
        bullet_text_indent_pt=round(text_indent, 1),
        paragraph_space_pt=max(0.0, paragraph_space),
        list_item_space_pt=max(0.0, list_space),
        label_emphasis_weight=cast("Any", label_emphasis),
    )


__all__ = ["extract_theme"]
