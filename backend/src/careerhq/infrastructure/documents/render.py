"""WeasyPrint behind a boundary (D7). Content in, PDF bytes out.

**The only module permitted to import WeasyPrint**, for the same reason
`FastEmbedSource` is the only one permitted to import fastembed: the layers above must
not be able to reach a rendering engine except through a function that takes a
`ResumeDocument` and returns bytes.

**The template is ATS-safe by construction, not by review** (T034, FR-018). Single
column, standard headings, contact details in the **body**, and no table, no `float`, no
`position`, no image, no icon and no background. Each of those is one of the six
assertions `tests/unit/test_export_ats.py` checks with an independent extractor, and each
was drilled by breaking this file and watching the assertion name the break.

**`font-variant-ligatures: none` is defensive, and the drill could NOT prove it
load-bearing — recorded rather than claimed.** The hazard is real in general: a shaper
that substitutes one glyph for `ffi` extracts as `ineﬃciencies`, and an employer's parser
searching for `inefficiencies` does not match — invisible in a viewer, fatal in a résumé.
But removing this property changed nothing here, and neither did forcing a font that does
ligate (Georgia): WeasyPrint maps the glyph back through the PDF's `ToUnicode` table, so
extraction stays correct either way. The property is kept because it costs nothing and
the guarantee should not depend on a `ToUnicode` table staying correct, **not** because a
drill demonstrated it. `tests/unit/test_export_ats.py` asserts the outcome regardless.

**The font is a resolved fallback, not a chosen one.** "DejaVu Sans" is not installed on
macOS, so the host renders in **Verdana**; `python:3.12-slim` carries neither and will
resolve to something else again. Two environments therefore produce different bytes from
identical content, which is a **T032** problem (byte-determinism) and is recorded there.

**Byte-determinism is pinned here, and the reason is a measurement rather than a
theory.** FR-031 requires two renders of identical content on one runtime to be
byte-identical. They were not: on Linux, `fontTools` stamps the embedded font subset's
`head.modified` with the **wall-clock time of the render**, so two renders landing in
different seconds produced different fonts, different compressed lengths, and a different
file. Measured in the production image: **five distinct hashes from eight consecutive
renders of the same document.**

The three differing bytes were all consequences of one value — `head.modified`, plus the
two checksums derived from it (`head.checkSumAdjustment` and the `head` entry in the sfnt
table directory). Nothing else moved: this renderer, object ordering and compression were
never involved, and the PDF itself carries no `/CreationDate`, `/ModDate` or `/ID` at
WeasyPrint 69 — T032 measured that correctly and it still holds. The timestamp it missed
was one level down, inside the font.

**T032 concluded "already byte-identical" from the one environment where that is true.**
On macOS the resolved font is not restamped and keeps its own 2007 date, so the test
passed on the dev host while production and CI were nondeterministic on every render more
than a second apart. The determinism test now separates its two renders by over a second
for exactly that reason.
"""

from __future__ import annotations

import html
import logging
import os
import pathlib

# Bound to a private name **so the boundary is real rather than conventional** (T035).
# As `HTML`, `from careerhq.infrastructure.documents.render import HTML` worked, and any
# caller could drive the engine directly while the import guard in
# `tests/unit/test_architecture.py` stayed green — it looks for modules importing
# *weasyprint*, and such a caller imports this module instead.
from weasyprint import HTML as _HTML

from careerhq.domain.schemas.document import ResumeDocument, ResumeSection
from careerhq.domain.schemas.theme import MAX_LABEL_CHARS, ResumeTheme

logger = logging.getLogger(__name__)

#: Font files this module may reference, bundled rather than installed.
#:
#: **A family that is merely named resolves to whatever fontconfig has.** That is how the
#: plain template ends up in Verdana on macOS and something else again on
#: `python:3.12-slim` — recorded above, and harmless there only because the plain
#: template's guarantee is byte-determinism *within* one runtime. A theme makes a
#: stronger claim: it says the document looks like the CV the owner uploaded. So its
#: faces travel with the code, and `ResumeTheme.font_family` is a whitelist of what is
#: actually in this directory rather than a string the caller chooses.
_FONT_DIR = pathlib.Path(__file__).parent / "fonts"

#: The weights `ResumeTheme.FontWeight` permits, and the file carrying each.
_FONT_FILES: dict[int, str] = {
    200: "Poppins-ExtraLight.ttf",
    300: "Poppins-Light.ttf",
    400: "Poppins-Regular.ttf",
    600: "Poppins-SemiBold.ttf",
    700: "Poppins-Bold.ttf",
}

