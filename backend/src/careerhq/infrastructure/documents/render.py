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

**Byte-determinism is NOT established here — that is T032**, with T035's metadata and
timestamp pinning. This renderer currently emits whatever creation date WeasyPrint
chooses, so two renders of identical content differ. Deliberate: pinning it without the
test that proves it is how a "stable checksum" ends up unstable in a way nobody notices
until a re-export.
"""

from __future__ import annotations

import html

# Bound to a private name **so the boundary is real rather than conventional** (T035).
# As `HTML`, `from careerhq.infrastructure.documents.render import HTML` worked, and any
# caller could drive the engine directly while the import guard in
# `tests/unit/test_architecture.py` stayed green — it looks for modules importing
# *weasyprint*, and such a caller imports this module instead.
from weasyprint import HTML as _HTML

from careerhq.domain.schemas.document import ResumeDocument

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
        for line in section.lines:
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
