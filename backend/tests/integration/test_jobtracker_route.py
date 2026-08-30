"""T082 — `POST /api/applications/import/jobtracker`.

The use case is tested in `test_jobtracker_import.py`; this file is about the **edge**: who may
call it, what a client actually receives, and what happens to a file that is too large or is not
an export at all.

**Ownership is the claim worth the most here.** A JobTracker export carries the `user_id` of
whoever exported it, and the endpoint accepts that file from anyone signed in. If the column were
honoured, uploading someone else's export would attribute rows to their account — so the test
below imports a file whose every row says `user_id=99` and asserts the rows belong to the
*caller*, twice over: once through the API and once by counting a second user's applications.
"""

from __future__ import annotations

import csv
import io
import pathlib
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.api.routes.imports import MAX_UPLOAD_BYTES
from careerhq.application import import_jobtracker as import_jobtracker_module
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import User
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

pytestmark = pytest.mark.asyncio

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "jobtracker_export.csv"
ENDPOINT = "/api/applications/import/jobtracker"

ALICE = {"sub": "google-jt-alice", "email": "jt-alice@example.com", "name": "Alice"}
BOB = {"sub": "google-jt-bob", "email": "jt-bob@example.com", "name": "Bob"}


async def _user(session: AsyncSession, claims: dict[str, str]) -> User:
    user: User = await provision_user(session, claims)
    await session.commit()
    return user


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


def _upload(data: bytes | None = None) -> dict[str, Any]:
    payload = FIXTURE.read_bytes() if data is None else data
    return {"file": ("jobtracker_export.csv", payload, "text/csv")}


# ======================================================================================
# Authentication and ownership
# ======================================================================================


async def test_the_endpoint_requires_a_session(client: httpx.AsyncClient) -> None:
    """Unauthenticated is 401. An open import endpoint writes to whichever account it likes."""
    client.cookies.clear()

    response = await client.post(ENDPOINT, files=_upload())

    assert response.status_code == 401, response.text


