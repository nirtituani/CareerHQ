# Resume Builder — Reference Experience

> Description of the Teal / Gloat resume builder, captured from screenshots reviewed during
> design. This is the target for the **deferred** from-scratch builder
> (`docs/01` §12, ADR-013). Written down because the screenshots themselves are not in the
> repository, and "build something like Teal" is not a specification.

---

## Why it is deferred

Counting what follows: roughly **forty presentation settings** plus a guided editor, each needing
a control, state, persistence, and a live preview that re-renders correctly on every change. Weeks
of interface work that demonstrates none of the course requirements — no agent, no memory, no
tools, no RAG, no evaluation.

Version 1 populates the Professional Profile by **importing an existing CV** instead. The parsed
data model is identical, so the builder later becomes a pure interface addition with no migration
(ADR-013).

---

## Top-level structure

A single document workspace with five tabs, a persistent live preview on the right, and
`Export PDF`:

```
Content Editor | Designer | Analyzer (10) | Job Matcher (!) | Cover Letter
```

The badge on `Analyzer` is an issue count; the `!` on `Job Matcher` flags an unaddressed job.

A home screen lists resumes as cards — one per company (`Nir Tituani - CV - GLOAT`,
`- MYHERITAGE`, `- APPSFLYER`, …) each with a **Match a job** action and a last-edited date. Entry
points: `New Resume`, `Start from job description`, `Start from template`, `New Cover Letter`.

> `Start from job description` is worth noting: it is the agent composing a resume from nothing
> but a job description plus the knowledge pool. A stronger demonstration than tailoring an
> existing document, and the same underlying agent.

---

## Content Editor

Sections, each collapsible with add and overflow actions:

Contact Information · Target Title · Professional Summary · Work Experience · Education ·
Skills & Interests · Certifications · Awards & Scholarships · Projects · Volunteering & Leadership ·
Publications

**Every item carries a checkbox.** Not just sections — individual contact fields, the target
title, each summary paragraph, each company, each position, each date range, and **each bullet**.
Checked items appear in this version; unchecked ones remain in the profile but are excluded here.

Skills are grouped into named categories (`Backend Development`, `Programming Languages`,
`Backend & Messaging`, `Databases`) with drag-to-assign between them.

Per-item hover actions: AI rewrite, edit, duplicate, favourite, delete. Bullets have drag handles.

> This checkbox model is why `docs/03` carries an `ItemInclusion` value object rather than
> section-level visibility — and it doubles as the approval interface: the agent proposes, the
> user sees checkboxes flip alongside the diff, and approves item by item.

---

## Designer

Four sub-tabs.

**Presentation** — template library with thumbnails and a saved-templates row; font family, line
height, list line height, accent colour from a swatch palette; header alignment (left / centre /
right), date alignment (left / right), location alignment (left / right), skills layout (three
variants).

**Sections** — section order via drag, and section renaming.

**Settings** — Work Experience display rules: show locations by company / position / none; show
experience grouped by company or by position; show dates by company / position / both.

**Advanced** — bullet glyph (`•`, `–`, `»`, `→`); separator glyph (`•`, `–`, `,`, `|`); five text
sizes (body 10pt, primary heading 11pt, secondary heading 11pt, section titles 10pt, full name
18pt); six text weights (extra light → semi-bold, per element); text transformations; five
vertical spacing controls (between sections 6pt, titles and content 8pt, primary and secondary
headings 2pt, content blocks 12pt, list items 4pt); three border controls (above header, below
header, section titles).

---

## What Version 1 ships instead

**One template.** Single-column, ATS-safe, well designed. `ResumeLayout` in `docs/03` already
carries the fields a designer surface would need — font family, sizes, spacing, accent colour,
page size, maximum page count — so adding the panel later is an interface change, not a schema
change.

The parts of this reference that **did** make Version 1, because they are structural rather than
presentational:

- Per-item inclusion (`ItemInclusion`, FR-032)
- Section order and visibility (`ResumeSection`)
- One document per company, frozen once submitted (ADR-012)
- Match scoring against a job description (FR-010)
