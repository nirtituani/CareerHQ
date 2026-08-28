"""T039 — FR-022: a locked version refuses modification, explicitly and without trace.

**Two states are locked, and which two is the whole of the task.** `docs/03` §10.1:
*"`Ready` means user-approved. It remains editable; approval is not a one-way door **until
export**"*, and *"`Submitted` is terminal and **locked**. The Version cannot be edited
again."* So the door closes at `EXPORTED`, and **`READY` is deliberately still editable**
— FR-029 requires it, and locking it would be the most plausible way to get this task
wrong while every immutability test still passed.

**"Refused explicitly" is a claim about three things, and each fails on its own.**
It must *raise* rather than return; it must raise something a caller can tell apart from a
render failure or a wrong-state complaint; and it must leave nothing behind. A guard that
mutates and then raises satisfies the first two and is the dangerous one, because the
caller's own `commit` — or any later flush in the same session — persists the change the
refusal claimed to prevent.

**So every assertion here is made twice: in memory and in a fresh session.** The
in-memory half is the attribute's *history*, not its value: an implementation that wrote
the new value and then raised leaves the object dirty, and reading `item.final_text` back
off that same object would show the original only if nothing had been written at all —
which is precisely what is in question. The persisted half commits first and re-reads
through a second session, because a row still held in the identity map of the session
that wrote it answers with what that session believes, not with what the database holds.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from careerhq.application.export import ExportRefused
from careerhq.application.export_resume import export_version
from careerhq.application.immutability import (
    LOCKED_STATUSES,
    VersionLocked,
    ensure_version_mutable,
)
from careerhq.application.submit_resume import SubmissionRefused, submit_version
from careerhq.application.tailor_resume import (
    TailoringRefused,
    approve_version,
    create_pending_version,
    decide_item,
)
from careerhq.domain.models import (
    ExportedDocument,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    SourceKind,
    User,
    VersionStatus,
)
from careerhq.infrastructure import storage
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

_ORIGINAL = "Owned the settlement service end to end, from schema to on-call."
_PROPOSED = "Owned settlement end to end for 4M daily transactions."
_INTRUSION = "Edited after the document was already sent."

_LOCKED = [VersionStatus.EXPORTED, VersionStatus.SUBMITTED]


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    stored: dict[str, bytes] = {}

    async def _put(key: str, data: bytes, *, content_type: str) -> None:
        stored[key] = data

    async def _get(key: str) -> bytes:
        return stored[key]

    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "get_object", _get)
    return stored


async def _seed(
    session: AsyncSession, *, sub: str, status: VersionStatus
) -> tuple[User, ResumeVersion, uuid.UUID]:
    seeded = await seed_tailorable(session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(session, seeded.application)
    item = ResumeVersionItem(
        resume_version_id=version.id,
        source_kind=SourceKind.EXPERIENCE_BULLET,
        position=0,
        original_text=_ORIGINAL,
        proposed_text=_PROPOSED,
        final_text=_ORIGINAL,
        decision=ProposalDecision.PENDING,
        included=True,
    )
    session.add(item)
    version.status = status
    await session.commit()
    return seeded.user, version, item.id


async def _reload(session: AsyncSession, version_id: uuid.UUID) -> ResumeVersion:
    version = await session.scalar(
        select(ResumeVersion)
        .where(ResumeVersion.id == version_id)
        .options(selectinload(ResumeVersion.items))
    )
    assert version is not None
    return version


def _unwritten(item: ResumeVersionItem) -> None:
    """The object was not written to at all — not written and then rolled back in the head.

    `history.has_changes()` is the question that distinguishes "the guard refused" from
    "the guard mutated and then refused". The second leaves a pending UPDATE that the
    caller's own commit will happily flush, which is FR-022 failing in the most quiet way
    available to it.
    """
    state = sa_inspect(item)
    for attribute in ("final_text", "decision", "included", "position"):
        assert not state.attrs[attribute].history.has_changes(), (
            f"{attribute} was written before the refusal; a later flush would persist it"
        )


# --------------------------------------------------------------------------------------
# What is locked, and what deliberately is not
# --------------------------------------------------------------------------------------


async def test_exactly_exported_and_submitted_are_locked() -> None:
    """The scope of the task, stated as an assertion rather than left in a docstring.

    **`READY` is the one that matters.** It is approved, it is what a person would call
    "final", and locking it would look like a stricter reading of the same requirement —
    while contradicting FR-029 and `docs/03` §10.1 outright. `DRAFT` through
    `AWAITING_APPROVAL` are obviously live. Enumerated over the whole enum so a status
    added later has to be classified here rather than defaulting to editable.
    """
    assert LOCKED_STATUSES == {VersionStatus.EXPORTED, VersionStatus.SUBMITTED}

    editable = [s for s in VersionStatus if s not in LOCKED_STATUSES]
    assert editable == [
        VersionStatus.DRAFT,
        VersionStatus.TAILORING,
        VersionStatus.REVIEWING,
        VersionStatus.AWAITING_APPROVAL,
        VersionStatus.READY,
    ], "a status was added or reclassified without deciding whether it is locked"

    for status in editable:
        ensure_version_mutable(status)
    for status in LOCKED_STATUSES:
        with pytest.raises(VersionLocked):
            ensure_version_mutable(status)


async def test_the_guard_accepts_the_plain_string_a_loaded_row_actually_carries() -> None:
    """`status` is a `String` column, so a row from a fresh session is a `str`.

    The same defect `ensure_exportable` shipped: membership and `==` survive it because
    `VersionStatus` is a `StrEnum`, but `.value` — which the refusal message uses — does
    not, and the tests that passed enum members only could not see it.
    """
    ensure_version_mutable("ready")
    with pytest.raises(VersionLocked):
        ensure_version_mutable("submitted")


async def test_a_lock_is_not_a_generic_failure_and_not_another_refusal() -> None:
    """Distinguishable, which is what "refused explicitly" means in practice.

    Not an `OSError`, so a handler written for storage and rendering cannot swallow it;
    not a `ValueError`, which `decide_item` already raises for empty edit text and which
    the API answers with 422 — a *malformed request*, not a refused one. And its own
    type, because "you may not edit this" is a different answer from "this cannot be
    exported" or "this cannot be submitted", and a route that collapsed them would tell
    a person to do something that is not possible.
    """
    assert issubclass(VersionLocked, Exception)
    for wrong in (OSError, ValueError, ExportRefused, SubmissionRefused, TailoringRefused):
        assert not issubclass(VersionLocked, wrong), (
            f"VersionLocked inherits from {wrong.__name__} and would be caught by handlers "
            "meant for a different failure"
        )


# --------------------------------------------------------------------------------------
# The mutation paths
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", _LOCKED)
async def test_deciding_an_item_on_a_locked_version_is_refused_and_writes_nothing(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    status: VersionStatus,
) -> None:
    """The path a person actually has: accept, reject or rewrite one proposal.

    Committed **after** the refusal on purpose. A route would not commit after an
    exception, but any caller that spans several use cases in one transaction would —
    and that is the transaction boundary this project deliberately chose. A guard that
    mutates before raising is a guard that depends on its caller never committing again.
    """
    _user, version, _item = await _seed(
        db_session, sub=f"lock-item-{status.value[:6]}", status=status
    )

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        item = loaded.items[0]

        with pytest.raises(VersionLocked):
            await decide_item(session, item=item, decision=ProposalDecision.EDITED, text=_INTRUSION)

        _unwritten(item)
        await session.commit()

    async with session_factory() as check:
        after = (await _reload(check, version.id)).items[0]
        assert after.final_text == _ORIGINAL, "the refused edit reached the database"
        assert after.decision == ProposalDecision.PENDING
        assert (await _reload(check, version.id)).status == status


@pytest.mark.parametrize("status", _LOCKED)
async def test_approving_a_locked_version_is_refused_and_writes_nothing(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    status: VersionStatus,
) -> None:
    """The second content-mutation path, and the one that would also move the status back.

    `approve_version` accepts every pending item *and* sets the status to `READY`. On an
    exported version that is two violations in one call: it rewrites approved content,
    and it walks the lifecycle backwards out of a state the diagram has no edge out of.
    """
    _user, version, _ = await _seed(db_session, sub=f"lock-appr-{status.value[:6]}", status=status)

    async with session_factory() as session:
        loaded = await _reload(session, version.id)

        with pytest.raises(VersionLocked):
            await approve_version(session, version=loaded)

        _unwritten(loaded.items[0])
        assert not sa_inspect(loaded).attrs["status"].history.has_changes()
        await session.commit()

    async with session_factory() as check:
        after = await _reload(check, version.id)
        assert after.status == status, "the version was walked back out of a locked state"
        assert after.items[0].final_text == _ORIGINAL
        assert after.items[0].decision == ProposalDecision.PENDING


# --------------------------------------------------------------------------------------
# What must keep working
# --------------------------------------------------------------------------------------


async def test_an_approved_but_unexported_version_is_still_editable(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-029, as the counterexample the lock has to leave alone.

    Stated here rather than only in `test_version_status_transitions.py` because it is
    this task's most likely failure: a lock defined as "approved means final" passes
    every test above and silently removes the ability to fix a typo before exporting.
    """
    _user, version, _item = await _seed(db_session, sub="lock-ready", status=VersionStatus.READY)

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        await decide_item(
            session, item=loaded.items[0], decision=ProposalDecision.EDITED, text="Fixed a typo."
        )
        await session.commit()

    async with session_factory() as check:
        assert (await _reload(check, version.id)).items[0].final_text == "Fixed a typo."


