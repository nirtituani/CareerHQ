"""The content of a résumé, as the renderer receives it.

**Pure content, no ORM.** `infrastructure/documents/render.py` takes one of these and
returns bytes; it never sees a `ResumeVersion`, a session, or a `SourceKind`. Loading
approved items and deciding which section each belongs to is the export use case's job
(T036) — the layer that already holds that domain knowledge — and keeping it out of the
renderer is what lets every ATS assertion be checked without a database.

**Sections are explicit rather than derived from item kind, and that is the whole design
decision here.** A renderer that grouped items by kind would decide the document's order
itself, and "approved order" (FR-017) would then mean something the caller could not
see or control. Given sections, the renderer's contract is exact and testable: *emit
these lines, in this order, adding nothing*.

**Deliberately minimal.** It carries what T031, T034 and T035 name — a name, a contact
block rendered in the body, standard headings, and ordered lines — and nothing else.
**It has no role headings, employers or dates**, which a complete résumé does need;
those require loading work-experience context and a nested shape, and neither T034 nor
T035 asks for them. Recorded as an open point for T036 rather than guessed at here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResumeSection:
    """One standard heading and the approved lines beneath it, in approved order."""

    heading: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResumeDocument:
    """One résumé, ready to render.

    `contact` is a sequence of already-formatted fragments — email, phone, location —
    joined into one line **in the body**. Not a header or footer: FR-018 and the ATS
    evidence behind the corpus both say parsers routinely drop those, which is the one
    way to lose a candidate's email address without anything looking wrong.
    """

    full_name: str
    contact: tuple[str, ...]
    sections: tuple[ResumeSection, ...]

    def lines_in_order(self) -> tuple[str, ...]:
        """Every approved line, flattened in render order.

        Exists so a caller — and FR-017's test — can state the expected order without
        re-deriving how sections nest.
        """
        return tuple(line for section in self.sections for line in section.lines)


__all__ = ["ResumeDocument", "ResumeSection"]