#: Pins the timestamp `fontTools` writes into the embedded font subset (FR-031).
#:
#: **`SOURCE_DATE_EPOCH` is the reproducible-builds convention**, honoured by
#: `fontTools.misc.timeTools`, which is what turns `head.modified` from "now" into a
#: constant. Set here rather than in the Dockerfile, CI and `conftest.py`, because the
#: renderer is the boundary that owns this guarantee (D7) and three environment files are
#: three places to forget it — the failure being silent and only visible on a re-export.
#:
#: **Zero, deliberately.** The field describes when a *font* was modified, which says
#: nothing about the résumé being rendered; pinning it to the Unix epoch makes it
#: obviously synthetic rather than a date someone might read as provenance.
#:
#: `setdefault`, so a build system that pins its own value keeps it.
#:
#: **Below the imports, and that is checked rather than assumed.**
#: `fontTools.misc.timeTools.timestampNow()` reads the variable when a font is
#: *saved*, not when the module is imported — so this does not need to precede the
#: WeasyPrint import, and putting it there would only earn two `E402` suppressions.
#: If a future version snapshots it at import instead, this has to move back up.
PINNED_SOURCE_DATE_EPOCH = "0"
os.environ.setdefault("SOURCE_DATE_EPOCH", PINNED_SOURCE_DATE_EPOCH)

#: No tables, no columns, no floats, no images, no icons, no backgrounds — FR-018 in CSS.
#: Points rather than pixels because the output medium is paper, and a named generic
#: family so the document does not depend on a font this container may not carry.
_CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "DejaVu Sans", sans-serif;
  font-size: 10.5pt;
  line-height: 1.45;
  color: #000;
  /* Load-bearing: a ligature glyph does not extract as the letters it replaces. */
  font-variant-ligatures: none;
}
h1 { font-size: 16pt; font-weight: bold; margin-bottom: 2pt; }
.contact { font-size: 9.5pt; margin-bottom: 10pt; }
/* **No rule under the heading, and no decoration anywhere** (T034, FR-018's "no
   graphics"). A border-bottom looks like a hairline but WeasyPrint paints it as two
   filled rectangles spanning the whole heading box, which is indistinguishable from a
   shaded panel to anything inspecting the page — so keeping it would have made "no
   filled panels" unassertable. It bought nothing a parser can read: separation comes
   from weight, capitals and space, which cost no vector objects at all. The document is
   now text and nothing else, and `test_export_template.py` asserts exactly that. */
h2 {
  font-size: 11pt;
  font-weight: bold;
  text-transform: uppercase;
  margin-top: 12pt;
  margin-bottom: 4pt;
}
p.line { margin-bottom: 3pt; }
/* **A role block, and the reason it is three elements rather than one** (T051). The
   corpus's ATS rule requires the employer and the job title to be separate readable
   text, because a parser extracts "current employer" and "current title" as distinct
   fields and a combined line hands it one string where it expects two. Separation is
   therefore structural — three block elements — and not merely visual.

   Weight and space do the visual work, as they do for `h2`: no rule, no border, no
   background. `test_export_template.py` asserts the document is text and nothing else,
   and a border-bottom here would paint filled rectangles and break that. */
