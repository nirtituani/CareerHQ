"""T051 — role context in the exported résumé: employer, job title and dates.

**The defect this file exists to prevent from returning.** The exported PDF listed
experience bullets with nothing saying where or when. Measured on the real submitted
document (`1bd5f20f`, checksum `d77926480e3c…`): seven bullets under one `EXPERIENCE`
heading, no employer, no title, no dates — and those bullets came from **two different
roles at the same employer**, rendered as one undifferentiated stream. An ATS parses that
into an empty employment history.

**Why the suite could not catch it.** ATS assertion 1 walks the approved items through the
extracted text with a moving cursor and checks nothing unapproved appears. A document
missing role context satisfies that perfectly, because role context was never an item.

**The ordering rule, and why it is not invented here.** `position` on a version item is the
*agent's* approved ordering, and it **collides across roles** — the real data has two items
at position 0 — because the draft reorders a flat list with no notion of a role boundary.
Within one role it is unique and meaningful. So:

* **Role order is `work_experiences.ordinal`**, the profile's own explicit order field,
  snapshotted onto the item as `role_ordinal`. No new ordering rule was introduced.
* **Within a role, approved order is `position`**, unchanged.

**Snapshotted, never read live.** A locked version must re-render byte-identically after a
profile edit (Principle IV, FR-023), so the role context travels on the item.
"""

from __future__ import annotations

import io

import pdfplumber
import pytest

from careerhq.domain.schemas.document import (
    ResumeDocument,
    ResumeGroup,
    ResumeRole,
    ResumeSection,
)
from careerhq.infrastructure.documents.render import render_resume_pdf

_CPP = ResumeRole(employer="Sapiens", title="C++ Developer", dates="10/2017 – 01/2026")  # noqa: RUF001
_AI = ResumeRole(employer="Sapiens", title="AI Backend & Cloud Engineering Developer", dates="")

_CPP_LINES = ("Owned the settlement service end to end.", "Designed event-driven pipelines.")
_AI_LINES = ("Built Python services with FastAPI.", "Deployed on AWS Lambda and S3.")


def _document() -> ResumeDocument:
    return ResumeDocument(
        full_name="Dana Levi",
        contact=("dana@example.com", "Tel Aviv"),
        sections=(
            ResumeSection.of_lines("Summary", ("Senior Backend Engineer.",)),
            ResumeSection(
                heading="Experience",
                groups=(
                    ResumeGroup(role=_CPP, lines=_CPP_LINES),
                    ResumeGroup(role=_AI, lines=_AI_LINES),
                ),
            ),
            ResumeSection.of_lines("Skills", ("Python, PostgreSQL.",)),
        ),
    )


@pytest.fixture(scope="module")
def text() -> str:
    with pdfplumber.open(io.BytesIO(render_resume_pdf(_document()))) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_the_employer_and_title_reach_the_document(text: str) -> None:
    """The regression gate for the original defect: neither was present at all."""
    assert "Sapiens" in text
    assert "C++ Developer" in text
    assert "AI Backend & Cloud Engineering Developer" in text


def test_employer_and_job_title_are_separate_readable_text(text: str) -> None:
    """The corpus's own ATS rule, sourced to a vendor.

    *"Give each role an explicit employer name and job title as separate readable text
    rather than combining them into one styled line. Current title and current employer
    are extracted as distinct fields, and a combined line gives the parser one string
    where it expects two."* So no line may contain both.
    """
    for line in text.splitlines():
        stripped = line.strip()
        assert not ("Sapiens" in stripped and "Developer" in stripped), (
            f"employer and title combined into one line, which the ATS rule forbids: {stripped!r}"
        )


def test_two_roles_at_one_employer_render_as_two_groups(text: str) -> None:
    """The real case. Same company, two titles — one merged block loses the distinction."""
    assert text.count("Sapiens") == 2, "each role needs its own employer line"


def test_bullets_sit_under_their_own_role(text: str) -> None:
    """Each role's bullets follow that role's heading and precede the next role's."""
    flat = " ".join(text.split())
    cpp = flat.index("C++ Developer")
    ai = flat.index("AI Backend & Cloud Engineering Developer")
    assert cpp < ai, "roles must render in profile ordinal order"
    for line in _CPP_LINES:
        assert cpp < flat.index(" ".join(line.split())) < ai, f"{line!r} left its role"
    for line in _AI_LINES:
        assert flat.index(" ".join(line.split())) > ai, f"{line!r} left its role"


