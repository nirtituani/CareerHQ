"""T043 — the submit endpoint, and the reference an application exposes.

**Two routes' worth of surface, and the route owns none of the rules.**
`ensure_submittable` decides refusal, `latest_export` picks the document, `submit_version`
re-reads the stored bytes and re-verifies the checksum before writing anything (T038), and
`submission_for` is the single answer to *what did this application send* (T040). The
endpoint translates and commits.

**Two 409s that mean different things.** A wrong-state refusal is the person's to resolve
— export it first, or revise as a new version. A checksum mismatch is not: the stored
document is not the document its record describes, and clicking again cannot fix that. The
status code cannot separate them, so the message does, and the mismatch is **logged** as
well — an integrity failure that only ever produced a 409 would be invisible to whoever
has to explain it.

**Submission does not touch the application.** `docs/03` §10.2 says *"Moving to `Applied`
requires a Submitted Resume"* — the dependency runs that way, not the other — and
`date_applied` is a field the person fills in, defaulted in the form and editable
afterwards. Deriving either from a submission would overwrite what someone said about
their own history. Asserted below so the decision is checkable rather than remembered.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application import export_resume, submit_resume
from careerhq.application.export_resume import export_version
from careerhq.domain.models import (
    Application,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    SourceKind,
    SubmittedResume,
    User,
    VersionStatus,
)
from careerhq.domain.schemas.document import ResumeDocument
from careerhq.infrastructure import storage
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

_SENT = "Owned the settlement service end to end, from schema to on-call."


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    stored: dict[str, bytes] = {}

    def _render(document: ResumeDocument) -> bytes:
        return b"DOC\n" + "\n".join(document.lines_in_order()).encode()

    async def _put(key: str, data: bytes, *, content_type: str) -> None:
        stored[key] = data

    async def _get(key: str) -> bytes:
        return stored[key]

    monkeypatch.setattr(export_resume, "render_resume_pdf", _render)
    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "get_object", _get)
    return stored


async def _version(
    session: AsyncSession, *, sub: str, status: VersionStatus = VersionStatus.READY
) -> tuple[User, Application, ResumeVersion]:
    from careerhq.application.tailor_resume import create_pending_version

    seeded = await seed_tailorable(session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(session, seeded.application)
    session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.EXPERIENCE_BULLET,
            position=0,
            original_text=_SENT,
            final_text=_SENT,
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    version.status = status
    await session.commit()
    return seeded.user, seeded.application, version


async def _exported(session: AsyncSession, *, sub: str) -> tuple[User, Application, ResumeVersion]:
    user, application, version = await _version(session, sub=sub)
    await export_version(session, version_id=version.id)
    await session.commit()
    return user, application, version


# ======================================================================================
# POST /api/versions/{id}/submit
# ======================================================================================


async def test_submitting_an_exported_version_returns_the_version_and_its_submission(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
) -> None:
    """The contract: 200, the version at `submitted`, and the record's own facts."""
    user, _application, version = await _exported(db_session, sub="api-submit")

    response = await _as(client, user).post(f"/api/versions/{version.id}/submit")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(version.id)
    assert body["status"] == "submitted"

    submission = body["submission"]
    assert len(submission["checksum_sha256"]) == 64
    assert submission["byte_size"] > 0
    assert submission["submitted_at"]

    async with session_factory() as check:
        rows = list(
            (
                await check.execute(
                    sa.select(SubmittedResume).where(
                        SubmittedResume.resume_version_id == version.id
                    )
                )
            ).scalars()
        )
    assert len(rows) == 1
    assert rows[0].checksum_sha256 == submission["checksum_sha256"]