p.role-employer { font-weight: bold; margin-top: 7pt; }
p.role-title { margin-bottom: 1pt; }
p.role-dates { font-size: 9.5pt; margin-bottom: 3pt; }
"""


def _render_html(document: ResumeDocument) -> str:
    """The document as one column of block elements.

    Everything user-supplied goes through `html.escape`. A profile is user data and an
    ampersand in an employer's name must not become markup — and this is the one place
    in the codebase where profile text is interpolated into a markup document.
    """
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(document.full_name)}</h1>",
    ]
    if document.contact:
        joined = " · ".join(html.escape(fragment) for fragment in document.contact)
        parts.append(f"<div class='contact'>{joined}</div>")
    for section in document.sections:
        parts.append(f"<h2>{html.escape(section.heading)}</h2>")
        for group in section.groups:
            # A group with no role is a plain run of lines — every section but
            # Experience, and every version predating the T051 snapshot.
            if group.role is not None:
                parts.append(f"<p class='role-employer'>{html.escape(group.role.employer)}</p>")
                parts.append(f"<p class='role-title'>{html.escape(group.role.title)}</p>")
                if group.role.dates:
                    parts.append(f"<p class='role-dates'>{html.escape(group.role.dates)}</p>")
            for line in group.lines:
                parts.append(f"<p class='line'>{html.escape(line)}</p>")
    parts.append("</body></html>")
    return "".join(parts)


def _font_faces(family: str) -> str:
    """`@font-face` for every bundled weight, by absolute `file://` URL.

    Missing files are skipped rather than raising: a face that is absent degrades to the
    nearest one WeasyPrint has, which is a worse-looking document, where raising here
    would be a failed export of a résumé somebody is waiting for.
    """
    rules = []
    missing = []
    for weight, filename in _FONT_FILES.items():
        path = _FONT_DIR / filename
        if path.is_file():
            rules.append(
                f"@font-face {{ font-family: '{family}'; font-weight: {weight}; "
                f"font-style: normal; src: url('{path.as_uri()}') format('truetype'); }}"
            )
        else:
            missing.append(filename)
    if missing:
        # **Logged, because the failure is otherwise invisible.** A skipped face degrades
        # to whatever fontconfig resolves, which changes the rendered bytes and looks
        # merely "a bit wrong" — and two renders in the same environment fall back
        # identically, so the determinism test stays green. The likeliest cause is a
        # build that ships the package without its data files.
        logger.warning(
            "bundled font files are missing; themed exports will render in a fallback face",
            extra={"family": family, "missing": missing, "font_dir": str(_FONT_DIR)},
        )
    return "\n".join(rules)


def _themed_css(theme: ResumeTheme) -> str:
    """FR-018's structural guarantees, restated in the imported CV's typography.

    **Every clause the plain template refuses, this refuses too**: no table, no
    `column-count`, no `float`, no `position`, no image, no background, no border and no
    `letter-spacing`. What changes is family, size, weight, colour and space — none of
    which any ATS assertion reads. The one addition is a flex row for a right-flushed
    date, and flex is used precisely *because* it leaves DOM order alone: the employer
    still precedes the date in the content stream, so extraction order is unchanged and
    the page still measures as a single column (no gutter — a body line spans the full
    measure on almost every row).
    """
    marker_width = theme.bullet_marker_width_pt()
    label = (
        f"span.label {{ font-weight: {theme.label_emphasis_weight}; }}"
        if theme.label_emphasis_weight is not None
        else ""
    )
    return f"""
{_font_faces(theme.font_family)}
@page {{ size: {theme.page_size};
         margin: {theme.margin_top_pt}pt {theme.margin_right_pt}pt
                 {theme.margin_bottom_pt}pt {theme.margin_left_pt}pt; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: '{theme.font_family}', sans-serif;
  font-size: {theme.body_font_size_pt}pt;
  font-weight: {theme.body_font_weight};
  line-height: {theme.body_line_height};
  color: #000;
  /* Load-bearing for the same reason as the plain template. */
  font-variant-ligatures: none;
}}
h1.name {{
  font-size: {theme.name_font_size_pt}pt;
  font-weight: {theme.name_font_weight};
  color: {theme.name_color};
  text-align: {theme.name_alignment};
  line-height: 1.15;
}}
div.contact {{
  font-size: {theme.contact_font_size_pt}pt;
  text-align: {theme.contact_alignment};
  margin-top: 3pt;
}}
h2.section {{
  font-size: {theme.section_heading_font_size_pt}pt;
  font-weight: {theme.section_heading_font_weight};
  color: {theme.section_heading_color};
  text-transform: {theme.section_heading_transform};
  margin-top: {theme.section_heading_space_before_pt}pt;
  margin-bottom: {theme.section_heading_space_after_pt}pt;
}}
p.line {{ margin-bottom: {theme.paragraph_space_pt}pt; }}
p.line.list {{ margin-bottom: {theme.list_item_space_pt}pt; }}
{label}
div.role {{ margin-top: {theme.list_item_space_pt}pt; }}
div.role-row {{ display: flex; justify-content: space-between; align-items: baseline; }}
p.role-employer {{ font-size: {theme.role_font_size_pt}pt; font-weight: {theme.role_font_weight}; }}
p.role-dates {{
  font-size: {theme.date_font_size_pt}pt;
  font-weight: {theme.date_font_weight};
  white-space: nowrap;
}}
p.role-title {{
  font-size: {theme.role_font_size_pt}pt;
  font-weight: {theme.role_font_weight};
  margin-bottom: 3pt;
}}
/* A hanging indent built from padding and a negative margin, **not**
   `text-indent`: WeasyPrint applied that a second time to the marker box and put the
   glyph a full marker-width left of where the source CV has it. */