async def test_the_lifecycle_still_runs_forward_through_both_locked_states(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
) -> None:
    """`READY → EXPORTED → SUBMITTED`, with the lock in place the whole way.

    **A lock on the row would make the lifecycle impossible**, and a version stuck at
    `EXPORTED` forever would be a worse outcome than the one FR-022 is protecting
    against. The rule is about *content*: a locked version's items may not change, and
    its status may still move forward along the one edge the diagram draws.
    """
    _user, version, _ = await _seed(db_session, sub="lock-forward", status=VersionStatus.READY)

    async with session_factory() as session:
        loaded = await _reload(session, version.id)
        await approve_version(session, version=loaded)  # READY is not locked
        record = await export_version(session, version_id=version.id)
        await session.commit()

    async with session_factory() as check:
        assert (await _reload(check, version.id)).status == VersionStatus.EXPORTED

    async with session_factory() as session:
        submission = await submit_version(session, version_id=version.id)
        await session.commit()
        assert submission.checksum_sha256 == record.checksum_sha256

    async with session_factory() as check:
        assert (await _reload(check, version.id)).status == VersionStatus.SUBMITTED


async def test_a_re_export_of_a_locked_version_is_still_allowed(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
) -> None:
    """`EXPORTED → EXPORTED`: a download that failed, a second copy.

    T036 built `ExportedDocument` with no unique constraint on the version precisely to
    allow this, so a lock that refused it would break a decision taken one task earlier —
    and it produces byte-identical output under FR-031, so it modifies nothing.
    """
    _user, version, _ = await _seed(db_session, sub="lock-reexport", status=VersionStatus.READY)

    async with session_factory() as session:
        await export_version(session, version_id=version.id)
        await session.commit()

    async with session_factory() as session:
        await export_version(session, version_id=version.id)
        await session.commit()

    async with session_factory() as check:
        rows = await check.execute(
            select(ExportedDocument).where(ExportedDocument.resume_version_id == version.id)
        )
        records = list(rows.scalars())
        assert len(records) == 2, f"the lock refused a legitimate re-export ({len(records)} rows)"
        assert len({r.checksum_sha256 for r in records}) == 1, "FR-031: the bytes should repeat"
        assert hashlib.sha256(fake_storage[records[0].document_storage_key]).hexdigest() == (
            records[0].checksum_sha256
        )