def test_dates_render_when_available(text: str) -> None:
    assert "10/2017 – 01/2026" in text  # noqa: RUF001


def test_a_role_without_dates_renders_no_date_line(text: str) -> None:
    """Nothing is inferred. The AI role has no stored dates, so none are shown —
    'Present' would be the exporter asserting something the profile does not say."""
    assert "Present" not in text


def test_a_section_of_plain_lines_still_renders(text: str) -> None:
    """Summary and Skills carry no role, and must be unaffected."""
    assert "Senior Backend Engineer." in text
    assert "Python, PostgreSQL." in text


def test_lines_in_order_reports_approved_items_only() -> None:
    """`lines_in_order()` is what FR-017's test states expected order with, so a role
    heading must **not** appear in it — those are document structure, like the section
    headings and the contact line, not items anybody approved."""
    lines = _document().lines_in_order()
    assert lines == ("Senior Backend Engineer.", *_CPP_LINES, *_AI_LINES, "Python, PostgreSQL.")
    assert "Sapiens" not in lines


# -- composition: grouping, ordering, and the NULL-snapshot fallback -----------

from careerhq.application.export_resume import _compose  # noqa: E402
from careerhq.domain.models import ResumeVersion, ResumeVersionItem, SourceKind  # noqa: E402


def _item(kind: SourceKind, text: str, position: int, **role: object) -> ResumeVersionItem:
    return ResumeVersionItem(
        source_kind=kind,
        source_item_id=None,
        position=position,
        original_text=text,
        proposed_text=None,
        final_text=text,
        decision="accepted",
        included=True,
        **role,
    )


def _version(items: list[ResumeVersionItem]) -> ResumeVersion:
    return ResumeVersion(name="Backend Engineer — tailored", items=items)


def _experience(document: ResumeDocument) -> ResumeSection:
    return next(s for s in document.sections if s.heading == "Experience")


#: The real submitted document's data (`1bd5f20f`). Two roles at **one employer**, whose
#: version-item positions **collide across roles** — the draft reordered a flat list with
#: no notion of a role boundary. Within each role the positions are unique.
_REAL = [
    # role_ordinal 9 — the AI role, second in the profile, first by flat position
    _item(
        SourceKind.EXPERIENCE_BULLET,
        "AI-a",
        0,
        role_employer="Sapiens",
        role_title="AI Backend",
        role_start_date="",
        role_end_date="",
        role_ordinal=9,
    ),
    _item(
        SourceKind.EXPERIENCE_BULLET,
        "CPP-a",
        0,
        role_employer="Sapiens",
        role_title="C++ Developer",
        role_start_date="10/2017",
        role_end_date="01/2026",
        role_ordinal=4,
    ),
    _item(
        SourceKind.EXPERIENCE_BULLET,
        "CPP-b",
        1,
        role_employer="Sapiens",
        role_title="C++ Developer",
        role_start_date="10/2017",
        role_end_date="01/2026",
        role_ordinal=4,
    ),
    _item(
        SourceKind.EXPERIENCE_BULLET,
        "AI-b",
        3,
        role_employer="Sapiens",
        role_title="AI Backend",
        role_start_date="",
        role_end_date="",
        role_ordinal=9,
    ),
]


def test_interleaved_positions_group_by_role_rather_than_flat_position() -> None:
    """**The real case, and the whole ordering decision.**

    Sorted by `position` alone the document reads AI-a, CPP-a, CPP-b, AI-b — the two jobs
    interleaved. That interleaving is a data-model artefact of a flat reorder, not a
    meaningful order, so grouping is by role and the roles run in profile ordinal order.
    """
    section = _experience(_compose(_version(list(_REAL)), None))

    assert [g.role.title if g.role else None for g in section.groups] == [
        "C++ Developer",
        "AI Backend",
    ], "roles must run in profile ordinal order (4 before 9), not flat position order"
    assert [list(g.lines) for g in section.groups] == [["CPP-a", "CPP-b"], ["AI-a", "AI-b"]]