p.bullet {{
  padding-left: {theme.bullet_text_indent_pt}pt;
  margin-bottom: {theme.paragraph_space_pt}pt;
}}
p.bullet::before {{
  content: "{theme.bullet_glyph}";
  display: inline-block;
  width: {marker_width}pt;
  margin-left: -{marker_width}pt;
}}
"""


def _themed_line(text: str, section: ResumeSection, theme: ResumeTheme) -> str:
    """One body line, with the label before its first colon set in the heavier face.

    **Positional emphasis only, and that is the whole of the design.** The label is
    "whatever precedes the first colon of a list entry", so nothing is stored about which
    words the owner considered important and no markup enters item text — which means a
    Tailor rewrite of the value cannot leave a bold span attached to words that are gone.
    Author-chosen keyword emphasis is not preserved; that is recorded as a limitation,
    not solved here.

    **The extracted text is byte-for-byte what it would be without this.** A `<span>`
    changes the face, not the characters or their order, so FR-017's assertion sees the
    same document either way.
    """
    if section.style != "list":
        return f"<p class='line'>{html.escape(text)}</p>"
    if theme.label_emphasis_weight is not None:
        # Split first, escape after: a long label is a long *label*, not a short one
        # whose ampersand became five characters.
        label, separator, rest = text.partition(":")
        if separator and len(label) <= MAX_LABEL_CHARS:
            return (
                f"<p class='line list'><span class='label'>{html.escape(label)}:</span>"
                f"{html.escape(rest)}</p>"
            )
    return f"<p class='line list'>{html.escape(text)}</p>"


def _render_themed_html(document: ResumeDocument, theme: ResumeTheme) -> str:
    """The same document, the same order, in the imported CV's typography.

    **Deliberately a second emitter rather than a branch inside `_render_html`.** The
    plain path's output must stay byte-for-byte what it was: FR-021 records a checksum
    over an exported document and FR-031 requires a re-render to reproduce it, so a
    conditional threaded through the untenanted path is a byte-drift risk on documents
    that have already been sent. `test_export_themed.py` pins the plain path's markup to a
    hash so an edit to it cannot pass unnoticed, and asserts both emitters carry the same
    **approved lines** in the same order.

    **The role heading is where the two deliberately differ, and that is pinned
    separately.** Plain emits employer → title → dates as three stacked blocks; this emits
    employer → dates on one flex row, then the title. `lines_in_order()` excludes role
    context by design (it is document structure, not an approved item), so the
    same-lines test cannot see this — `test_the_themed_role_row_orders_employer_dates_then_title`
    states it directly instead.
    """
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<style>{_themed_css(theme)}</style></head><body>",
        f"<h1 class='name'>{html.escape(document.full_name)}</h1>",
    ]
    if document.contact:
        joined = f" {theme.bullet_glyph} ".join(
            html.escape(fragment) for fragment in document.contact
        )
        parts.append(f"<div class='contact'>{joined}</div>")
    for section in document.sections:
        if section.heading:
            parts.append(f"<h2 class='section'>{html.escape(section.heading)}</h2>")
        for group in section.groups:
            if group.role is not None:
                parts.append("<div class='role'><div class='role-row'>")
                parts.append(f"<p class='role-employer'>{html.escape(group.role.employer)}</p>")
                if group.role.dates:
                    parts.append(f"<p class='role-dates'>{html.escape(group.role.dates)}</p>")
                parts.append("</div>")
                parts.append(f"<p class='role-title'>{html.escape(group.role.title)}</p></div>")
            for line in group.lines:
                if group.role is not None:
                    parts.append(f"<p class='bullet'>{html.escape(line)}</p>")
                else:
                    parts.append(_themed_line(line, section, theme))
    parts.append("</body></html>")
    return "".join(parts)


def render_resume_pdf(document: ResumeDocument, theme: ResumeTheme | None = None) -> bytes:
    """Render one résumé to PDF bytes, in `theme` or on the plain ATS template.

    Takes content, not a `ResumeVersion` and not a session: the renderer has no idea what
    a version is, which is what keeps the ATS assertions checkable without a database and
    keeps WeasyPrint out of every layer above this one.

    **`theme=None` is the default and renders exactly what this function rendered before
    themes existed** — same markup, same CSS, same bytes. Every import that yields no
    recoverable design, every DOCX, and every profile created before slice 011 takes that
    path, so it is the common case rather than a fallback.
    """
    markup = _render_html(document) if theme is None else _render_themed_html(document, theme)
    rendered = _HTML(string=markup).write_pdf()
    if rendered is None:  # pragma: no cover - write_pdf returns bytes when no target given
        raise RuntimeError("the renderer produced no bytes")
    return bytes(rendered)


__all__ = ["render_resume_pdf"]
