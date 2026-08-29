"""Two people, one button, one résumé — FR-021 and FR-025 under a race.

**A second send is a new version, never a second row against the old one**, and the
schema is what makes that true: `submitted_resumes` is unique on `resume_version_id`
because, in this project's words, *"two clicks can race an application-level check"*.

The check `submit_version` performs is exactly such a read-then-write: it reads the
version's status, goes to object storage, hashes what came back, and only then inserts.
Two requests that arrive together both read `EXPORTED`, both verify, and both try to
insert. The constraint refuses the second — so the **record** was never at risk.

**What was at risk is what the loser is told.** An `IntegrityError` escaping the use case
reaches the route as an unhandled exception and the person gets a **500**, which says the
system broke. It did not: it refused, correctly, for a reason that has a sentence already
written for it. FR-022 requires a refusal to be *explicit*, and a stack trace is not.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application.submit_resume import (
    ExportChecksumMismatch,
    SubmissionRefused,
    _is_duplicate_submission,
    submit_version,
)
from careerhq.application.tailor_resume import create_pending_version
from careerhq.domain.models import (
    ExportedDocument,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    SourceKind,
    SubmittedResume,
    User,
    VersionStatus,
)
from careerhq.infrastructure import storage
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

_PDF = b"%PDF-1.7\nthe-document-that-was-sent\n%%EOF\n"


class _Storage:
    """Object storage that **holds every reader until both have arrived.**

    ***The barrier is what makes this a race rather than a sequence, and a first
    attempt without it silently tested nothing.*** Left to `asyncio.gather` alone, the
    first coroutine ran to completion — commit included — before the second read the
    version, so the second was refused by `ensure_submittable` on a status that was
    already `SUBMITTED`. That is the *sequential* path. It produces the same refusal and
    the same message, so every assertion passed while the concurrent code path was never
    entered.

    Blocking here fixes the interleaving where it matters: a racer parked in this call
    has passed the guard and **cannot have committed**, so the other necessarily still
    sees `EXPORTED`, passes the guard too, and both reach the insert. No deadlock is
    possible for that reason — and the timeout turns one into a failure rather than a
    hang if that reasoning is ever wrong.
    """

    def __init__(self, parties: int = 2) -> None:
        self.objects: dict[str, bytes] = {}
        self.reads = 0
        self._barrier = asyncio.Barrier(parties)

    async def get(self, key: str) -> bytes:
        self.reads += 1
        async with asyncio.timeout(10):
            await self._barrier.wait()
        return self.objects[key]

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Storage:
    fake = _Storage()
    monkeypatch.setattr(storage, "get_object", fake.get)
    monkeypatch.setattr(storage, "put_object", fake.put)
    return fake


async def _exported(
    session: AsyncSession, store: _Storage, *, sub: str
) -> tuple[User, ResumeVersion]:
    """An `EXPORTED` version with real stored bytes, committed and visible to every session."""
    seeded = await seed_tailorable(session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(session, seeded.application)
    session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.EXPERIENCE_BULLET,
            position=0,
            original_text="Owned the settlement service end to end.",
            final_text="Owned the settlement service end to end.",
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    key = f"exports/{version.profile_id}/{version.id}/{uuid.uuid4()}.pdf"
    store.objects[key] = _PDF
    session.add(
        ExportedDocument(
            resume_version_id=version.id,
            document_storage_key=key,
            checksum_sha256=hashlib.sha256(_PDF).hexdigest(),
            byte_size=len(_PDF),
        )
    )
    version.status = VersionStatus.EXPORTED
    await session.commit()
    return seeded.user, version


async def _submit_in_own_session(
    factory: async_sessionmaker[AsyncSession], version_id: uuid.UUID
) -> object:
    """One racer: its own session, its own transaction, committing on success."""
    async with factory() as session:
        try:
            record = await submit_version(session, version_id=version_id)
            await session.commit()
            return record.id
        except BaseException as failure:
            await session.rollback()
            return failure


async def test_two_simultaneous_submissions_write_exactly_one_record(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    store: _Storage,
) -> None:
    """The invariant, and the refusal, and the verification — all three at once.

    Genuinely concurrent: two independent sessions, started together with
    `asyncio.gather`, interleaving inside the object-storage read.
    """
    _user, version = await _exported(db_session, store, sub="race-submit")

    first, second = await asyncio.gather(
        _submit_in_own_session(session_factory, version.id),
        _submit_in_own_session(session_factory, version.id),
    )
    outcomes = [first, second]

    written = [o for o in outcomes if isinstance(o, uuid.UUID)]
    refused = [o for o in outcomes if isinstance(o, BaseException)]

    assert len(written) == 1, f"expected exactly one submission, got {len(written)}"
    assert len(refused) == 1, f"expected exactly one refusal, got {outcomes}"

    # **The loser is refused, not broken.** An `IntegrityError` here would reach the
    # route unhandled and answer 500 — "the system failed" — for a request the system
    # correctly declined.
    loser = refused[0]
    assert isinstance(loser, SubmissionRefused), (
        f"the losing request raised {type(loser).__name__}, which the API cannot "
        f"translate into a refusal: {loser!r}"
    )
    assert "already been submitted" in str(loser)

    # ***The refusal came from the constraint, not from the guard.*** Both paths give the
    # same message on purpose, so the message cannot tell them apart — the cause can.
    # Without this the test passes against a sequence and proves nothing about a race.
    assert isinstance(loser.__cause__, IntegrityError), (
        "the loser was refused by `ensure_submittable`, which means the two requests "
        f"never actually raced; cause was {type(loser.__cause__).__name__}"
    )

    # **Nothing bypassed the integrity check.** Both racers read the stored bytes and
    # hashed them before either tried to insert; the loser lost at the constraint,
    # not by skipping verification.
    assert store.reads == 2, f"expected both racers to verify the bytes, saw {store.reads}"

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
        assert len(rows) == 1, f"{len(rows)} submission rows for one version"
        assert rows[0].id == written[0]
        assert rows[0].checksum_sha256 == hashlib.sha256(_PDF).hexdigest()

        reloaded = await check.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert VersionStatus(reloaded.status) == VersionStatus.SUBMITTED


async def test_the_losing_request_is_answered_409_and_not_500(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    store: _Storage,
) -> None:
    """The same race at the boundary a person actually reaches.

    Two `POST .../submit` requests issued together. **500 is the wrong answer**: it tells
    the person the system broke, when it refused — and it is what an unhandled
    `IntegrityError` produces.
    """
    user, version = await _exported(db_session, store, sub="race-api")
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))

    async def _post() -> httpx.Response:
        return await client.post(f"/api/versions/{version.id}/submit")

    first, second = await asyncio.gather(_post(), _post())
    codes = sorted([first.status_code, second.status_code])

    assert 500 not in codes, (
        f"a raced submission answered 500: {[r.text[:200] for r in (first, second)]}"
    )
    assert codes == [200, 409], f"expected one success and one refusal, got {codes}"

    refusal = first if first.status_code == 409 else second
    assert "already been submitted" in refusal.json()["detail"]

    async with session_factory() as check:
        count = await check.scalar(
            sa.select(sa.func.count())
            .select_from(SubmittedResume)
            .where(SubmittedResume.resume_version_id == version.id)
        )
    assert count == 1


async def test_a_raced_loser_still_verified_before_it_was_refused(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    store: _Storage,
) -> None:
    """The refusal must not become a shortcut past the checksum.

    If the constraint were caught somewhere that let a submission through without
    reading the bytes, this is what would notice: a tampered object makes **both**
    racers fail, and neither may be recorded.
    """
    _user, version = await _exported(db_session, store, sub="race-tamper")
    (key,) = store.objects
    store.objects[key] = b"%PDF-1.7\nsomething-else\n%%EOF\n"

    outcomes = await asyncio.gather(
        _submit_in_own_session(session_factory, version.id),
        _submit_in_own_session(session_factory, version.id),
    )

    assert all(isinstance(o, ExportChecksumMismatch) for o in outcomes), (
        f"a tampered document was submitted under a race: {outcomes}"
    )
    async with session_factory() as check:
        count = await check.scalar(sa.select(sa.func.count()).select_from(SubmittedResume))
        assert count == 0
        reloaded = await check.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert VersionStatus(reloaded.status) == VersionStatus.EXPORTED


async def test_a_different_constraint_failure_is_not_reported_as_a_duplicate(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    store: _Storage,
) -> None:
    """The narrowing, and a drill is why it is tested at all.

    ***Removing `_is_duplicate_submission` changed nothing until this existed.*** Every
    other test here produces a *unique* violation, so catching `IntegrityError` blindly
    passed them all — and would have turned every future constraint failure on this
    insert into "this version has already been submitted", which is a wrong answer
    delivered in a confident sentence.

    The case used is a real inconsistency rather than an invented one: an export whose
    stored object is **empty**, with a recorded checksum that is the hash of nothing. The
    verification passes — those bytes really are what the record describes — and
    `ck_submitted_resumes_byte_size` then refuses a zero-length submission. That is a
    check violation, not a duplicate, and it must surface as itself.
    """
    seeded = await seed_tailorable(db_session, sub="race-other", email="race-other@example.com")
    version = await create_pending_version(db_session, seeded.application)
    key = f"exports/{version.profile_id}/{version.id}/{uuid.uuid4()}.pdf"
    store.objects[key] = b""
    db_session.add(
        ExportedDocument(
            resume_version_id=version.id,
            document_storage_key=key,
            # The hash of the empty document, so verification agrees and the insert is
            # reached. `byte_size` cannot be 0 here — this table forbids it too.
            checksum_sha256=hashlib.sha256(b"").hexdigest(),
            byte_size=1,
        )
    )
    version.status = VersionStatus.EXPORTED
    await db_session.commit()

    store._barrier = asyncio.Barrier(1)  # one caller, no race — the constraint is the subject

    async with session_factory() as session:
        with pytest.raises(IntegrityError) as raised:
            await submit_version(session, version_id=version.id)
        await session.rollback()

    assert not isinstance(raised.value, SubmissionRefused)
    assert "byte_size" in str(raised.value)

    async with session_factory() as check:
        assert (await check.scalar(sa.select(sa.func.count()).select_from(SubmittedResume))) == 0


async def test_the_losing_request_leaves_no_failed_transaction_behind(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    store: _Storage,
) -> None:
    """The route's transaction handling, pinned through the route rather than mocked.

    **A refused flush aborts the PostgreSQL transaction**, and the connection carrying it
    goes back to the pool. If it were returned without a rollback, the next request to
    draw it would fail with `InFailedSqlTransaction` — a 500 on a request that has
    nothing to do with the race, which is the kind of fault that gets blamed on the wrong
    code for a week.

    Nothing here asserts *how* the rollback happens. The route raises `HTTPException`
    before it reaches `session.commit()`, and `get_db` yields inside
    `async with ... as session`, so closing the session releases the connection and rolls
    back. That is existing behaviour and was not changed; this proves it holds by using
    the pool afterwards, which is the only thing that would actually notice.
    """
    user, version = await _exported(db_session, store, sub="race-rollback")
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))

    async def _post() -> httpx.Response:
        return await client.post(f"/api/versions/{version.id}/submit")

    first, second = await asyncio.gather(_post(), _post())
    assert sorted([first.status_code, second.status_code]) == [200, 409]

    # The barrier has served its purpose; the requests below are sequential.
    store._barrier = asyncio.Barrier(1)

    # A third submit: still a clean refusal, not a 500 from a poisoned connection.
    third = await client.post(f"/api/versions/{version.id}/submit")
    assert third.status_code == 409, third.text
    assert "already been submitted" in third.json()["detail"]

    # And an ordinary read on the same pool.
    read = await client.get(f"/api/versions/{version.id}")
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "submitted"

    # The loser committed nothing: one row, and it is the winner's.
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
    assert rows[0].checksum_sha256 == hashlib.sha256(_PDF).hexdigest()


class _Diag:
    """Just the two fields the predicate reads off psycopg's diagnostics."""

    def __init__(self, table_name: str | None, constraint_name: str | None) -> None:
        self.table_name = table_name
        self.constraint_name = constraint_name


