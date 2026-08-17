"""Recording a job to tailor against (T060-T064, T067).

User Story 2. An application is a job the user is pursuing: a company, a title,
and — the reason this story exists at all — the **job description text** that
slice 004 tailors a resume against.

Four invariants run through these tests, and each is here because the failure it
guards against is silent:

* An application is valid with **no** submitted resume (FR-011). Submitted
  Resumes arrive in slice 004; a pre-submission application must not be waiting
  on a table that does not exist yet.
* Another user's application is **404, not 403** (FR-019). A 403 confirms the
  row exists, which is the disclosure the isolation requirement is about.
* Status history is **insert-only** (FR-012, Constitution IV, constraint C6).
* There is **no `rejected` column anywhere** (FR-016). Its enforcement is an
  absence, so nothing breaks when it grows back — see the last test in this
  file, which is the only thing that would catch it.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.api.deps import get_structured_completion
from careerhq.application.ports import Completion, Usage
from careerhq.application.provision_user import provision_user
from careerhq.domain.models import User
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "careerhq"

ALICE = {"sub": "google-alice", "email": "alice@example.com", "name": "Alice"}
BOB = {"sub": "google-bob", "email": "bob@example.com", "name": "Bob"}

#: A real posting's worth of text. The point of US2 is that this is *stored*,
#: not linked to — slice 004 cannot tailor against a URL it would have to fetch.
JOB_DESCRIPTION = """\
We are looking for a Senior Backend Engineer to join our platform team.

Responsibilities:
- Design and operate services handling millions of requests per day
- Mentor engineers and raise the bar on code review