# --------------------------------------------------------------------------------------
# The API boundary
# --------------------------------------------------------------------------------------


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


@pytest.mark.parametrize("status", _LOCKED)
async def test_patching_an_item_on_a_locked_version_is_refused_with_409(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    status: VersionStatus,
) -> None:
    """FR-022 at the only boundary a person can actually reach.

    **409, not 422.** The request is well formed and the state refuses it — the status
    `approve` and `export` already use for exactly this. **Not 200 with nothing
    happening**, which is the failure FR-022 names: a silent no-op on an immutability
    guarantee is indistinguishable from success, and the client would render the edit as
    accepted.

    The database is re-read afterwards through a second session, because a route that
    mutated and then refused would still have committed if anything downstream did.
    """
    user, version, item_id = await _seed(
        db_session, sub=f"api-lock-{status.value[:6]}", status=status
    )

    response = await _as(client, user).patch(
        f"/api/versions/{version.id}/items/{item_id}",
        json={"decision": "edited", "text": _INTRUSION},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "no longer be changed" in detail, f"the refusal does not say what happened: {detail}"
    assert _INTRUSION not in detail

    async with session_factory() as check:
        after = (await _reload(check, version.id)).items[0]
        assert after.final_text == _ORIGINAL, "the refused edit reached the database"
        assert after.decision == ProposalDecision.PENDING


@pytest.mark.parametrize("status", _LOCKED)
async def test_approving_a_locked_version_is_refused_with_409(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    status: VersionStatus,
) -> None:
    """The second route that mutates, refused the same way and for the same reason."""
    user, version, _ = await _seed(db_session, sub=f"api-appr-{status.value[:6]}", status=status)

    response = await _as(client, user).post(f"/api/versions/{version.id}/approve")

    assert response.status_code == 409, response.text
    assert "no longer be changed" in response.json()["detail"]

    async with session_factory() as check:
        assert (await _reload(check, version.id)).status == status


async def test_the_lock_is_reported_differently_from_a_version_not_yet_reviewable(
    client: Any, db_session: AsyncSession
) -> None:
    """Two wrong states, two answers, and collapsing them would misinform on both sides.

    A `TAILORING` version is not editable *yet*; an `EXPORTED` one is not editable *any
    more*. Both are 409 and the status code cannot tell them apart, so the message is
    the entire difference — and "this version is not ready for review yet" told about a
    document that has already been rendered describes a state that will never arrive.

    **This is what the drill for the route change targets.** Before T039 the
    `DECIDABLE_STATUSES` check answered for both, and the exported case got the sentence
    written for the unfinished one.
    """
    early_user, early, early_item = await _seed(
        db_session, sub="api-early", status=VersionStatus.TAILORING
    )
    locked_user, locked, locked_item = await _seed(
        db_session, sub="api-locked", status=VersionStatus.EXPORTED
    )

    body = {"decision": "accepted"}
    early_response = await _as(client, early_user).patch(
        f"/api/versions/{early.id}/items/{early_item}", json=body
    )
    locked_response = await _as(client, locked_user).patch(
        f"/api/versions/{locked.id}/items/{locked_item}", json=body
    )

    assert early_response.status_code == locked_response.status_code == 409
    early_detail = early_response.json()["detail"]
    locked_detail = locked_response.json()["detail"]

    assert early_detail == "This version is not ready for review yet."
    assert locked_detail != early_detail, (
        "a locked version is described as one that is not ready yet"
    )
    assert "no longer be changed" in locked_detail


async def test_a_ready_version_is_still_patchable_through_the_route(
    client: Any, db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FR-029 at the boundary, so the lock cannot be tightened without this failing.

    The use-case test above proves `decide_item` still works on a `READY` version; this
    proves the *route* does, which is a separate claim — the refusal was added to the
    route ahead of its existing wrong-state check, and a guard placed there with the
    wrong status set would refuse the one edit FR-029 requires.
    """
    user, version, item_id = await _seed(db_session, sub="api-ready", status=VersionStatus.READY)

    response = await _as(client, user).patch(
        f"/api/versions/{version.id}/items/{item_id}",
        json={"decision": "edited", "text": "Fixed before exporting."},
    )

    assert response.status_code == 200, response.text

    async with session_factory() as check:
        assert (await _reload(check, version.id)).items[0].final_text == "Fixed before exporting."