def _integrity_error(sqlstate: str, table_name: str | None, constraint_name: str | None):
    """An `IntegrityError` shaped like the driver's, for cases PostgreSQL cannot be asked
    to produce here.

    **A unit test of a pure predicate, not a mock of the route's error handling.** The
    route is exercised for real above; this covers the one input the database cannot be
    made to deliver from this schema — a violation on *another* table whose constraint is
    merely *named* after this one.
    """

    class _Orig(Exception):
        pass

    original = _Orig("simulated")
    original.sqlstate = sqlstate  # type: ignore[attr-defined]
    original.diag = _Diag(table_name, constraint_name)  # type: ignore[attr-defined]
    return IntegrityError("INSERT ...", {}, original)


async def test_the_duplicate_predicate_matches_this_table_and_nothing_that_merely_names_it() -> (
    None
):
    """The tightening, pinned — because a drill showed nothing else defends it.

    Reverting to the earlier `table_name in constraint_name` substring test broke **no**
    test, since `submitted_resumes` carries exactly one unique constraint today and every
    real violation names it. The difference only shows on an input the schema cannot
    currently produce, which is precisely what the predicate is being hardened against:
    a unique violation on a *different* table whose constraint happens to be named after
    this one would have been reported to the person as *"this version has already been
    submitted"*.
    """
    table = SubmittedResume.__tablename__

    # The real case: a unique violation on this table.
    assert _is_duplicate_submission(
        _integrity_error("23505", table, f"{table}_resume_version_id_key")
    )

    # A constraint merely *named* after this table, on another one. The substring form
    # said yes here; the exact form says no.
    assert not _is_duplicate_submission(
        _integrity_error("23505", "applications", f"uq_applications_{table}_ref")
    )

    # Right table, wrong failure: a check violation is not a duplicate.
    assert not _is_duplicate_submission(
        _integrity_error("23514", table, "ck_submitted_resumes_byte_size")
    )

    # A unique violation somewhere else entirely, and a diagnostic that says nothing.
    assert not _is_duplicate_submission(_integrity_error("23505", "resume_versions", "uq_x"))
    assert not _is_duplicate_submission(_integrity_error("23505", None, f"{table}_key"))


