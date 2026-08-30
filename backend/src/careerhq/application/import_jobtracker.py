"""T081 — importing a JobTracker export, without inventing a second way to write an application.

**The mapping is not decided here.** `research.md` R8 read `nirtituani/job-tracker-web` directly
and resolved the column order, the `rejected` reconciliation, the day-first dates and the
discarded `user_id` against the actual schema. This module implements that document.

**Two phases, and the split is FR-023 rather than tidiness.** `map_row` is pure: it takes a
`Mapping[str, str]` and returns a `MappedRow` or a `RejectedRow`, touching no session. Every row
is classified *before* the transaction does anything, so the transaction contains only rows
already known to be mappable. A partition that ran inside the transaction would discover a bad
row after the good ones were written, and rolling back then discards work that was never in
question.

**Persistence goes through `record_application`, deliberately.** That use case owns company
resolution (C2), the opening status-history row, and the date coercion — so an importer that
built its own `Application` would be a second write path that drifts from the first. The project
has paid for a second render path before; this is the same mistake with worse consequences,
because the thing that would go missing is history.

**Idempotency is checked here and guaranteed by C3.** The in-file dedup and the "already
imported" query are the fast path; `uq_applications_import_identity` — partial, on
`(user_id, import_source, import_source_id) WHERE import_source IS NOT NULL` — is what actually
holds under a concurrent retry, where a read-then-write check can be raced. A duplicate is
**skipped**, which is an outcome, not **rejected**, which would make a safe retry read as a
failure and invite someone to delete rows and try again.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.record_application import record_application
from careerhq.domain.models import Application, NormalizedStatus, normalize_status

#: Written into `import_source`, and half of C3's identity. Without it the partial unique index
#: — whose predicate is `import_source IS NOT NULL` — matches nothing and every re-import
#: duplicates the lot.
IMPORT_SOURCE = "jobtracker"

#: The columns `GET /api/export` writes, in order. The last three were added to the source by
#: `ALTER TABLE`, which is why they trail: the export is `SELECT *`, so column order *is* the
#: table definition (R8). Presence is required; order is not, because a CSV is read by name.
EXPORT_COLUMNS = (
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

#: What a CSV renders a boolean as depends on the driver that wrote it. Reading only `"true"`
#: would treat every other rendering as *not* rejected — a wrong outcome that looks like a
#: clean import.
_TRUTHY = frozenset({"true", "t", "1", "yes", "y"})

#: Day-first, because the source writes `%d/%m/%Y %H:%M` and stores it as TEXT (R8 Finding 4).
#: `03/04/2026` is 3 April. A month-first reading produces a plausible wrong answer on most
#: rows and never raises, which is the whole danger.
_DATE_FORMATS = ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y")


@dataclass(frozen=True, slots=True)
class MappedRow:
    """One export row, understood. **Carries no source `user_id`** (FR-019).

    Ownership comes from the session. Importing a foreign user id is precisely the
    vulnerability that rule exists to prevent, so the field is not dropped late — it is never
    represented at all, which is a stronger guarantee than remembering not to use it.
    """

    source_id: str
    company: str
    company_domain: str | None
    job_title: str
    status: str
    normalized_status: NormalizedStatus
    date_applied: datetime | None
    location: str | None
    salary_text: str | None
    job_url: str | None
    job_description_url: str | None
    contact_name: str | None
    contact_email: str | None
    source: str | None
    imported_match_rating: int
    notes: str | None
    #: Non-fatal things a person should see: an unfamiliar status, a date that could not be
    #: read. The row imports; the report says what needs attention.
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RejectedRow:
    """A row that cannot become an application at all (FR-018).

    Reserved for something **structural** — no company, no title. An unfamiliar status is not
    this: it is merely uncategorised, and rejecting it would discard real history over a naming
    choice (R8 Finding 3).
    """

    source_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ImportNotice:
    source_id: str
    message: str


@dataclass(frozen=True, slots=True)
class ImportReport:
    """What one import did, per row.

    `skipped` and `rejected` are different outcomes and must stay that way: skipped means the
    row was already imported and C3 did its job; rejected means the row could not be understood.
    """

    imported: int = 0
    skipped: int = 0
    rejected: list[RejectedRow] = field(default_factory=list)
    notices: list[ImportNotice] = field(default_factory=list)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def parse_jobtracker_date(value: str | None) -> datetime | None:
    """Day-first, or nothing. **Deliberately not `record_application.parse_date`.**

    That one reads ISO, because that is what the Add form sends, and it is correct for the form.
    JobTracker writes `%d/%m/%Y %H:%M`, so `datetime.fromisoformat` raises on every row and
    returns `None` — every imported date silently absent. Widening the shared parser to accept
    both would make the *form* ambiguous instead, which is the same bug pointed the other way.
    """
    text = (value or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _match_rating(value: str | None) -> int:
    """`0` means unset in the source, and is kept rather than dropped.

    Discarding a user's own ratings on import is silent data loss, and slice 004's match
    analysis is built to stand beside them (R8).
    """
    try:
        return int((value or "0").strip() or 0)
    except ValueError:
        return 0


def map_row(row: Mapping[str, str]) -> MappedRow | RejectedRow:
    """Decide what one export row means. **Pure — no session, no IO.**

    That is what lets every row be classified before the transaction opens (FR-023).
    """
    source_id = _clean(row.get("id"))
    company = _clean(row.get("company"))
    job_title = _clean(row.get("title"))

    if company is None:
        return RejectedRow(source_id=source_id, reason="the row has no company name")
    if job_title is None:
        return RejectedRow(source_id=source_id, reason="the row has no job title")
    if source_id is None:
        # Without it there is no idempotency key, so a re-import would duplicate the row.
        return RejectedRow(source_id=None, reason="the row has no id to import it under")

    label = _clean(row.get("status")) or "Applied"
    notices: list[str] = []

    # R8 Finding 1. The label records *how far they got*; the normalized status records *how it
    # ended*. Keeping both is strictly more than JobTracker could express, and it is obtained by
    # removing a field rather than adding one — there is no `rejected` column here.
    derived = normalize_status(label)
    if _clean(row.get("rejected")) and (row.get("rejected") or "").strip().casefold() in _TRUTHY:
        derived = NormalizedStatus.REJECTED

    if normalize_status(label) is NormalizedStatus.OTHER:
        notices.append(
            f"status {label!r} is not a status this system recognises; it was kept as written "
            "and counted as 'other'"
        )

    raw_date = _clean(row.get("date_applied"))
    date_applied = parse_jobtracker_date(raw_date)
    if raw_date and date_applied is None:
        # Preserved in the report rather than guessed. A wrong date is worse than an absent one
        # for anything reasoning over a timeline, and a silently dropped one is worse still —
        # the row looks complete and nobody learns the value was ever there.
        notices.append(f"date_applied {raw_date!r} could not be read as a date and was left empty")

    raw_updated = _clean(row.get("last_updated"))
    if raw_updated and parse_jobtracker_date(raw_updated) is None:
        notices.append(f"last_updated {raw_updated!r} could not be read as a date")

    return MappedRow(
        source_id=source_id,
        company=company,
        company_domain=_clean(row.get("company_domain")),
        job_title=job_title,
        status=label,
        normalized_status=derived,
        date_applied=date_applied,
        location=_clean(row.get("location")),
        salary_text=_clean(row.get("salary_range")),
        job_url=_clean(row.get("job_link")),
        job_description_url=_clean(row.get("job_desc_link")),
        contact_name=_clean(row.get("contact_person")),
        contact_email=_clean(row.get("contact_email")),
        source=_clean(row.get("applied_via")),
        imported_match_rating=_match_rating(row.get("match_rating")),
        notes=_clean(row.get("notes")),
        notices=tuple(notices),
    )


def read_export(data: bytes) -> list[dict[str, str]]:
    """Parse the upload, or refuse it whole.

    A file we cannot recognise is refused before anything is written, because partially
    importing an unrecognised file is worse than refusing it: the rows that happened to parse
    would be silently wrong and nothing would say so.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("that file is not a readable text export") from exc

    reader = csv.DictReader(io.StringIO(text))
    # **`csv.Error` is not a `ValueError`** — its bases are `Exception`, `object` — so it passes
    # straight through a caller that catches `ValueError` and becomes a 500 for a file the
    # system understood perfectly well was malformed. Python refuses any field over
    # `csv.field_size_limit()`, 131072 bytes by default, which one long `notes` value reaches in
    # a file far under the upload limit. Converted here, at the parser, so every caller of this
    # function gets one exception type for "this file cannot be read".
    try:
        header = reader.fieldnames or []
        missing = [column for column in EXPORT_COLUMNS if column not in header]
        if missing:
            # Named, because "not a recognised export" alone leaves someone guessing which file
            # to upload. The columns are the source's own, so naming them is not a disclosure.
            raise ValueError(
                "that file does not look like a JobTracker export; it is missing the columns: "
                + ", ".join(missing)
            )
        return [
            {key: (value or "") for key, value in row.items() if key is not None} for row in reader
        ]
    except csv.Error as exc:
        raise ValueError(f"that file could not be read as CSV: {exc}") from exc


