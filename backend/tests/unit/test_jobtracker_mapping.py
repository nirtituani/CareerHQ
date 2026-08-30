"""T076, T077, T078, T080 — mapping one JobTracker row, before any session exists.

**Pure by construction, and that is the design under test as much as the values are.**
FR-023 forbids a partial commit, and T081's answer is to validate and partition every row
*before* the transaction opens. That is only possible if deciding what a row means needs no
database — so `map_row` takes a `Mapping[str, str]` and returns either a `MappedRow` or a
`RejectedRow`, and a test that had to open a session would be evidence the partition cannot
happen where FR-023 needs it to.

**The mapping is not invented here.** `research.md` R8 read `nirtituani/job-tracker-web`
directly and resolved the column order, the `rejected` reconciliation, the day-first dates and
the discarded `user_id` against the actual schema. These tests hold the implementation to that
document rather than to a guess about what an export looks like.

**Two of these tasks drill behaviour that already exists.** `normalize_status` already folds an
unrecognised label to `OTHER` (T077), and no code anywhere reads a source `user_id` (T080).
Ticking either on inspection would be a lie, so each is written to fail if the existing
behaviour is removed — and each was watched failing.
"""

from __future__ import annotations

import csv
import dataclasses
import pathlib
from collections.abc import Mapping

import pytest

from careerhq.application.import_jobtracker import MappedRow, RejectedRow, map_row
from careerhq.domain.models.application import NormalizedStatus

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "jobtracker_export.csv"

#: The export's columns, in the order `GET /api/export` writes them. The last three were added
#: to the source by `ALTER TABLE`, which is why they trail the rest — the export is `SELECT *`,
#: so column order is the table definition (R8).
R8_COLUMNS = (
    "id",
    "user_id",
    "company",
    "title",
    "location",
    "date_applied",
    "status",
    "salary_range",
    "job_link",
    "contact_person",
    "contact_email",
    "applied_via",
    "match_rating",
    "notes",
    "last_updated",
    "job_desc_link",
    "rejected",
    "company_domain",
)


def _rows() -> list[dict[str, str]]:
    with FIXTURE.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _by_id(source_id: str, *, occurrence: int = 0) -> dict[str, str]:
    """One fixture row. `occurrence` because the duplicate-id case appears twice on purpose."""
    matching = [row for row in _rows() if row["id"] == source_id]
    assert matching, f"fixture has no row with id {source_id}; the test is reading the wrong file"
    return matching[occurrence]


def _mapped(source_id: str) -> MappedRow:
    result = map_row(_by_id(source_id))
    assert isinstance(result, MappedRow), f"row {source_id} was rejected: {result}"
    return result


# ======================================================================================
# The fixture itself, because a fixture that loses an edge case takes its test with it
# ======================================================================================


def test_the_fixture_matches_the_export_shape_and_carries_every_case() -> None:
    """**A synthetic fixture is a claim about a real format, so the claim is asserted.**

    The real export is the author's own employment history and this repository is public, so
    T074's fixture is written rather than exported. That trade is only safe while the written
    file still has the shape the source produces and still contains every case the other tests
    reach for — otherwise a future tidy-up silently deletes a case and the test that depended
    on it starts passing vacuously against a row that is no longer there.
    """
    rows = _rows()
    assert tuple(rows[0].keys()) == R8_COLUMNS, "the fixture no longer matches the export's columns"

    ids = [row["id"] for row in rows]
    statuses = {row["status"] for row in rows}

    cases = {
        "rejected with another label": any(
            row["rejected"] == "true" and row["status"] != "Rejected" for row in rows
        ),
        "status Rejected outright": "Rejected" in statuses,
        "unknown status": bool(statuses - {*_KNOWN_LABELS, "Rejected"}),
        "day-first date": any(row["date_applied"].startswith("25/12/") for row in rows),
        "unparseable date": any(row["date_applied"] == "ASAP" for row in rows),
        "blank date": any(row["date_applied"] == "" for row in rows),
        "missing company": any(not row["company"].strip() for row in rows),
        "missing title": any(not row["title"].strip() for row in rows),
        "duplicate source id": len(ids) != len(set(ids)),
        "foreign user_id": len({row["user_id"] for row in rows}) > 1,
        "company spelling variant": any(
            row["company"].strip().startswith("northwind") for row in rows
        ),
    }
    missing = sorted(name for name, present in cases.items() if not present)
    assert not missing, f"the fixture no longer exercises: {missing}"
    assert len(cases) == 11, "a case was added or removed without updating the count"