async def _submit_and_probe_the_session(
    factory: async_sessionmaker[AsyncSession], version_id: uuid.UUID
) -> tuple[object, str]:
    """Submit, and on refusal report whether the session is still usable — before rolling back."""
    async with factory() as session:
        try:
            record = await submit_version(session, version_id=version_id)
            await session.commit()
            return record.id, "committed"
        except SubmissionRefused as refused:
            try:
                await session.scalar(sa.select(sa.func.count()).select_from(ResumeVersion))
                state = "usable"
            except Exception as broken:
                state = type(broken).__name__
            await session.rollback()
            return refused, state


async def test_a_refusal_leaves_the_session_usable_whichever_branch_raised_it(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    store: _Storage,
) -> None:
    """One exception type must mean one thing.

    **Every other refusal in this codebase costs nothing.** `ensure_exportable` raises
    before any side effect and T036 drilled the ordering to keep it that way; T039's
    `_unwritten()` asserts a refused decision does not even leave the object dirty. The
    contract these use cases advertise — *"the use case flushes; the caller commits, so a
    route can span several use cases in one transaction"* — is what makes that matter: a
    caller is invited to handle the refusal and carry on.

    Before the savepoint, the constraint path broke that: the flush had already failed,
    PostgreSQL had aborted the transaction, and the next statement raised
    `PendingRollbackError` — a fault that gets blamed on whatever code happens to run
    next. This test was `xfail(strict=True)` while that was true.

    ***It is also the test that distinguishes a real fix from a plausible one.*** A
    savepoint wrapped around `flush()` alone leaves this failing, because the pending
    `add` and status change would still belong to the outer transaction. Only moving them
    inside the block fixes it.
    """
    _user, version = await _exported(db_session, store, sub="race-session-state")

    outcomes = await asyncio.gather(
        _submit_and_probe_the_session(session_factory, version.id),
        _submit_and_probe_the_session(session_factory, version.id),
    )
    refused = [(o, state) for o, state in outcomes if isinstance(o, SubmissionRefused)]
    assert len(refused) == 1, outcomes
    loser, state = refused[0]

    assert isinstance(loser.__cause__, IntegrityError), "the two requests did not race"
    assert state == "usable", (
        "a refused submission left the session in a failed transaction: the next "
        f"statement raised {state}. The same refusal from `ensure_submittable` leaves "
        "the session usable, so `SubmissionRefused` means two different things."
    )


