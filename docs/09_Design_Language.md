# CareerHQ — Design Language

The implementation is [`frontend/src/app/globals.css`](../frontend/src/app/globals.css). This
document is the argument behind it: what was decided, and what it rules out.

Written before slice 003 because that slice is the first with substantial interface — an
applications table at real density, an application detail view, and a CV review screen that is
genuinely hard. Slices 001 and 002 shipped a login page and a nearly empty dashboard, which is why
this document did not exist until now.

---

## 1. The direction

**Editorial instrument.** CareerHQ holds a person's career history and asks them to approve claims
about their own professional identity. That is a deliberative act, so the interface should read as
*considered and precise* — closer to a well-made reference work than to a startup dashboard.

Three commitments follow, and everything else is downstream of them.

1. **Data is quoted, not styled.** Dates, identifiers, confidence values and provenance labels are
   set in monospace. The typeface is doing semantic work: it marks the difference between what the
   system is *saying* and what it is *reporting verbatim*.
2. **Warmth comes from the serif, and only from the serif.** Page titles, the wordmark and large
   figures use Fraunces. The subject is someone's working life, and an interface entirely in
   technical sans reads colder than the subject deserves. Everywhere else, restraint.
3. **Colour is never the only carrier of meaning.** Non-negotiable, and enforced by the token
   layer rather than by review — see §5.

### What this rules out

Purple-gradient hero panels; large friendly illustrations; celebratory microcopy; card grids where
a table is correct; Inter. A user opening this screen has often just been rejected. The interface
should be calm and useful, never chipper.

---

## 2. Typography

| Role | Face | Why |
|---|---|---|
| Display | **Fraunces** | A variable serif with genuine character — optical-size and "wonk" axes. Used sparingly: page titles, wordmark, the four stat figures. Supplies the warmth in commitment 2 |
| UI / body | **IBM Plex Sans** | Drawn for technical work and legible at the small sizes a 96-row table needs. Unlike Inter it has a voice — the double-storey `g`, the flat-sided `a` |
| Data | **IBM Plex Mono** | Same superfamily, so it sits beside body text without argument. Carries commitment 1 |

Wired through `next/font/google` in `layout.tsx`, exposing `--font-fraunces`, `--font-plex-sans`
and `--font-plex-mono`. The `@theme` block maps them to `--font-display` / `--font-sans` /
`--font-mono`, each with an inline fallback so an unwired variable degrades instead of dropping
`font-family` entirely.

### Scale

Sparse on purpose. Six sizes is enough, and a scale nobody can enumerate is a scale nobody applies
consistently.

| Token | Size / leading | Use |
|---|---|---|
| `text-xs` | 12 / 16 | Provenance labels, table metadata, confidence values |
| `text-sm` | 14 / 20 | **The workhorse.** Table cells, form labels, most UI |
| `text-base` | 16 / 26 | Body prose, job description text |
| `text-lg` | 18 / 26 | Section headings, card titles |
| `text-2xl` | 24 / 30 | Page titles *(display)* |
| `text-4xl` | 36 / 40 | Stat figures *(display, tabular)* |

**Every numeric column uses `.tabular`** (`font-variant-numeric: tabular-nums`). Proportional
figures make a column of dates or percentages look misaligned, which reads as a rendering bug.

---

## 3. Colour

### Brand

Deep teal, carried from slice 001 and refined — hue nudged off pure cyan to 186, chroma raised
through the mid range. It is the interactive colour: links, focus, primary actions, and the
"corrected" provenance rule. It is *not* decoration.

### Outcome colours

One per normalized status. These appear ~96 times on one screen, so they are deliberately
low-drama; a palette that shouts at that frequency is unusable.

| Normalized status | Token | Colour |
|---|---|---|
| `wishlist` | `--color-outcome-wishlist` | Amber — not yet acted on |
| `applied` | `--color-outcome-applied` | Brand teal — in flight |
| `interviewing` | `--color-outcome-interviewing` | Violet — the good part |
| `offer` | `--color-outcome-offer` | Green — the best part |
| `rejected`, `ghosted`, `withdrawn` | `--color-outcome-closed` | **Neutral grey** |
| `other` | `--color-outcome-other` | Neutral grey |