#: JobTracker's own vocabulary (R8 Finding 3), used only to prove the fixture contains a label
#: that is *not* in it. Deliberately a literal rather than an import of the production mapping:
#: importing it would make this check agree with the implementation by construction.
_KNOWN_LABELS = frozenset(
    {
        "Pre-Applied",
        "Applied",
        "Online Assessment",
        "Phone Screen",
        "Interview Round 1",
        "Interview Round 2",
        "Interview Round 3",
        "Final Interview",
        "Offer Received",
        "Rejected",
        "Ghosted",
        "Withdrawn",
    }
)


# ======================================================================================
# T076 — the FR-016 reconciliation
# ======================================================================================


def test_a_rejected_flag_keeps_the_original_label_and_normalizes_to_rejected() -> None:
    """R8 Finding 1, and the whole reason there is no `rejected` column.

    `rejected=true` with status `Interview Round 2` records two different facts: **how far the
    application got** and **how it ended**. Keeping the label and deriving the normalized status
    preserves both, which is strictly more than JobTracker could express — obtained by removing
    a field rather than adding one.

    Getting this wrong in the obvious direction — overwriting the label with "Rejected" — loses
    the interview history permanently, and no later import can recover it.
    """
    mapped = _mapped("102")

    assert mapped.status == "Interview Round 2", (
        "the label was overwritten; how far they got is lost"
    )
    assert mapped.normalized_status == NormalizedStatus.REJECTED


def test_a_status_of_rejected_needs_no_flag_to_normalize_as_rejected() -> None:
    """The other half of the same table: the label is already the outcome."""
    mapped = _mapped("105")

    assert mapped.status == "Rejected"
    assert mapped.normalized_status == NormalizedStatus.REJECTED


def test_an_unrejected_row_still_derives_its_status_from_its_label() -> None:
    """The control, without which both tests above pass against a mapper that hardcodes rejected.

    This is the assertion that makes the two above mean anything.
    """
    assert _mapped("101").normalized_status == NormalizedStatus.APPLIED
    assert _mapped("103").normalized_status == NormalizedStatus.OFFER
    assert _mapped("109").normalized_status == NormalizedStatus.WITHDRAWN


@pytest.mark.parametrize("flag", ["true", "True", "TRUE", "t", "1"])
def test_the_flag_is_read_in_the_forms_a_real_export_writes(flag: str) -> None:
    """A CSV has no booleans, and the source writes whatever its driver rendered.

    Reading only the exact string `true` would silently treat every other rendering as *not*
    rejected — a wrong outcome that looks like a clean import.
    """
    row = dict(_by_id("101"))
    row["rejected"] = flag
    result = map_row(row)

    assert isinstance(result, MappedRow)
    assert result.normalized_status == NormalizedStatus.REJECTED, f"{flag!r} did not read as true"


@pytest.mark.parametrize("flag", ["false", "False", "f", "0", ""])
def test_the_absent_flag_does_not_manufacture_a_rejection(flag: str) -> None:
    row = dict(_by_id("101"))
    row["rejected"] = flag
    result = map_row(row)

    assert isinstance(result, MappedRow)
    assert result.normalized_status == NormalizedStatus.APPLIED, f"{flag!r} read as rejected"


# ======================================================================================
# T077 — an unfamiliar label is the common case, not an error
# ======================================================================================


def test_an_unrecognised_status_is_preserved_normalized_to_other_and_flagged() -> None:
    """R8 Finding 3: JobTracker keeps its status vocabulary in `localStorage`.

    A customised status never reaches the database as a *definition*, but the strings it
    produced are in `applications.status` — so an unfamiliar label is what a real export
    routinely contains. Rejecting the row would discard real history over a naming choice.
    FR-018's "cannot be mapped" is reserved for something structural, like a missing company.

    **Flagged, not silent.** The row imports, and the report says it needs attention, because a
    status that quietly becomes `other` is a status nobody ever fixes.
    """
    result = map_row(_by_id("104"))

    assert isinstance(result, MappedRow), "an unfamiliar label rejected the row"
    assert result.status == "Take-Home Task", "the user's own label was not preserved verbatim"
    assert result.normalized_status == NormalizedStatus.OTHER
    assert any("Take-Home Task" in notice for notice in result.notices), (
        f"the unrecognised label was not reported: {result.notices}"
    )


def test_a_recognised_status_is_not_flagged() -> None:
    """Or every row arrives needing attention, and the flag stops meaning anything."""
    assert _mapped("101").notices == ()