async def test_the_response_carries_no_internal_storage_address(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """The same rule `export` and `read_original` already follow.

    A storage key is an internal address. Publishing it hands a client something that
    only means anything to the bucket, invites it to be treated as a document reference,
    and outlives the route that returned it. The document is reached through
    `GET /versions/{id}/document`, which checks ownership.
    """
    user, _application, version = await _exported(db_session, sub="api-nokey")

    response = await _as(client, user).post(f"/api/versions/{version.id}/submit")

    assert response.status_code == 200, response.text
    assert "document_storage_key" not in response.json()["submission"]
    assert "exports/" not in response.text, "an object path reached the client"


async def test_a_version_that_was_never_exported_is_refused_with_409(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FR-021's precondition, surfaced rather than swallowed.

    409 is the status `approve` and `export` already use for a well-formed request the
    state refuses, and the guard's own sentence is returned — authored user-facing text,
    which is the case this project's detail-to-the-log rule exempts.
    """
    user, _application, version = await _version(db_session, sub="api-noexport")

    response = await _as(client, user).post(f"/api/versions/{version.id}/submit")

    assert response.status_code == 409, response.text
    assert "has not been exported" in response.json()["detail"]

    async with session_factory() as check:
        assert (await check.get(ResumeVersion, version.id)).status == VersionStatus.READY
        assert (
            await check.scalar(
                sa.select(sa.func.count())
                .select_from(SubmittedResume)
                .where(SubmittedResume.resume_version_id == version.id)
            )
        ) == 0


async def test_submitting_twice_is_refused_and_writes_no_second_record(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
) -> None:
    """A second send is a new version (FR-025), not a second row against this one."""
    user, _application, version = await _exported(db_session, sub="api-twice")

    first = await _as(client, user).post(f"/api/versions/{version.id}/submit")
    assert first.status_code == 200, first.text
    second = await _as(client, user).post(f"/api/versions/{version.id}/submit")

    assert second.status_code == 409, second.text
    assert "already been submitted" in second.json()["detail"]

    async with session_factory() as check:
        assert (
            await check.scalar(
                sa.select(sa.func.count())
                .select_from(SubmittedResume)
                .where(SubmittedResume.resume_version_id == version.id)
            )
        ) == 1


async def test_a_tampered_document_is_refused_distinctly_and_logged(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The mismatch reaches the client as its own answer, and the operator as a log line.

    **Both halves matter and they fail separately.** A person told "export it first" for
    a corrupted document is sent to do something that will not help; an operator who
    never hears about it learns that a stored résumé stopped matching its record only if
    somebody complains. The detail — which version, which export — goes to the log in
    `extra` fields, because Railway blanks the message of a parsed JSON log and keeps the
    structured ones.
    """
    user, _application, version = await _exported(db_session, sub="api-tamper")
    (key,) = fake_storage
    fake_storage[key] = b"DOC\nsomething else entirely"

    with caplog.at_level("ERROR"):
        response = await _as(client, user).post(f"/api/versions/{version.id}/submit")

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "no longer matches the checksum" in detail
    assert "has not been exported" not in detail, "corruption was reported as a wrong state"

    records = [r for r in caplog.records if "checksum" in r.getMessage().lower()]
    assert records, "a document that stopped matching its record was never logged"
    assert getattr(records[0], "version_id", None) == str(version.id)

    async with session_factory() as check:
        assert (await check.get(ResumeVersion, version.id)).status == VersionStatus.EXPORTED
        assert (await check.scalar(sa.select(sa.func.count()).select_from(SubmittedResume))) == 0


async def test_another_users_version_cannot_be_submitted(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
) -> None:
    """404, not 403: a 403 confirms the id names something real.

    Ownership comes from the session and never from the request — the rule every route
    here follows, and the one whose absence T037 found on the download only because the
    check was deliberately removed and nothing failed.
    """
    _owner, _application, version = await _exported(db_session, sub="api-owner")
    stranger = await seed_tailorable(db_session, sub="api-stranger", email="stranger@example.com")
    await db_session.commit()

    response = await _as(client, stranger.user).post(f"/api/versions/{version.id}/submit")

    assert response.status_code == 404, response.text

    async with session_factory() as check:
        assert (await check.get(ResumeVersion, version.id)).status == VersionStatus.EXPORTED
        assert (await check.scalar(sa.select(sa.func.count()).select_from(SubmittedResume))) == 0


async def test_a_version_that_does_not_exist_is_404(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    user, _application, _version = await _exported(db_session, sub="api-missing")

    response = await _as(client, user).post(f"/api/versions/{uuid.uuid4()}/submit")

    assert response.status_code == 404, response.text


async def test_the_endpoint_delegates_to_the_use_case(
    client: Any,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_storage: dict[str, bytes],
) -> None:
    """The route must call `submit_version`, not reproduce its guarantees.

    Asserted by replacing the use case: if the route still submits, it is doing the work
    itself — and T038's ordering, its re-read of the stored bytes and its checksum
    comparison apply to code nobody tested.
    """
    user, _application, version = await _exported(db_session, sub="api-delegate")

    calls: list[uuid.UUID] = []

    async def _refuse(session: object, *, version_id: uuid.UUID) -> None:
        calls.append(version_id)
        raise submit_resume.SubmissionRefused("stubbed")

    monkeypatch.setattr("careerhq.api.routes.tailoring.submit_version", _refuse)

    response = await _as(client, user).post(f"/api/versions/{version.id}/submit")

    assert calls == [version.id], "the route did not call the submit use case"
    assert response.status_code == 409
    assert response.json()["detail"] == "stubbed"


# ======================================================================================
# The application's reference (FR-024's acceptance scenario)
# ======================================================================================


async def test_an_application_exposes_the_submission_it_sent(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """*"Given an application in `Applied` or later, when I inspect it, then it references
    a submitted resume"* — `spec.md` scenario 4.

    The reference is resolved by `submission_for`, which is the single answer to that
    question (T040), rather than by a query written a second time here. It carries the
    version it names and the checksum, and **not** the storage key.
    """
    user, application, version = await _exported(db_session, sub="api-inspect")
    await _as(client, user).post(f"/api/versions/{version.id}/submit")

    response = await _as(client, user).get(f"/api/applications/{application.id}")

    assert response.status_code == 200, response.text
    submission = response.json()["submission"]
    assert submission is not None
    assert submission["resume_version_id"] == str(version.id)
    assert len(submission["checksum_sha256"]) == 64
    assert submission["submitted_at"]
    assert "document_storage_key" not in submission
    assert "exports/" not in response.text


async def test_an_application_that_sent_nothing_reports_nothing(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """`null`, not a nearest-available document.

    T040's rule, at the surface: an application that reached `Applied` outside CareerHQ —
    every imported row does — has no document here, and the honest answer is absence. A
    fallback to the latest export would answer confidently about something nobody sent.
    """
    user, application, _version = await _exported(db_session, sub="api-nothing")

    response = await _as(client, user).get(f"/api/applications/{application.id}")

    assert response.status_code == 200, response.text
    assert response.json()["submission"] is None


async def test_another_users_application_does_not_disclose_its_submission(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """Ownership is checked before anything about a submission is read."""
    user, application, version = await _exported(db_session, sub="api-private")
    await _as(client, user).post(f"/api/versions/{version.id}/submit")
    stranger = await seed_tailorable(db_session, sub="api-peeper", email="peeper@example.com")
    await db_session.commit()

    response = await _as(client, stranger.user).get(f"/api/applications/{application.id}")

    assert response.status_code == 404, response.text


# ======================================================================================
# What submission deliberately does NOT do
# ======================================================================================


async def test_submitting_changes_neither_the_application_status_nor_the_date_applied(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
) -> None:
    """The product decision T038 deferred, resolved from the sources and pinned here.

    **The dependency runs the other way.** `docs/03` §10.2: *"Moving to `Applied`
    requires a Submitted Resume."* Nothing in FR-020 to FR-025 says a submission moves an
    application, and `docs/03` §5.2 says only that an `Applied` application must
    reference one.

    **`date_applied` is the person's own record**, asked for in the form once the status
    is `Applied` or later and editable afterwards. Deriving it from a submission would
    overwrite what they said about their own history — and `date_added` and `date_applied`
    are separate columns precisely so *"this sat in Pre-Applied for 46 days"* stays
    computable.

    **And the status label is their words.** `normalized_status` is derived from it, never
    the reverse, so a system that set a status would be inventing the label a person uses
    for their own job search. Marking the job as applied is a decision they make, on the
    application, through the route that already exists for it.
    """
    user, application, version = await _exported(db_session, sub="api-nostatus")

    async with session_factory() as before_session:
        before = await before_session.get(Application, application.id)
        assert before is not None
        status_before = before.status
        normalized_before = before.normalized_status
        applied_before = before.date_applied
        history_before = len(before.status_history)

    response = await _as(client, user).post(f"/api/versions/{version.id}/submit")
    assert response.status_code == 200, response.text

    async with session_factory() as check:
        after = await check.get(Application, application.id)
        assert after is not None
        assert after.status == status_before, "submitting rewrote the person's own label"
        assert after.normalized_status == normalized_before
        assert after.date_applied == applied_before, (
            "submitting overwrote the date the person said they applied"
        )
        assert len(after.status_history) == history_before, (
            "submitting appended a status history row nobody asked for"
        )
