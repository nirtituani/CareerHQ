"""T075, T079 — importing a JobTracker export, twice, and with rows that cannot be imported.

**T075 is written first on purpose.** Idempotency is the requirement most likely to pass in the
happy path and break under retry: the first import of a clean file works under almost any
implementation, and the second one is where a read-then-write check loses a race or a missing
constraint quietly doubles someone's history. `data-model.md` §4 names C3 as the thing to test
first, and this is that test.

**The guarantee is the constraint, not the check.** C3 is
`UNIQUE (user_id, import_source, import_source_id) WHERE import_source IS NOT NULL`. An
application-level "have I seen this id" lookup is the fast path; under a concurrent retry it can
be raced, and only the database can refuse both. So the second import must report duplicates as
**skipped**, which is an outcome, rather than as errors, which would make a safe retry look like
a failure and invite someone to "fix" it by deleting rows.

**T079 is the other half of FR-023.** A file with one unmappable row must import the rest — and
the transaction must contain only rows already known to be mappable, which is why `map_row` is
pure and the partition happens before the session is asked to do anything. A transaction that
discovers a bad row halfway through has already written the good ones, and rolling back then
loses work that was never in question.
"""

from __future__ import annotations

import csv
import pathlib

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.import_jobtracker import import_jobtracker
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import Application, Company, NormalizedStatus, User

pytestmark = pytest.mark.asyncio

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "jobtracker_export.csv"

#: A scratch user. `@example.com` because pydantic's `EmailStr` rejects `.test` and `.invalid`,
#: and the resulting 500 reads as an application bug rather than a bad fixture.
CLAIMS = {"sub": "google-jobtracker-import", "email": "importer@example.com", "name": "Importer"}


def _csv_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _fixture_rows() -> list[dict[str, str]]:
    with FIXTURE.open(newline="") as handle:
        return list(csv.DictReader(handle))


async def _user(session: AsyncSession) -> User:
    user: User = await provision_user(session, CLAIMS)
    await session.flush()
    return user


async def _applications(session: AsyncSession, user: User) -> list[Application]:
    result = await session.scalars(
        sa.select(Application).where(Application.user_id == user.id).order_by(Application.job_title)
    )
    return list(result)


async def _companies(session: AsyncSession, user: User) -> list[Company]:
    result = await session.scalars(sa.select(Company).where(Company.user_id == user.id))
    return list(result)


# ======================================================================================
# T075 — idempotency, first
# ======================================================================================


async def test_a_first_import_creates_the_mappable_rows(db_session: AsyncSession) -> None:
    """The baseline the idempotency test needs, and a count assertion rather than a smoke check.

    Without knowing exactly how many rows *should* land, "the second import added nothing" is
    satisfied by an implementation that imports nothing at all, both times.
    """
    user = await _user(db_session)

    report = await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    rows = _fixture_rows()
    unique_mappable = {row["id"] for row in rows if row["company"].strip() and row["title"].strip()}
    assert report.imported == len(unique_mappable), report
    assert len(await _applications(db_session, user)) == len(unique_mappable)


async def test_re_importing_the_same_file_creates_no_duplicates(db_session: AsyncSession) -> None:
    """FR-017, SC-006, constraint C3. **The headline of this file.**

    A retry is the normal case, not the exotic one: a browser tab reloaded, an upload that
    appeared to fail, a person who is not sure it worked. Doubling their history is the worst
    possible answer to that uncertainty, and it is silent.
    """
    user = await _user(db_session)
    first = await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())
    after_first = len(await _applications(db_session, user))

    second = await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    assert len(await _applications(db_session, user)) == after_first, (
        "the second import created applications; C3 did not hold"
    )
    assert second.imported == 0
    # Everything mappable is now a duplicate: the rows the first run imported, **plus** the row
    # it already skipped as a repeat within the file. Asserting `== first.imported` would be
    # off by exactly that one row — and would quietly encode the belief that a file cannot
    # repeat an id, which this fixture exists to disprove.
    assert second.skipped == first.imported + first.skipped, (
        f"duplicates were not all reported as skipped: {second}"
    )


async def test_a_duplicate_is_reported_as_skipped_not_as_an_error(
    db_session: AsyncSession,
) -> None:
    """A safe retry must not look like a failure.

    Reporting duplicates as errors would tell someone their import broke when it did exactly
    what it promised — and the plausible next move is to delete rows and try again.
    """
    user = await _user(db_session)
    await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    second = await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    assert second.rejected == [] or all(
        "duplicate" not in rejection.reason.lower() for rejection in second.rejected
    ), f"a duplicate was reported as a rejection: {second.rejected}"
    assert second.skipped > 0


async def test_a_duplicate_inside_one_file_is_skipped_too(db_session: AsyncSession) -> None:
    """The fixture repeats source id 101, because a real export can.

    Idempotency across two runs and idempotency within one file are different code paths: the
    second is not protected by anything already committed, only by the importer noticing — or by
    C3 refusing the second insert in the same transaction.
    """
    user = await _user(db_session)

    report = await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    ids = [row["id"] for row in _fixture_rows()]
    assert len(ids) != len(set(ids)), "the fixture lost its duplicate row; this tests nothing"

    matching = await db_session.scalars(
        sa.select(Application).where(
            Application.user_id == user.id, Application.import_source_id == "101"
        )
    )
    assert len(list(matching)) == 1, "the repeated row was imported twice"
    assert report.skipped >= 1


# ======================================================================================
# T079 — unmappable rows are reported individually while the rest still import
# ======================================================================================