async def test_the_rows_belong_to_the_caller_not_to_the_files_user_id(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-019, at the edge.

    The fixture's row 108 carries `user_id=99`. Every imported row must belong to the session
    user — and a *second* signed-in user must see none of them, which is the assertion that
    would catch an importer that honoured the column rather than the cookie.
    """
    alice = await _user(db_session, ALICE)
    bob = await _user(db_session, BOB)

    response = await _as(client, alice).post(ENDPOINT, files=_upload())
    assert response.status_code == 200, response.text

    alice_list = await _as(client, alice).get("/api/applications")
    bob_list = await _as(client, bob).get("/api/applications")

    assert len(alice_list.json()["applications"]) == response.json()["imported"]
    assert bob_list.json()["applications"] == [], "another user received the imported rows"


async def test_no_route_accepts_a_user_id(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A client-supplied owner must be ignored, not honoured.

    The endpoint takes multipart, so there is no body field to smuggle one in — but a query
    parameter is the cheap thing to try, and "it is not in the signature" is a claim worth an
    assertion rather than a reading of the code.
    """
    alice = await _user(db_session, ALICE)
    bob = await _user(db_session, BOB)

    response = await _as(client, alice).post(f"{ENDPOINT}?user_id={bob.id}", files=_upload())
    assert response.status_code == 200, response.text

    bob_list = await _as(client, bob).get("/api/applications")
    assert bob_list.json()["applications"] == [], "a query parameter chose the owner"


# ======================================================================================
# The response
# ======================================================================================


async def test_a_successful_import_returns_the_report(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """200 with imported, skipped, rejected-with-reasons, and notices (contracts/http-api.md)."""
    alice = await _user(db_session, ALICE)

    response = await _as(client, alice).post(ENDPOINT, files=_upload())

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"imported", "skipped", "rejected", "notices"}, body
    assert body["imported"] > 0
    assert body["skipped"] >= 1, "the file's repeated row was not reported"

    reasons = {row["source_id"]: row["reason"] for row in body["rejected"]}
    assert set(reasons) == {"106", "107"}, reasons
    assert all(reason for reason in reasons.values()), "a rejection carries no reason"

    assert any("ASAP" in notice["message"] for notice in body["notices"]), body["notices"]


async def test_the_imported_rows_are_readable_immediately(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The route commits. Without it the report would describe rows nobody can see."""
    alice = await _user(db_session, ALICE)

    imported = (await _as(client, alice).post(ENDPOINT, files=_upload())).json()["imported"]
    listing = await _as(client, alice).get("/api/applications")

    assert len(listing.json()["applications"]) == imported


async def test_the_rejected_flag_arrives_as_a_status_not_a_field(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-016 through the API. **No response field is named `rejected`.**

    An API field is exactly how a removed column grows back, which is why the contract says so
    explicitly and why this is asserted on the payload rather than on the model.
    """
    alice = await _user(db_session, ALICE)
    await _as(client, alice).post(ENDPOINT, files=_upload())

    listing = (await _as(client, alice).get("/api/applications")).json()["applications"]
    assert listing, "nothing was examined"

    interviewed = [row for row in listing if row["status"] == "Interview Round 2"]
    assert len(interviewed) == 1, [row["status"] for row in listing]
    assert interviewed[0]["normalized_status"] == "rejected"
    assert "rejected" not in interviewed[0], "a rejected field came back on an application"


async def test_re_uploading_the_same_file_reports_everything_as_skipped(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A retry is safe and says so — it is not an error, and it creates nothing."""
    alice = await _user(db_session, ALICE)

    first = (await _as(client, alice).post(ENDPOINT, files=_upload())).json()
    second_response = await _as(client, alice).post(ENDPOINT, files=_upload())

    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["imported"] == 0
    assert second["skipped"] == first["imported"] + first["skipped"]

    listing = await _as(client, alice).get("/api/applications")
    assert len(listing.json()["applications"]) == first["imported"]


# ======================================================================================
# Refusals
# ======================================================================================


@pytest.mark.parametrize(
    "payload",
    [b"", b"not a csv at all", b"id,user_id\n1,2\n"],
    ids=["empty", "not-csv", "wrong-columns"],
)
async def test_a_file_that_is_not_an_export_is_400_and_writes_nothing(
    client: httpx.AsyncClient, db_session: AsyncSession, payload: bytes
) -> None:
    """400 per the contract, and the refusal leaves no trace."""
    alice = await _user(db_session, ALICE)

    response = await _as(client, alice).post(ENDPOINT, files=_upload(payload))

    assert response.status_code == 400, response.text
    listing = await _as(client, alice).get("/api/applications")
    assert listing.json()["applications"] == [], "a refused upload wrote rows"


async def test_the_refusal_names_the_missing_columns(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """ "Not a recognised export" alone leaves someone guessing which file to upload.

    The names are the source's own column names, so this discloses nothing internal — the same
    judgement `/extract` makes when it hands a fetch failure to the browser.
    """
    alice = await _user(db_session, ALICE)

    response = await _as(client, alice).post(ENDPOINT, files=_upload(b"id,user_id\n1,2\n"))

    assert "company" in response.json()["detail"]


async def test_a_file_over_the_upload_limit_is_413(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The same guard and the same limit as the CV upload, imported rather than re-typed.

    Two copies of a size limit drift, and the one that drifts is always the newer one.
    """
    alice = await _user(db_session, ALICE)

    header = ",".join(
        [
            "id,user_id,company,title,location,date_applied,status,salary_range,job_link",
            "contact_person,contact_email,applied_via,match_rating,notes,last_updated",
            "job_desc_link,rejected,company_domain",
        ]
    )
    oversize = (header + "\n").encode() + b"x" * (MAX_UPLOAD_BYTES + 1)

    response = await _as(client, alice).post(ENDPOINT, files=_upload(oversize))

    assert response.status_code == 413, response.status_code
    assert "10 MB" in response.json()["detail"]


async def test_the_size_guard_runs_before_the_file_is_parsed(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """An oversize file that is *also* unreadable must be 413, not 400.

    Parsing first would mean spending the work before deciding the file was too big to accept —
    and would report the wrong reason, sending someone to fix a format problem they do not have.
    """
    alice = await _user(db_session, ALICE)

    response = await _as(client, alice).post(
        ENDPOINT, files=_upload(b"nonsense" * (MAX_UPLOAD_BYTES // 4))
    )

    assert response.status_code == 413, response.text


async def test_a_csv_with_an_oversized_field_is_400_rather_than_500(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """**Found by drilling the size guard, not by writing the happy path.**

    `csv.Error` does **not** inherit from `ValueError` — its bases are `Exception`, `object` —
    so a `except ValueError` around the parser does not catch it. Python's reader refuses any
    field over `csv.field_size_limit()`, 131072 bytes by default, which a file well under the
    10 MB upload limit reaches easily: one long `notes` value does it.

    The result was an unhandled exception, so the caller got a **500** for a file the system
    understood perfectly well was malformed. That inverts the rule this project applies
    everywhere else — the detail belongs in the log, the *type* belongs in the response — and a
    500 tells a person to report a bug rather than to fix their file.
    """
    alice = await _user(db_session, ALICE)

    with FIXTURE.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerow({**rows[0], "notes": "x" * 200_000})
    payload = buffer.getvalue().encode()

    assert len(payload) < MAX_UPLOAD_BYTES, "this must test the parser, not the size guard"

    response = await _as(client, alice).post(ENDPOINT, files=_upload(payload))

    assert response.status_code == 400, f"got {response.status_code}: {response.text[:200]}"
    listing = await _as(client, alice).get("/api/applications")
    assert listing.json()["applications"] == [], "a refused upload wrote rows"


async def test_two_imports_racing_the_same_rows_is_409_and_writes_nothing(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented 409, exercised through the one thing that actually produces it.

    **The race is simulated by making the duplicate check stale, because that *is* the race.**
    `_already_imported` reads which rows exist and the writes happen afterwards; a second upload
    landing in between makes that read wrong. Forcing it to return nothing reproduces the exact
    state a concurrent importer creates, without needing two requests to interleave on a
    schedule no test can control.

    A driver-level failure reaching the client as a 500 was the alternative, and it would have
    carried the constraint name, the table and the values with it.
    """
    alice = await _user(db_session, ALICE)
    assert (await _as(client, alice).post(ENDPOINT, files=_upload())).status_code == 200

    listing_before = (await _as(client, alice).get("/api/applications")).json()["applications"]

    async def _stale(*_: object, **__: object) -> set[str]:
        return set()

    monkeypatch.setattr(import_jobtracker_module, "_already_imported", _stale)

    response = await _as(client, alice).post(ENDPOINT, files=_upload())

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    # The refusal must not double as a description of the schema.
    for leak in ("uq_", "constraint", "applications", "import_source", "psycopg", "DETAIL"):
        assert leak not in detail, f"the 409 disclosed {leak!r}: {detail}"

    listing_after = (await _as(client, alice).get("/api/applications")).json()["applications"]
    assert len(listing_after) == len(listing_before), "a refused import wrote rows"


async def test_a_missing_file_is_a_422_rather_than_a_crash(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FastAPI's own validation, asserted so a later signature change cannot turn it into a 500."""
    alice = await _user(db_session, ALICE)

    response = await _as(client, alice).post(ENDPOINT)

    assert response.status_code == 422, response.text


async def test_an_export_with_extra_columns_still_imports(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A future JobTracker column must not break the import.

    The check is "every column we need is present", not "the columns are exactly these" — a
    stricter rule would reject a newer export for containing *more* information.
    """
    alice = await _user(db_session, ALICE)

    with FIXTURE.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[*rows[0].keys(), "some_new_column"])
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "some_new_column": "ignored"})

    response = await _as(client, alice).post(ENDPOINT, files=_upload(buffer.getvalue().encode()))

    assert response.status_code == 200, response.text
    assert response.json()["imported"] > 0