def test_within_a_role_the_approved_order_is_preserved() -> None:
    """`position` is unique **within** a role and is the owner's approved order there."""
    reordered = [
        _item(
            SourceKind.EXPERIENCE_BULLET,
            "second",
            5,
            role_employer="Sapiens",
            role_title="C++ Developer",
            role_start_date="",
            role_end_date="",
            role_ordinal=4,
        ),
        _item(
            SourceKind.EXPERIENCE_BULLET,
            "first",
            2,
            role_employer="Sapiens",
            role_title="C++ Developer",
            role_start_date="",
            role_end_date="",
            role_ordinal=4,
        ),
    ]
    section = _experience(_compose(_version(reordered), None))
    assert list(section.groups[0].lines) == ["first", "second"]


def test_two_roles_at_one_employer_stay_distinct() -> None:
    section = _experience(_compose(_version(list(_REAL)), None))
    assert len(section.groups) == 2
    assert {g.role.employer for g in section.groups if g.role} == {"Sapiens"}


def test_dates_are_composed_only_from_what_the_profile_stored() -> None:
    section = _experience(_compose(_version(list(_REAL)), None))
    by_title = {g.role.title: g.role.dates for g in section.groups if g.role}
    assert by_title["C++ Developer"] == "10/2017 – 01/2026"  # noqa: RUF001
    assert by_title["AI Backend"] == "", "a role with no stored dates must show none"


def test_a_version_with_no_role_snapshot_still_exports() -> None:
    """**Backward compatibility, and it is not hypothetical**: six versions predate the
    snapshot, one of them submitted. They must remain exportable, and they render exactly
    as they did before T051 — one unlabelled group, flat position order."""
    legacy = [
        _item(SourceKind.EXPERIENCE_BULLET, "old-b", 1),
        _item(SourceKind.EXPERIENCE_BULLET, "old-a", 0),
    ]
    section = _experience(_compose(_version(legacy), None))
    assert len(section.groups) == 1
    assert section.groups[0].role is None
    assert list(section.groups[0].lines) == ["old-a", "old-b"]


def test_a_partially_snapshotted_version_keeps_the_unsnapshotted_bullets() -> None:
    """A mixed version must lose nothing. The unlabelled group renders last, after the
    roles, because it has no ordinal to place it by — and dropping it would silently
    delete approved content."""
    mixed = [*_REAL, _item(SourceKind.EXPERIENCE_BULLET, "orphan", 7)]
    section = _experience(_compose(_version(mixed), None))
    assert section.groups[-1].role is None
    assert list(section.groups[-1].lines) == ["orphan"]
    assert "orphan" in _compose(_version(mixed), None).lines_in_order()


def test_other_sections_are_untouched_by_grouping() -> None:
    items = [
        _item(SourceKind.SKILL, "Python", 0),
        _item(SourceKind.SUMMARY, "Senior engineer.", 0),
    ]
    document = _compose(_version(items), None)
    for section in document.sections:
        assert len(section.groups) == 1
        assert section.groups[0].role is None


def test_every_approved_line_appears_exactly_once_across_the_groups() -> None:
    """**Grouping introduces a duplication risk that assertion 1 cannot see.**

    ATS assertion 1 walks the approved items through the extracted text with a *moving
    cursor*: it proves presence and order, and an item rendered twice passes it, because
    the walk finds the first occurrence and moves past it. Partitioning items into groups
    is the first thing in this codebase that could plausibly emit one twice — a key that
    did not partition cleanly would put a bullet under two roles.

    `contracts/export.md` claims every approved item appears **exactly once**. This is the
    test that makes that claim true rather than merely plausible.
    """
    document = _compose(_version([*_REAL, _item(SourceKind.EXPERIENCE_BULLET, "orphan", 7)]), None)
    lines = document.lines_in_order()

    assert sorted(lines) == sorted(set(lines)), f"a line was rendered more than once: {lines}"
    assert sorted(lines) == sorted(["AI-a", "AI-b", "CPP-a", "CPP-b", "orphan"]), (
        "grouping must neither drop nor duplicate an approved line"
    )