# ======================================================================================
# T078 — dates are day-first text, and a wrong date is worse than an absent one
# ======================================================================================


def test_dates_parse_day_first() -> None:
    """R8 Finding 4: the source writes `%d/%m/%Y %H:%M` and stores it as TEXT.

    `03/04/2026` is **3 April**, not 4 March. Both readings are valid dates, which is exactly
    why this is dangerous: a month-first parser produces a plausible wrong answer on most rows
    and never raises.
    """
    mapped = _mapped("101")

    assert mapped.date_applied is not None
    assert (mapped.date_applied.day, mapped.date_applied.month) == (3, 4), (
        f"03/04/2026 was read as {mapped.date_applied:%d %B %Y} — month-first"
    )


def test_a_date_only_valid_day_first_still_parses() -> None:
    """`25/12/2025` has no month-first reading at all, so a parser that tries one drops it."""
    mapped = _mapped("102")

    assert mapped.date_applied is not None
    assert (mapped.date_applied.day, mapped.date_applied.month) == (25, 12)


def test_an_unparseable_date_is_reported_with_its_raw_value_never_guessed() -> None:
    """The value is kept where a person can see it, and the column stays empty.

    Guessing would put a confident wrong date in front of a Career Advisor reasoning over a
    timeline. Dropping it silently is nearly as bad: the row imports looking complete, and
    nobody learns that `ASAP` was ever in the file.
    """
    result = map_row(_by_id("105"))

    assert isinstance(result, MappedRow), "an unparseable date must not reject the row"
    assert result.date_applied is None
    assert any("ASAP" in notice for notice in result.notices), (
        f"the raw value was not preserved in the report: {result.notices}"
    )


def test_a_blank_date_is_absent_rather_than_a_failure() -> None:
    """An empty column is missing data, not bad data, and must not be reported as a problem."""
    mapped = _mapped("109")

    assert mapped.date_applied is None
    assert mapped.notices == (), f"a blank date was reported as a failure: {mapped.notices}"


# ======================================================================================
# T080 — the source user_id is discarded
# ======================================================================================


def test_the_source_user_id_never_reaches_the_mapped_row() -> None:
    """FR-019. Ownership comes from the session; importing a foreign user id is the
    vulnerability that rule exists to prevent.

    **Asserted over every field rather than over a named one**, because the risk is not that
    someone adds a `user_id` attribute — it is that the value survives somewhere incidental,
    in a note or a passthrough dict, and is later read by something that trusts it.
    """
    row = _by_id("108")
    assert row["user_id"] == "99", "the fixture's foreign-user row changed; this tests nothing"

    result = map_row(row)
    assert isinstance(result, MappedRow)

    assert not hasattr(result, "user_id"), "the mapped row carries a source user id"
    # `dataclasses.fields`, not `vars`: `MappedRow` is `slots=True` and so has no `__dict__`.
    values = [str(getattr(result, f.name)) for f in dataclasses.fields(result)]
    assert len(values) == len(dataclasses.fields(MappedRow)), "nothing was examined"
    offenders = [value for value in values if "99" in value and "1999" not in value]
    assert not offenders, f"the source user_id survived into: {offenders}"


def test_a_foreign_user_id_does_not_reject_the_row() -> None:
    """Discarding is not refusing. The row is the importing user's history to keep."""
    assert isinstance(map_row(_by_id("108")), MappedRow)


# ======================================================================================
# FR-018 — what "cannot be mapped" actually means
# ======================================================================================


@pytest.mark.parametrize(
    ("source_id", "missing"),
    [("106", "company"), ("107", "title")],
)
def test_a_row_missing_something_structural_is_rejected_with_a_reason(
    source_id: str, missing: str
) -> None:
    """FR-018: reported individually, with enough detail to fix it by hand.

    A row with no company or no title cannot become an application at all — unlike an unfamiliar
    status, which merely cannot be categorised.
    """
    result = map_row(_by_id(source_id))

    assert isinstance(result, RejectedRow), f"a row with no {missing} was mapped anyway"
    assert result.source_id == source_id, "the report cannot point at the offending row"
    assert missing in result.reason.lower(), (
        f"the reason does not say what is missing: {result.reason}"
    )


def test_mapping_reads_only_what_it_was_given() -> None:
    """`map_row` takes a Mapping, so a caller can partition before any transaction (FR-023)."""
    row: Mapping[str, str] = _by_id("101")
    assert isinstance(map_row(dict(row)), MappedRow)