async def test_unmappable_rows_are_reported_individually_and_the_rest_import(
    db_session: AsyncSession,
) -> None:
    """FR-018 and FR-023 together.

    The fixture carries one row with no company and one with no title. Both are structurally
    unmappable — unlike an unfamiliar status, which is merely uncategorised and imports fine.
    """
    user = await _user(db_session)

    report = await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    rejected_ids = {rejection.source_id for rejection in report.rejected}
    assert rejected_ids == {"106", "107"}, f"unexpected rejections: {report.rejected}"
    assert all(rejection.reason for rejection in report.rejected), (
        "a rejection carries no reason, so nobody can fix the row by hand"
    )
    assert report.imported > 0, "one bad row stopped the whole import"


async def test_a_rejected_row_leaves_nothing_behind(db_session: AsyncSession) -> None:
    """FR-023's "no partial commit", at row granularity.

    A row that was reported as unmappable must not also have created a company as a side effect
    of being examined — which is exactly what happens if the partition runs inside the
    transaction and resolves the company before discovering the title is missing.
    """
    user = await _user(db_session)

    await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    names = {company.normalized_name for company in await _companies(db_session, user)}
    assert "larkspur interactive" not in names, "the company from a rejected row was created anyway"


async def test_the_report_accounts_for_every_row_in_the_file(db_session: AsyncSession) -> None:
    """Nothing may be dropped silently.

    A row that is neither imported, skipped nor rejected has vanished, and the report is the
    only place anyone would ever notice.
    """
    user = await _user(db_session)

    report = await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    total = report.imported + report.skipped + len(report.rejected)
    assert total == len(_fixture_rows()), f"{len(_fixture_rows())} rows in, {total} accounted for"


# ======================================================================================
# The mapping, proved through the real persistence path
# ======================================================================================


async def test_the_rejected_flag_reaches_the_row_as_a_status_not_a_column(
    db_session: AsyncSession,
) -> None:
    """FR-016 end to end, through `record_application`.

    The unit test proves `map_row` decides this correctly. This proves the decision survives
    persistence — which is the half that a `normalized_status` recomputed inside the use case
    would silently discard.
    """
    user = await _user(db_session)
    await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    application = await db_session.scalar(
        sa.select(Application).where(
            Application.user_id == user.id, Application.import_source_id == "102"
        )
    )
    assert application is not None
    assert application.status == "Interview Round 2", "how far they got was overwritten"
    assert application.normalized_status == NormalizedStatus.REJECTED


async def test_the_same_employer_spelled_differently_is_one_company(
    db_session: AsyncSession,
) -> None:
    """C2, FR-014. Rows 102 and 103 are `Northwind Analytics` and `  northwind analytics.`."""
    user = await _user(db_session)
    await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    northwind = [
        company
        for company in await _companies(db_session, user)
        if company.normalized_name == "northwind analytics"
    ]
    assert len(northwind) == 1, f"the employer was created {len(northwind)} times"


async def test_the_source_user_id_is_never_written(db_session: AsyncSession) -> None:
    """FR-019. Row 108 belongs to JobTracker user 99; it imports as *this* user's history."""
    user = await _user(db_session)
    await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    application = await db_session.scalar(
        sa.select(Application).where(
            Application.user_id == user.id, Application.import_source_id == "108"
        )
    )
    assert application is not None, (
        "a row from another JobTracker user was refused rather than imported"
    )
    assert application.user_id == user.id


async def test_an_unparseable_date_is_reported_with_its_raw_value(
    db_session: AsyncSession,
) -> None:
    """T078's reporting half, which only the import report can satisfy.

    `parse_date` returns `None` for anything it cannot read, which cannot distinguish "blank"
    from "someone typed ASAP". The row still imports; the report is where the raw value lives.
    """
    user = await _user(db_session)

    report = await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    notices = [notice for notice in report.notices if notice.source_id == "105"]
    assert notices, f"nothing was reported for the unparseable date: {report.notices}"
    assert any("ASAP" in notice.message for notice in notices), (
        f"the raw value was not preserved: {[n.message for n in notices]}"
    )


async def test_every_imported_row_carries_its_import_provenance(
    db_session: AsyncSession,
) -> None:
    """Without both columns C3 does not apply — its predicate is `import_source IS NOT NULL`.

    An importer that set only `import_source_id` would pass every other test here and leave the
    partial unique index matching nothing, so the *second* import would duplicate everything.
    """
    user = await _user(db_session)
    await import_jobtracker(db_session, user_id=user.id, data=_csv_bytes())

    applications = await _applications(db_session, user)
    assert applications, "nothing was examined"
    for application in applications:
        assert application.import_source == "jobtracker", application.job_title
        assert application.import_source_id, application.job_title


# ======================================================================================
# The file itself
# ======================================================================================


@pytest.mark.parametrize(
    "payload",
    [b"", b"not a csv at all", b"id,user_id\n1,2\n"],
    ids=["empty", "not-csv", "wrong-columns"],
)
async def test_a_file_that_is_not_an_export_is_refused_whole(
    db_session: AsyncSession, payload: bytes
) -> None:
    """A file we cannot recognise is refused before anything is written (400, per the contract).

    Partially importing an unrecognised file is worse than refusing it: the rows that happened
    to parse would be silently wrong, and nothing would say so.
    """
    user = await _user(db_session)

    with pytest.raises(ValueError):
        await import_jobtracker(db_session, user_id=user.id, data=payload)

    assert await _applications(db_session, user) == []


def test_the_use_case_opens_no_transaction_of_its_own() -> None:
    """The caller owns the transaction, as every use case in this project does.

    A use case that committed would make FR-023 unenforceable from the route, and would make
    these tests commit into a database whose knowledge tables `conftest` never truncates.
    """
    source = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src"
        / "careerhq"
        / "application"
        / "import_jobtracker.py"
    ).read_text()

    assert "async def import_jobtracker" in source, "this test is reading the wrong file"
    assert "session.commit()" not in source, "the use case commits; the caller owns that"
