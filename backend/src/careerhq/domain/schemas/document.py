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

**Sections hold ordered *groups*, and only Experience uses a labelled one (T051).** A
group with a role is one job — employer, title, dates — followed by that job's approved
bullets; a group with `role=None` is a plain run of lines, which is every other section.
The renderer's contract is unchanged by this: *emit these groups, in this order, adding
nothing*. It still decides no ordering and infers no heading.

**Role context reaches here already snapshotted, never read live from the profile.** A
version freezes its items so a later profile edit cannot change an approved document
(Principle IV, FR-023); role context read live would sit outside that freeze and let a
locked document change underneath its own checksum. `ResumeVersionItem` therefore carries
`role_employer`, `role_title`, `role_start_date`, `role_end_date` and `role_ordinal`, and
this model receives their snapshotted values.

**A role heading is document structure, not an item.** `lines_in_order()` deliberately
excludes it, for the same reason the name, the contact line and the section headings are
excluded: FR-017 is a claim about approved items, and an employer nobody approved as a
résumé line must not be counted as one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: What a section *is*, not how it looks.
#:
#: **Semantic, and the distinction is load-bearing.** `list` does not mean "8pt between
#: entries" — it means every line is its own complete entry, which is a fact about the
#: content that only the caller assembling the section knows. A themed renderer reads it
#: and sets list entries further apart than wrapped prose; the plain renderer ignores it
#: entirely. Putting the spacing here instead would move presentation into the document
#: and make `ResumeDocument` unrenderable without deciding a design.
#:
#: Measured, not assumed: on a real CV, prose paragraphs ran 2pt apart and Skills
#: entries 8pt. Rendering both at one spacing put the following heading 30pt out of
#: place and cost the one-page fit.
SectionStyle = Literal["prose", "list", "roles"]


@dataclass(frozen=True, slots=True)
class ResumeRole:
    """One job's context: where, as what, and when.

    **`employer` and `title` are separate fields because they must render as separate
    text.** The corpus's ATS rule, sourced to a vendor: *"Give each role an explicit
    employer name and job title as separate readable text rather than combining them into
    one styled line. Current title and current employer are extracted as distinct fields,
    and a combined line gives the parser one string where it expects two."* Holding them
    as one string here would make that unenforceable one layer down.

    `dates` is **pre-formatted and may be empty**, and empty means the profile stores
    none. Nothing is inferred — a role with a start and no end does not become "Present",
    because that would be the exporter asserting something the owner never recorded.
    """

    employer: str
    title: str
    dates: str


@dataclass(frozen=True, slots=True)
class ResumeGroup:
    """Lines that belong together, optionally under a role.

    `role is None` is the ordinary case — Summary, Skills, Education — and renders as a
    plain run of lines, exactly as before T051.
    """

    role: ResumeRole | None
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResumeSection:
    """One standard heading and the ordered groups beneath it."""

    heading: str
    groups: tuple[ResumeGroup, ...]
    #: Defaults to `prose`, so every construction site that predates this — and every
    #: test written against the plain template — keeps its meaning unchanged.
    style: SectionStyle = field(default="prose")

    @classmethod
    def of_lines(
        cls, heading: str, lines: tuple[str, ...], style: SectionStyle = "prose"
    ) -> ResumeSection:
        """A section of plain lines under no role — every section except Experience.

        Exists so the common case stays one call and the nesting is not repeated at every
        construction site.
        """
        return cls(heading=heading, groups=(ResumeGroup(role=None, lines=lines),), style=style)


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
        return tuple(
            line for section in self.sections for group in section.groups for line in group.lines
        )


__all__ = ["ResumeDocument", "ResumeGroup", "ResumeRole", "ResumeSection", "SectionStyle"]