> **A rejected application is not an error.** It is among the commonest outcomes of a job search —
> in the reference data, 63 of 96 — and painting a third of the list red would make an ordinary
> week look like a catastrophe. Outcome colours are neutral at the closed end. Red is reserved for
> things that actually broke.
>
> The existing JobTracker already had this instinct right, using grey for `Rejected`. It is worth
> stating explicitly so it is not "corrected" later by someone reaching for semantic red.

### Signal colours

Reserved, and never used for outcomes.

- `--color-attention` (amber) — low confidence, rows needing a look
- `--color-failure` (red) — extraction failed, upload rejected, request errored
- `--color-fixture` (magenta) — **canned demo data.** Loud on purpose: fixture content must never
  be mistaken for a real extraction, so it gets a colour that appears nowhere else

### Surfaces

Light is the default and was designed first — this is a daylight tool used for long sessions. Dark
follows `prefers-color-scheme`. The ground is faintly cool paper rather than pure white; `--surface`
lifts cards and table bodies off it; `--surface-sunken` recesses wells, quoted job description text
and code.

---

## 4. Density and spacing

The applications table is a **reading surface, not a form**.

- Row height `--spacing-row` (44px) — dense but scannable
- Reviewed-and-collapsed import items `--spacing-row-compact` (32px)
- **Hairline rules, no zebra striping.** Alternating fills fight with status pills and provenance
  rules, and at 96 rows they produce visual noise that reads as texture rather than structure
- Sticky table header; the page scrolls, the header does not
- 8px base rhythm; 4px only inside compact controls

---

## 5. The provenance and confidence system

The domain-critical part of this document. Both requirements say the same thing in different
words: **the interface must inform without deciding.**

### Provenance — line treatment, not colour

Three states, each carried by a left rule, a monospace micro-label, and a mark. The rule is the
primary channel because it survives greyscale, colour blindness and a poor monitor.

| State | Rule | Label | Reads as |
|---|---|---|---|
| `extracted` | `--rule-extracted` — **2px dashed** | `EXTRACTED` | Provisional. The system's guess |
| `user_corrected` | `--rule-corrected` — 2px solid brand | `CORRECTED` | Affirmed, and changed |
| `user_added` | `--rule-added` — 2px solid muted | `ADDED` | Affirmed, and yours |

Dashed versus solid is the whole idea: *provisional* versus *affirmed*, legible down a long list at
a glance without reading a single label.

**Provenance persists after approval.** It is not a review-time affordance — FR-004 requires that
user-verified facts stay distinguishable from unverified extraction inside the profile, so profile
screens carry the same rules.

### Confidence — a meter and a number, never a decision

- A three-segment meter plus the value in monospace (`0.82`). Two channels, neither of them colour
  alone.
- Below threshold, an amber attention dot and inclusion in the **Needs attention** filter.
- **No confidence value changes the default action.** Every item arrives `pending` regardless.
  Confidence may change what the interface *suggests* — ordering, filtering, emphasis — and never
  what it *does*. Principle II admits no threshold, and "we were very sure about this one" is
  exactly how an approval gate quietly stops being one.

### Three empty states that must never be confused

A recurring failure in tools like this, and worth designing deliberately:

| State | Treatment | Message shape |
|---|---|---|
| **Not built yet** | Dashed border, muted, small forward marker | "Match scoring arrives with resume tailoring." |
| **Empty but available** | Plain muted text inside a normal container | "No notes yet." |
| **Failed** | Solid `--color-failure` left rule, error icon | "Couldn't read this PDF — it has no text layer." |

The first must never look like the third. A scanned CV that extracted nothing is a *failure* and
must say so; an unbuilt panel is not broken and must not alarm.

---

## 6. Screens

### 6.1 Applications list

Left sidebar navigation; four stat tiles across the top (Total / Active / Interviews / Rejected)
with figures in display type at `text-4xl.tabular`; then search, status filter and the table.