async def test_a_refused_submission_preserves_the_callers_earlier_uncommitted_write(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    store: _Storage,
) -> None:
    """**The second reason for the savepoint, and the one a usability test cannot see.**

    Session usability alone is satisfied by simply rolling the session back inside the
    use case — and that fix is worse than the fault. It makes the session usable by
    discarding *the caller's* transaction: any row the caller wrote before calling
    `submit_version` disappears, silently, because a use case decided to tidy up after
    itself. Measured while choosing the design: with `session.rollback()` in place of the
    savepoint, the row written below is **gone** after commit.

    This project's contract is that the caller owns the transaction — *"the use case
    flushes; the caller commits, so a route can span several use cases in one
    transaction"*. A savepoint honours that: the refusal unwinds its own work and nothing
    else.

    The caller's write is a `ResumeVersionItem` — a row the caller may legitimately have
    created in the same transaction, and deliberately **not** an `ExportedDocument`: the
    first attempt used one and `latest_export` promptly selected it as the document to
    submit, which is its own small lesson about writing a fixture into a table the code
    under test reads.
    """
    _user, version = await _exported(db_session, store, sub="race-caller-tx")
    marker = "caller-work-before-the-refusal"

    async def caller() -> SubmissionRefused:
        async with session_factory() as session:
            # 1. The caller writes something of its own, uncommitted, before calling in.
            session.add(
                ResumeVersionItem(
                    resume_version_id=version.id,
                    source_kind=SourceKind.SKILL,
                    position=99,
                    original_text=marker,
                    final_text=marker,
                    decision=ProposalDecision.ACCEPTED,
                    included=True,
                )
            )
            await session.flush()

            # 2. The use case refuses. It parks in the storage read having already
            #    passed the guard on `EXPORTED`; the competing row lands while it is
            #    parked, so the refusal comes from the constraint and not from the guard.
            with pytest.raises(SubmissionRefused) as refused:
                await submit_version(session, version_id=version.id)

            # 3. The caller carries on in the same transaction and commits its own work.
            await session.commit()
            return refused.value

    task = asyncio.create_task(caller())

    # The competing submission, inserted directly and committed while the caller is
    # parked. By hand rather than through `submit_version`, because the subject here is
    # the caller's transaction and this makes the ordering deterministic — the same
    # technique `test_tailoring_concurrency.py` uses to skip an application-level check.
    async with session_factory() as winner:
        winner.add(
            SubmittedResume(
                resume_version_id=version.id,
                application_id=version.application_id,
                document_storage_key="the-winner",
                checksum_sha256=hashlib.sha256(_PDF).hexdigest(),
                byte_size=len(_PDF),
            )
        )
        await winner.commit()
    # Releasing the caller: the second party on the barrier it is waiting at.
    await store._barrier.wait()

    loser = await task
    assert isinstance(loser.__cause__, IntegrityError), (
        "the refusal came from the guard, so this proves nothing about the savepoint"
    )

    async with session_factory() as check:
        survived = await check.scalar(
            sa.select(sa.func.count())
            .select_from(ResumeVersionItem)
            .where(ResumeVersionItem.original_text == marker)
        )
        assert survived == 1, (
            "the caller's earlier write was destroyed by a refusal inside the use case"
        )

        # And the refusal still left nothing of its own behind.
        submissions = list(
            (
                await check.execute(
                    sa.select(SubmittedResume).where(
                        SubmittedResume.resume_version_id == version.id
                    )
                )
            ).scalars()
        )
        assert len(submissions) == 1, "the losing submission was written after all"
        assert submissions[0].document_storage_key == "the-winner"

        reloaded = await check.get(ResumeVersion, version.id)
        assert reloaded is not None
        assert VersionStatus(reloaded.status) == VersionStatus.EXPORTED, (
            "the loser's status change survived the refusal"
        )