Requirements:
- 5+ years building production systems in Python or Go
- Experience with PostgreSQL and asynchronous architectures
"""


async def _user(session: AsyncSession, claims: dict[str, str]) -> User:
    user = await provision_user(session, claims)
    await session.commit()
    return user


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


async def _create(client: httpx.AsyncClient, user: User, **overrides: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "company": "Acme Corporation",
        "job_title": "Senior Backend Engineer",
        "job_description": JOB_DESCRIPTION,
        "location": "Tel Aviv",
        "status": "Pre-Applied",
    }
    body.update(overrides)
    return await _as(client, user).post("/api/applications", json=body)


class _StubCompletion:
    """A completion client returning a fixed posting. No network, no key.

    The suite makes no provider call anywhere (FR-027, obligation O6). Without
    this the extraction tests reach the real API with the fake test key and fail
    on authentication — which is what happened the first time they ran, and is
    the reason this exists rather than a convenience.
    """

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        return Completion(
            value=schema.model_validate(
                {
                    "company": "Acme Corporation",
                    "job_title": "Senior Backend Engineer",
                    "location": "Tel Aviv",
                    "job_description": "Build and operate services.",
                }
            ),
            usage=Usage(
                model="stub/model", input_tokens=100, output_tokens=50, cost=Decimal("0.001")
            ),
        )


@pytest.fixture
def stub_completion(app: object) -> Iterator[None]:
    """Override the completion seam for the extraction tests."""
    app.dependency_overrides[get_structured_completion] = _StubCompletion  # type: ignore[attr-defined]
    yield
    app.dependency_overrides.pop(get_structured_completion, None)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# T060 — valid without a submitted resume
# ---------------------------------------------------------------------------


async def test_an_application_is_valid_with_no_submitted_resume(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-011. A job you have not applied to yet is the normal starting state.

    Nothing in the request names a resume, and nothing in the schema requires
    one — `submitted_resume_id` is deliberately absent until slice 004
    (data-model.md §3).
    """
    alice = await _user(db_session, ALICE)

    response = await _create(client, alice)

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["job_title"] == "Senior Backend Engineer"
    assert created["normalized_status"] == "wishlist"
    assert "submitted_resume_id" not in created

    # Stored in full, not truncated or replaced by the URL it came from.
    fetched = await _as(client, alice).get(f"/api/applications/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["job_description"] == JOB_DESCRIPTION


# ---------------------------------------------------------------------------
# T061 — isolation, and 404 rather than 403
# ---------------------------------------------------------------------------


async def test_one_users_application_is_invisible_to_another(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-019. Bob's list must not contain Alice's job."""
    alice = await _user(db_session, ALICE)
    bob = await _user(db_session, BOB)

    await _create(client, alice)

    alice_list = await _as(client, alice).get("/api/applications")
    bob_list = await _as(client, bob).get("/api/applications")

    assert len(alice_list.json()["applications"]) == 1
    assert bob_list.json()["applications"] == []


async def test_another_users_application_is_404_not_403(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-019, contracts/http-api.md.

    A 403 would confirm the id names something real. The endpoint must not
    distinguish "someone else's application" from "no such application".
    """
    alice = await _user(db_session, ALICE)
    bob = await _user(db_session, BOB)

    created = (await _create(client, alice)).json()

    for method in ("get", "patch"):
        request = getattr(_as(client, bob), method)
        response = await (
            request(f"/api/applications/{created['id']}", json={"status": "Applied"})
            if method == "patch"
            else request(f"/api/applications/{created['id']}")
        )
        assert response.status_code == 404, f"{method.upper()} leaked existence: {response.text}"


# ---------------------------------------------------------------------------
# T062 — status history is written on every change, and never mutated
# ---------------------------------------------------------------------------


async def test_every_status_change_writes_a_history_row(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-012. The timeline is the record; the current status is a projection."""
    alice = await _user(db_session, ALICE)
    created = (await _create(client, alice)).json()

    patched = await _as(client, alice).patch(
        f"/api/applications/{created['id']}", json={"status": "Phone Screen"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["normalized_status"] == "interviewing"

    rows = (
        await db_session.execute(
            text(
                "SELECT from_status, to_status, normalized_to_status"
                " FROM application_status_history"
                " WHERE application_id = :id ORDER BY changed_at"
            ),
            {"id": created["id"]},
        )
    ).all()

    # Creation records the opening status, so the timeline is complete from the
    # first row rather than starting at the first edit.
    assert [tuple(row) for row in rows] == [
        (None, "Pre-Applied", "wishlist"),
        ("Pre-Applied", "Phone Screen", "interviewing"),
    ]


async def test_a_patch_that_does_not_change_status_writes_no_history_row(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """ "Every status change" is not "every write". Editing notes is not a move."""
    alice = await _user(db_session, ALICE)
    created = (await _create(client, alice)).json()

    await _as(client, alice).patch(
        f"/api/applications/{created['id']}", json={"notes": "Referred by Dana"}
    )

    count = await db_session.scalar(
        text("SELECT count(*) FROM application_status_history WHERE application_id = :id"),
        {"id": created["id"]},
    )
    assert count == 1


def test_no_code_path_updates_or_deletes_status_history() -> None:
    """Constraint C6, Constitution IV — asserted against the source tree.

    An append-only table stays append-only only while nothing can write to it
    any other way. Nothing fails at runtime when an UPDATE appears: the feature
    works, and the audit trail quietly stops being one.

    Parsed rather than grepped, so this file's own prose about deletion does not
    count as a deletion.
    """
    offenders: dict[str, list[str]] = {}

    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        hits: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else ""
            )
            if name not in {"delete", "update"}:
                continue

            # `sa.delete(ApplicationStatusHistory)` / `session.delete(row)` where
            # the argument names the history model.
            mentions = {
                n.id
                for n in ast.walk(node)
                if isinstance(n, ast.Name) and n.id == "ApplicationStatusHistory"
            }
            if mentions:
                hits.append(f"{name}() at line {node.lineno}")

        if hits:
            offenders[str(path.relative_to(SRC))] = hits

    assert offenders == {}, (
        f"application_status_history must be insert-only; found writes: {offenders}"
    )


# ---------------------------------------------------------------------------
# T063 — one company row per name, per user
# ---------------------------------------------------------------------------


async def test_two_applications_at_the_same_company_share_one_company_row(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-014, constraint C2.

    Matched on the normalized name, so the punctuation and casing a person
    happens to type on a Tuesday does not fork the company.
    """
    alice = await _user(db_session, ALICE)

    first = (await _create(client, alice, company="Acme Corporation")).json()
    second = (
        await _create(client, alice, company="  acme corporation.", job_title="Staff Engineer")
    ).json()

    assert first["company"]["id"] == second["company"]["id"]
    # The name is preserved as entered on the row that created it.
    assert first["company"]["name"] == "Acme Corporation"

    count = await db_session.scalar(
        text("SELECT count(*) FROM companies WHERE user_id = :id"), {"id": str(alice.id)}
    )
    assert count == 1


async def test_two_users_naming_the_same_company_own_separate_rows(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """C2 is scoped to the user. Companies are notes, not a shared directory."""
    alice = await _user(db_session, ALICE)
    bob = await _user(db_session, BOB)

    alice_app = (await _create(client, alice, company="Acme Corporation")).json()
    bob_app = (await _create(client, bob, company="Acme Corporation")).json()

    assert alice_app["company"]["id"] != bob_app["company"]["id"]


# ---------------------------------------------------------------------------
# T064 — normalized_status is derived, never supplied
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Pre-Applied", "wishlist"),
        ("Applied", "applied"),
        ("Final Interview", "interviewing"),
        ("Offer Received", "offer"),
        ("Rejected", "rejected"),
        ("Withdrawn", "withdrawn"),
        ("Ghosted", "ghosted"),
        # The common case, not the exotic one: JobTracker keeps custom statuses
        # in localStorage, so they never reach an export (R8, Finding 3).
        ("Waiting on referral", "other"),
    ],
)
async def test_the_normalized_status_is_derived_from_the_label(
    client: httpx.AsyncClient, db_session: AsyncSession, label: str, expected: str
) -> None:
    """FR-013. The label is whatever the user calls it; the category is ours."""
    alice = await _user(db_session, ALICE)

    created = (await _create(client, alice, status=label)).json()

    assert created["status"] == label, "the user's own words must survive verbatim"
    assert created["normalized_status"] == expected


async def test_a_request_cannot_set_the_normalized_status_directly(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-013. A client-settable normalized status is a second source of truth.

    Two fields describing one fact drift, and the analytics category is the one
    the Career Advisor reasons over — so the label wins and the request's
    attempt is ignored.
    """
    alice = await _user(db_session, ALICE)

    created = (await _create(client, alice, status="Applied", normalized_status="offer")).json()
    assert created["normalized_status"] == "applied"

    patched = await _as(client, alice).patch(
        f"/api/applications/{created['id']}",
        json={"status": "Rejected", "normalized_status": "offer"},
    )
    assert patched.json()["normalized_status"] == "rejected"


# ---------------------------------------------------------------------------
# T067 — the release blocker: no `rejected` column, anywhere
# ---------------------------------------------------------------------------


async def test_no_column_named_rejected_exists_anywhere(db_session: AsyncSession) -> None:
    """FR-016, docs/03 §14. **Release blocker.**

    Rejection is a value of `normalized_status` and nothing else. A boolean
    beside it is a second source of truth for the same fact, and the two drift
    the first time one is updated without the other.

    This is enforced by an **absence**, which is why it needs a test at all:
    nothing fails when the column comes back. **Failure looks like**: any row
    returned below.
    """
    rows = (
        await db_session.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND column_name = 'rejected'"
            )
        )
    ).all()

    assert rows == [], (
        "FR-016: rejection is a normalized_status value, never a column. Found: "
        f"{[tuple(row) for row in rows]}"
    )


# ---------------------------------------------------------------------------
# Dates and the company website (the Add Application form's remaining fields)
# ---------------------------------------------------------------------------


async def test_a_date_only_string_is_stored_as_a_date(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The form sends `2026-08-15`; the column is a timestamp.

    Left as a raw string this reaches the driver as text and either fails or is
    cast by PostgreSQL on a good day — behaviour that depends on the driver
    rather than on us. Parsed explicitly instead.
    """
    alice = await _user(db_session, ALICE)

    created = (await _create(client, alice, date_added="2026-08-15")).json()

    assert created["date_added"].startswith("2026-08-15")


async def test_an_application_starts_with_no_applied_date(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A Pre-Applied job has not been applied to, so there is no applied date.

    `date_added` still records when it was added — that is the pair that makes
    "this sat in Pre-Applied for 34 days" computable. One field overwritten at
    the transition would lose it.
    """
    alice = await _user(db_session, ALICE)

    created = (await _create(client, alice, status="Pre-Applied")).json()

    assert created["date_applied"] is None
    assert created["date_added"] is not None


async def test_applying_records_the_applied_date_and_how(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Applied Via and Date Applied arrive together, at the moment of applying.

    Both are meaningless on a job nobody has applied to yet — which is why the
    form asks for them only once the status is Applied or later, rather than up
    front as the source app did.
    """
    alice = await _user(db_session, ALICE)
    created = (await _create(client, alice, status="Pre-Applied")).json()

    patched = (
        await _as(client, alice).patch(
            f"/api/applications/{created['id']}",
            json={"status": "Applied", "date_applied": "2026-08-17", "source": "Referral"},
        )
    ).json()

    assert patched["date_applied"].startswith("2026-08-17")
    assert patched["source"] == "Referral"
    # The added date is untouched: the two answer different questions.
    assert patched["date_added"] == created["date_added"]


async def test_the_company_website_is_stored_on_the_company(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`Company Website (for logo)` — docs/09 §6.2's logo column needs a domain.

    Stored on the company rather than the application: it is a fact about the
    employer, so a second job there should not need it typed again.
    """
    alice = await _user(db_session, ALICE)

    first = (
        await _create(client, alice, company="Acme Corporation", company_domain="acme.com")
    ).json()
    assert first["company"]["domain"] == "acme.com"

    # A second job at the same employer inherits it without retyping.
    second = (await _create(client, alice, company="acme corporation", job_title="Staff")).json()
    assert second["company"]["domain"] == "acme.com"


# ---------------------------------------------------------------------------
# Extracting a posting from a URL or from pasted text
# ---------------------------------------------------------------------------


async def test_extraction_never_creates_an_application(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """Principle II. The model fills the form; the person saves it.

    An endpoint that created the record directly would be an extraction writing
    to the database unreviewed, which is the gate this system is built around.
    """
    alice = await _user(db_session, ALICE)

    response = await _as(client, alice).post(
        "/api/applications/extract",
        json={"text": "Acme Corporation is hiring a Senior Backend Engineer in Tel Aviv. " * 20},
    )

    assert response.status_code == 200, response.text
    assert "id" not in response.json()

    count = await db_session.scalar(text("SELECT count(*) FROM applications"))
    assert count == 0


async def test_extraction_reports_how_the_fields_were_obtained(
    client: httpx.AsyncClient, db_session: AsyncSession, stub_completion: None
) -> None:
    """The user is told whether the employer published this or a model read it.

    Those deserve different trust, and the interface marks the difference.
    """
    alice = await _user(db_session, ALICE)

    body = (
        await _as(client, alice).post(
            "/api/applications/extract",
            json={"text": "A posting for a Staff Engineer at Acme. " * 20},
        )
    ).json()

    assert body["provenance"] in {"structured_data", "model"}
    assert "posting" in body


async def test_extraction_refuses_a_url_pointing_inside_the_network(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """SSRF, asserted at the endpoint rather than only at the guard.

    This is the reachable surface: an authenticated user typing an address into
    a form. The metadata endpoint and the database are both one request away
    from the process that serves this route.
    """
    alice = await _user(db_session, ALICE)

    for url in ("http://169.254.169.254/latest/meta-data/", "http://backend:8000/api/health"):
        response = await _as(client, alice).post("/api/applications/extract", json={"url": url})
        assert response.status_code == 400, f"{url} was not refused: {response.text}"
        # The refusal must not report what it found there.
        assert "meta-data" not in response.text


async def test_extraction_requires_a_session(client: httpx.AsyncClient) -> None:
    """An unauthenticated fetcher is an open proxy with our IP on it."""
    client.cookies.clear()
    response = await client.post("/api/applications/extract", json={"text": "x" * 300})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Row actions carried over from the source app: reject, undo, delete
# ---------------------------------------------------------------------------


async def test_marking_rejected_moves_the_status_rather_than_setting_a_flag(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The source app's circled-✕, without the column behind it.

    There it set `rejected = true` beside a status that kept saying "Interview
    Round 2", and every read had to reconcile the two. Here the same button
    moves the status, so there is still exactly one source of truth (FR-016)
    and the move is recorded in history like any other.
    """
    alice = await _user(db_session, ALICE)
    created = (await _create(client, alice, status="Interview Round 2")).json()

    rejected = (
        await _as(client, alice).patch(
            f"/api/applications/{created['id']}", json={"status": "Rejected"}
        )
    ).json()

    assert rejected["normalized_status"] == "rejected"
    assert [row["to_status"] for row in rejected["status_history"]] == [
        "Interview Round 2",
        "Rejected",
    ]


async def test_undoing_a_rejection_restores_the_status_it_came_from(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The source app's "Undo rejection", which its flag made trivial.

    Clearing a boolean is easy; the cost was that the status underneath had
    quietly stopped meaning anything. Here the previous status is read back out
    of the history, which is exactly what an append-only timeline is for — and
    the undo is itself recorded rather than erasing the rejection.
    """
    alice = await _user(db_session, ALICE)
    created = (await _create(client, alice, status="Interview Round 2")).json()
    await _as(client, alice).patch(
        f"/api/applications/{created['id']}", json={"status": "Rejected"}
    )

    restored = (await _as(client, alice).post(f"/api/applications/{created['id']}/unreject")).json()

    assert restored["status"] == "Interview Round 2"
    assert restored["normalized_status"] == "interviewing"
    # Nothing was rewritten: the rejection is still in the record.
    assert [row["to_status"] for row in restored["status_history"]] == [
        "Interview Round 2",
        "Rejected",
        "Interview Round 2",
    ]


async def test_an_application_can_be_deleted_by_its_owner_only(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The trash action. Someone else's is 404, like every other route."""
    alice = await _user(db_session, ALICE)
    bob = await _user(db_session, BOB)
    created = (await _create(client, alice)).json()

    assert (await _as(client, bob).delete(f"/api/applications/{created['id']}")).status_code == 404

    assert (
        await _as(client, alice).delete(f"/api/applications/{created['id']}")
    ).status_code == 204
    assert (await _as(client, alice).get(f"/api/applications/{created['id']}")).status_code == 404

    # The history goes with it. Constitution IV forbids *rewriting* the
    # timeline, not a person deleting their own record outright.
    orphans = await db_session.scalar(
        text("SELECT count(*) FROM application_status_history WHERE application_id = :id"),
        {"id": created["id"]},
    )
    assert orphans == 0
