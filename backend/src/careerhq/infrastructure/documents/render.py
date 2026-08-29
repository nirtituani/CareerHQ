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
import os

# Bound to a private name **so the boundary is real rather than conventional** (T035).
# As `HTML`, `from careerhq.infrastructure.documents.render import HTML` worked, and any
# caller could drive the engine directly while the import guard in
# `tests/unit/test_architecture.py` stayed green — it looks for modules importing
# *weasyprint*, and such a caller imports this module instead.
from weasyprint import HTML as _HTML

from careerhq.domain.schemas.document import ResumeDocument

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


def render_resume_pdf(document: ResumeDocument) -> bytes:
    """Render one résumé to PDF bytes.

    Takes content, not a `ResumeVersion` and not a session: the renderer has no idea what
    a version is, which is what keeps the ATS assertions checkable without a database and
    keeps WeasyPrint out of every layer above this one.
    """
    rendered = _HTML(string=_render_html(document)).write_pdf()
    if rendered is None:  # pragma: no cover - write_pdf returns bytes when no target given
        raise RuntimeError("the renderer produced no bytes")
    return bytes(rendered)


__all__ = ["render_resume_pdf"]