Columns: company (with logo when a domain is known), job title, status pill, date applied
(mono, tabular), match, applied via, and a job-description indicator. Row actions on the right,
revealed on hover and always reachable by keyboard.

The status pill shows the **user's own label**. Where the normalized category differs in a way that
matters — a row flagged rejected while still labelled "Interview Round 2" — the pill carries the
label and a small neutral marker denotes the normalized outcome. That case is not hypothetical: it
is exactly what the JobTracker import produces, and it is *more* informative than the source, which
had to reconcile two fields at every read.

### 6.2 Application detail

Two columns. Left, the record: every stored field, with the **full job description text** set in
`text-base` on `--surface-sunken` — CareerHQ stores the description itself, where JobTracker stored
only a link that may since have expired.

Right, a stack of capability panels, each **named and visibly empty** in this slice:

- **Requirements** — "Extracted requirements arrive with resume tailoring."
- **Match score** — "Scoring arrives with resume tailoring."
- **Company research** — "Company research arrives later."

They use the *not built yet* treatment from §5, never the failure or empty-data ones. The purpose
of building them now is that slices 004, 005 and 006 each get a destination instead of inventing
their own layout and reconciling three of them later.

### 6.3 CV import review — the hard screen

The problem: dozens of items across eight or more sections, each needing accept / correct /
discard, and the user must move fast without losing their place.

**Two panes.** Left, a section navigator with per-section progress (`Work experience 6/9`). Right,
the items for the current section.

**Each item** is a row-card carrying content, provenance rule and label, confidence meter, and
three actions — available as buttons and as keys: `A` accept, `E` edit, `D` discard, `J`/`K` to
move. Keyboard is not a nicety here; it is the difference between reviewing sixty items and
abandoning the import.

**Reviewed items collapse** to `--spacing-row-compact`, so the list visibly shortens as work is
done. Progress you can see beats a progress bar you have to interpret.

**A persistent bottom bar**: `24 of 61 reviewed · 3 need attention`, and the Approve action.
Approve stays disabled until at least one item is accepted.

**Accept all in section** exists as an explicit, labelled bulk action. Bulk acceptance is a
legitimate thing to *choose* and an illegitimate thing to *default to* — the distinction §5 draws
between suggesting and deciding.

**Abandonment leaves nothing behind** (FR-007), so the screen must not imply otherwise: no
autosave-to-profile language, and the profile is written only on approval.

### 6.4 Upload and extraction states

`idle → uploading → extracting → (extracted | failed)`.

- **Extracting** is the slow one — a single model call. Show what is happening rather than an
  indeterminate spinner.
- **Failed** uses the failure treatment and names the likely cause: *"Couldn't read this PDF — it
  looks like a scan with no text layer. Try a PDF exported from a word processor."* Never an empty
  review form, which would imply the CV was understood and found to contain nothing.
- **Fixture** shows a persistent banner in `--color-fixture`: *"Demo data — this is not your CV."*
  It stays visible for the whole review, because the one unacceptable outcome is someone approving
  invented content into their own profile.

---

## 7. Accessibility

- Radix supplies keyboard behaviour and ARIA semantics; this document supplies what it looks like.
  One focus treatment everywhere: 2px brand outline, 2px offset, visible on both grounds.
- **Colour is never the only channel** — §5 is the substance of this commitment, not a note on it.
- Body text meets WCAG AA against its ground; `--muted` is for secondary text at 14px and above,
  never for body copy.
- `prefers-reduced-motion` is honoured globally in the token layer.
- Every icon-only control carries an accessible name. The table's hover-revealed row actions are
  reachable by keyboard and visible on focus — a control that appears only on hover is unusable
  without a mouse.

---

## 8. What is deliberately not decided

- **No theme toggle.** `prefers-color-scheme` only, matching what slices 001–002 shipped. A toggle
  needs persistence and a server-rendered initial value to avoid a flash; it is worth doing
  properly or not yet.
- **No motion system** beyond state transitions and the reduced-motion guard. Add it when there is
  something worth animating.
- **No chart language.** The Career Advisor (slice 007) is the first screen that needs one, and
  designing it now would be guessing at data that does not exist.