async def _already_imported(session: AsyncSession, *, user_id: uuid.UUID) -> set[str]:
    """The source ids this user has already imported. **The fast path, not the guarantee.**

    C3 is the guarantee: under a concurrent retry this read can be stale, and only the database
    can refuse both writers.
    """
    rows = await session.scalars(
        sa.select(Application.import_source_id).where(
            Application.user_id == user_id,
            Application.import_source == IMPORT_SOURCE,
            Application.import_source_id.is_not(None),
        )
    )
    return {value for value in rows if value is not None}


async def import_jobtracker(
    session: AsyncSession, *, user_id: uuid.UUID, data: bytes
) -> ImportReport:
    """Import an export for this user. **The caller owns the transaction** (FR-023).

    Every use case in this project leaves the commit to its caller, and here it is load-bearing
    rather than conventional: FR-023 forbids a partial commit, and a use case that committed
    would make that unenforceable from the route.
    """
    rows = read_export(data)

    # Phase one: classify everything, touching nothing.
    partitioned: list[MappedRow | RejectedRow] = [map_row(row) for row in rows]

    rejected: list[RejectedRow] = []
    notices: list[ImportNotice] = []
    imported = 0
    skipped = 0
    mappable: list[MappedRow] = []
    seen_in_file: set[str] = set()

    for outcome in partitioned:
        if isinstance(outcome, RejectedRow):
            rejected.append(outcome)
            continue
        if outcome.source_id in seen_in_file:
            # A real export can repeat a row. This is a duplicate, not an error.
            skipped += 1
            continue
        seen_in_file.add(outcome.source_id)
        mappable.append(outcome)

    existing = await _already_imported(session, user_id=user_id)

    # Phase two: only rows already known to be mappable reach the session.
    for mapped in mappable:
        if mapped.source_id in existing:
            skipped += 1
            continue

        application = await record_application(
            session,
            user_id=user_id,
            data={
                "company": mapped.company,
                "company_domain": mapped.company_domain,
                "job_title": mapped.job_title,
                "status": mapped.status,
                "location": mapped.location,
                "date_applied": mapped.date_applied,
                "job_url": mapped.job_url,
                "job_description_url": mapped.job_description_url,
                "source": mapped.source,
                "salary_text": mapped.salary_text,
                "contact_name": mapped.contact_name,
                "contact_email": mapped.contact_email,
                "notes": mapped.notes,
            },
            # FR-016. The reconciliation reads *two* source fields, so it cannot be derived
            # from the label alone — which is the one thing `normalize_status` can see.
            normalized_status_override=mapped.normalized_status,
        )

        # **Set on the object `record_application` created, not on one built here.** These are
        # import provenance and a preserved source value; none may be writable from an HTTP
        # request, so they are deliberately absent from `WRITABLE_FIELDS` and assigned on the
        # instance the single write path returned.
        application.import_source = IMPORT_SOURCE
        application.import_source_id = mapped.source_id
        application.imported_match_rating = mapped.imported_match_rating

        imported += 1
        notices.extend(
            ImportNotice(source_id=mapped.source_id, message=notice) for notice in mapped.notices
        )

    await session.flush()
    return ImportReport(imported=imported, skipped=skipped, rejected=rejected, notices=notices)


def rejected_reasons(report: ImportReport) -> Sequence[str]:
    """Flat reasons, for a log line that has no room for structure."""
    return [f"{rejection.source_id or '?'}: {rejection.reason}" for rejection in report.rejected]


__all__ = [
    "EXPORT_COLUMNS",
    "IMPORT_SOURCE",
    "ImportNotice",
    "ImportReport",
    "MappedRow",
    "RejectedRow",
    "import_jobtracker",
    "map_row",
    "parse_jobtracker_date",
    "read_export",
    "rejected_reasons",
]
