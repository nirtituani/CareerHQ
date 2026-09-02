"""T041 — FR-025: revising after submission creates a **new version**.

**This is a lineage requirement, not a second immutability check.** T039 already refuses
every content write to an `EXPORTED` or `SUBMITTED` version, and a system that only did
that would satisfy FR-022 while failing FR-025 completely — because the way to fail
FR-025 is to make revision *impossible*, not to make it destructive.
`docs/03` §10.1 says both halves in one breath: *"`Submitted` is terminal and **locked**.
The Version cannot be edited again. Duplicating it creates a new `Draft` with its own
lineage."*

So the shape being proved is:

    READY → EXPORTED → SUBMITTED  …then…  a **new** version, editable, its own identity

with the sent document, the sent version and the `SubmittedResume` all exactly where they
were. `docs/03` §12.1: *"A Submitted Resume Version can never transition to any other
state"*, and *"Every Resume Version records exactly one source Resume Profile, and that
lineage is immutable."*

**Nothing is asserted on Python object identity.** Two `ResumeVersion` objects having
different `id` attributes proves that two objects exist, which is what an implementation
that then overwrote the submitted row would also produce. Every claim below is re-read
through a **fresh session**, because a row still held in the identity map of the session
that wrote it answers with what that session believes rather than with what the database
holds.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from careerhq.application import export_resume
from careerhq.application.export_resume import export_version
from careerhq.application.submissions import submission_for
from careerhq.application.submit_resume import submit_version
from careerhq.application.tailor_resume import create_pending_version, decide_item
from careerhq.domain.models import (
    Application,
    ExportedDocument,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    SourceKind,
    SubmittedResume,
    VersionStatus,
)
from careerhq.domain.schemas.document import ResumeDocument
from careerhq.domain.schemas.theme import ResumeTheme
from careerhq.infrastructure import storage
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

_SENT = "Owned the settlement service end to end, from schema to on-call."
_REVISED = "Owned settlement for 4M daily transactions, written after the first send."


@pytest.fixture
def readable_documents(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Stored bytes that can be read back and searched — see T040 for why."""
    stored: dict[str, bytes] = {}

    def _render(document: ResumeDocument, theme: ResumeTheme | None = None) -> bytes:
        return b"DOC\n" + "\n".join(document.lines_in_order()).encode()

    async def _put(key: str, data: bytes, *, content_type: str) -> None:
        stored[key] = data

    async def _get(key: str) -> bytes:
        return stored[key]

    monkeypatch.setattr(export_resume, "render_resume_pdf", _render)
    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "get_object", _get)
    return stored


def _item(version_id: uuid.UUID, text: str) -> ResumeVersionItem:
    return ResumeVersionItem(
        resume_version_id=version_id,
        source_kind=SourceKind.EXPERIENCE_BULLET,
        position=0,
        original_text=text,
        proposed_text=text,
        final_text=text,
        decision=ProposalDecision.ACCEPTED,
        included=True,
    )


async def _reload(session: AsyncSession, version_id: uuid.UUID) -> ResumeVersion:
    version = await session.scalar(
        sa.select(ResumeVersion)
        .where(ResumeVersion.id == version_id)
        .options(selectinload(ResumeVersion.items))
    )
    assert version is not None
    return version


def _lineage(version: ResumeVersion) -> dict[str, Any]:
    """Everything about a version that a revision must not disturb.

    Deliberately not just `status`: an implementation that moved the submitted row's
    `source_resume_profile_id` to the current master, or renamed it, or repointed its run,
    would leave the status alone and still have rewritten history.
    """
    return {
        "id": version.id,
        "status": VersionStatus(version.status),
        "name": version.name,
        "profile_id": version.profile_id,
        "application_id": version.application_id,
        "source_resume_profile_id": version.source_resume_profile_id,
        "source_profile_updated_at": version.source_profile_updated_at,
        "tailoring_run_id": version.tailoring_run_id,
        "confidence_score": version.confidence_score,
        "failure_reason": version.failure_reason,
        "created_at": version.created_at,
        "items": [
            (i.id, i.position, i.source_kind, i.original_text, i.final_text, i.decision, i.included)
            for i in sorted(version.items, key=lambda i: i.position)
        ],
    }


def _record(record: SubmittedResume) -> dict[str, Any]:
    return {
        "id": record.id,
        "resume_version_id": record.resume_version_id,
        "application_id": record.application_id,
        "document_storage_key": record.document_storage_key,
        "checksum_sha256": record.checksum_sha256,
        "byte_size": record.byte_size,
        "submitted_at": record.submitted_at,
    }


async def _sent(
    session: AsyncSession, *, sub: str
) -> tuple[Application, ResumeVersion, SubmittedResume]:
    """A version taken all the way through the real path: READY → EXPORTED → SUBMITTED."""
    seeded = await seed_tailorable(session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(session, seeded.application)
    session.add(_item(version.id, _SENT))
    version.status = VersionStatus.READY
    await session.flush()
    await session.refresh(version, ["items"])

    await export_version(session, version_id=version.id)
    record = await submit_version(session, version_id=version.id)
    await session.commit()
    return seeded.application, version, record


async def _versions_of(session: AsyncSession, application_id: uuid.UUID) -> list[ResumeVersion]:
    rows = await session.execute(
        sa.select(ResumeVersion)
        .where(ResumeVersion.application_id == application_id)
        .options(selectinload(ResumeVersion.items))
        .order_by(ResumeVersion.created_at)
    )
    return list(rows.scalars())


# ======================================================================================
# Revision happens, and it happens by creating something new
# ======================================================================================


async def test_a_submitted_version_can_still_be_revised(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """**The half of FR-025 that a stricter lock would break.**

    T039 refuses every content write to a submitted version, and the tempting way to read
    that is "a submitted job is finished". FR-025 says the opposite: a person who has sent
    a résumé and then wants a better one must be able to produce it. Refusing revision
    would pass every immutability test in this slice and leave the job unusable.
    """
    application, sent, _record = await _sent(db_session, sub="rev-possible")

    async with session_factory() as session:
        loaded = await session.get(Application, application.id)
        assert loaded is not None
        revision = await create_pending_version(session, loaded)
        await session.commit()
        revision_id = revision.id

    assert revision_id != sent.id

    async with session_factory() as check:
        versions = await _versions_of(check, application.id)
        assert [v.id for v in versions] == [sent.id, revision_id], (
            "the revision did not land beside the version that was sent"
        )
        assert VersionStatus(versions[0].status) == VersionStatus.SUBMITTED
        assert VersionStatus(versions[1].status) == VersionStatus.TAILORING


async def test_the_submitted_version_is_untouched_by_the_revision(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """Every field, not just the status.

    An implementation that created a new row *and* repointed the old one's lineage at the
    current master, or renamed it, or cleared its run, would leave `status` alone and have
    rewritten history anyway. The whole lineage is snapshotted before and compared after,
    re-read through a session that never saw the write.
    """
    application, sent, _record = await _sent(db_session, sub="rev-untouched")

    async with session_factory() as before_session:
        before = _lineage(await _reload(before_session, sent.id))

    async with session_factory() as session:
        loaded = await session.get(Application, application.id)
        assert loaded is not None
        await create_pending_version(session, loaded)
        await session.commit()

    async with session_factory() as check:
        assert _lineage(await _reload(check, sent.id)) == before, (
            "the revision changed the version that had already been sent"
        )


async def test_the_submission_record_still_points_at_the_version_that_was_sent(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """The record, the pointer, and the bytes — all three, because they fail separately.

    Repointing `resume_version_id` at the revision is the most plausible way to get this
    wrong: it looks like keeping the application's submission "current", and it silently
    replaces the answer to *what did I actually send* with a document that was never sent.
    """
    application, sent, record = await _sent(db_session, sub="rev-record")
    before = _record(record)
    sent_bytes = readable_documents[record.document_storage_key]

    async with session_factory() as session:
        loaded = await session.get(Application, application.id)
        assert loaded is not None
        revision = await create_pending_version(session, loaded)
        await session.commit()
        revision_id = revision.id

    async with session_factory() as check:
        after = await check.get(SubmittedResume, before["id"])
        assert after is not None
        assert _record(after) == before, "the revision moved the submitted record"
        assert after.resume_version_id == sent.id
        assert after.resume_version_id != revision_id

        found = await submission_for(check, application_id=application.id)
        assert found is not None and found.id == before["id"]

    assert readable_documents[before["document_storage_key"]] == sent_bytes
    assert hashlib.sha256(sent_bytes).hexdigest() == before["checksum_sha256"]


async def test_the_new_version_has_its_own_identity_and_its_own_lineage(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """*"Duplicating it creates a new `Draft` with its own lineage"* — `docs/03` §10.1.

    **Its own**, and both words carry weight. The revision must belong to the same job —
    otherwise it is a different application's résumé and the person has lost the thread —
    while carrying a lineage snapshotted *now*, its own run, and no items inherited from
    the document that was sent. `docs/03` §12.1: a version's source resume profile is
    recorded exactly once and that lineage is immutable, so a revision cannot share the
    sent version's.
    """
    application, sent, _record = await _sent(db_session, sub="rev-lineage")

    async with session_factory() as session:
        loaded = await session.get(Application, application.id)
        assert loaded is not None
        revision = await create_pending_version(session, loaded)
        await session.commit()
        revision_id = revision.id

    async with session_factory() as check:
        new = await _reload(check, revision_id)
        old = await _reload(check, sent.id)

        assert new.id != old.id
        assert new.application_id == old.application_id, "the revision left the job behind"
        assert new.profile_id == old.profile_id
        assert new.tailoring_run_id is not None
        assert new.tailoring_run_id != old.tailoring_run_id, "the revision reused the sent run"
        assert new.items == [], "the revision inherited the sent document's items"
        assert new.failure_reason is None and new.confidence_score is None
        assert VersionStatus(new.status) == VersionStatus.TAILORING


@pytest.mark.parametrize(
    "status",
    [
        VersionStatus.AWAITING_APPROVAL,
        VersionStatus.READY,
        VersionStatus.EXPORTED,
        VersionStatus.SUBMITTED,
    ],
)
async def test_only_a_draft_is_ever_reused_as_a_revision_target(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    status: VersionStatus,
) -> None:
    """The single line of code FR-025 rests on, pinned behaviourally.

    `create_pending_version` reuses an existing version only when it is a `DRAFT` — a
    retry into the same unfinished attempt. Widening that filter by one status is a
    one-word edit that reads as a tidy-up and would let a revision **overwrite** an
    approved, exported or submitted document. Parametrised over every status past
    approval so the boundary is asserted rather than the one case that is easiest to
    think of.
    """
    seeded = await seed_tailorable(db_session, sub=f"rev-{status.value[:8]}")
    first = await create_pending_version(db_session, seeded.application)
    first.status = status
    await db_session.commit()

    async with session_factory() as session:
        application = await session.get(Application, seeded.application.id)
        assert application is not None
        second = await create_pending_version(session, application)
        await session.commit()
        second_id = second.id

    assert second_id != first.id, f"a {status.value} version was reused instead of revised"

    async with session_factory() as check:
        versions = await _versions_of(check, seeded.application.id)
        assert len(versions) == 2, f"{len(versions)} version(s) — the old one was consumed"
        assert VersionStatus(versions[0].status) == status, "the older version was moved"


async def test_an_unfinished_draft_is_still_reused_rather_than_multiplied(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The deliberate exception, stated so it does not get "fixed".

    `data-model.md` says it twice and it is the entire reason there is no `failed` version
    status: *"the owner can retry into the same `draft` rather than accumulating abandoned
    versions"*. A retry into an unfinished attempt is not a revision of a sent document,
    and a stricter rule here would fill the Versions list with identical dead drafts —
    which is exactly the defect this behaviour was introduced to fix.
    """
    seeded = await seed_tailorable(db_session, sub="rev-draft")
    first = await create_pending_version(db_session, seeded.application)
    first.status = VersionStatus.DRAFT
    await db_session.commit()

    async with session_factory() as session:
        application = await session.get(Application, seeded.application.id)
        assert application is not None
        again = await create_pending_version(session, application)
        await session.commit()
        assert again.id == first.id

    async with session_factory() as check:
        assert len(await _versions_of(check, seeded.application.id)) == 1


# ======================================================================================
# The revision is a real, independent document
# ======================================================================================


async def test_editing_the_revision_cannot_reach_the_document_that_was_sent(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """The point of the whole arrangement: a second document, edited freely, in front of
    a first that cannot move.

    The revision is given an item and then edited through `decide_item` — the real path,
    which T039 refuses on a locked version — and the sent version's items, the stored
    bytes and the checksum are all re-checked afterwards.
    """
    application, sent, record = await _sent(db_session, sub="rev-edit")
    sent_items = _lineage(await _reload(db_session, sent.id))["items"]
    sent_bytes = readable_documents[record.document_storage_key]

    async with session_factory() as session:
        loaded = await session.get(Application, application.id)
        assert loaded is not None
        revision = await create_pending_version(session, loaded)
        session.add(_item(revision.id, _SENT))
        revision.status = VersionStatus.AWAITING_APPROVAL
        await session.flush()
        await session.refresh(revision, ["items"])

        await decide_item(
            session,
            item=revision.items[0],
            decision=ProposalDecision.EDITED,
            text=_REVISED,
        )
        await session.commit()
        revision_id = revision.id

    async with session_factory() as check:
        assert _lineage(await _reload(check, sent.id))["items"] == sent_items, (
            "editing the revision changed the document that was sent"
        )
        revised = await _reload(check, revision_id)
        assert revised.items[0].final_text == _REVISED, "the revision was not editable"

        after = await check.get(SubmittedResume, record.id)
        assert after is not None and after.checksum_sha256 == record.checksum_sha256

    assert readable_documents[record.document_storage_key] == sent_bytes
    assert _REVISED.encode() not in sent_bytes


async def test_the_revision_can_itself_be_exported_and_submitted_without_displacing_the_first(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """The revision is a first-class version, and the first send survives it.

    Two submissions for one application is legitimate — `submitted_resumes` is unique on
    the **version**, not on the application, precisely because a second send is a new
    version. Both rows must remain, each naming its own version, its own object and its
    own checksum; the application's *current* answer moves to the newer one and its
    history does not disappear.
    """
    application, sent, first_record = await _sent(db_session, sub="rev-second-send")
    sent_key = first_record.document_storage_key
    sent_bytes = readable_documents[sent_key]

    async with session_factory() as session:
        loaded = await session.get(Application, application.id)
        assert loaded is not None
        revision = await create_pending_version(session, loaded)
        session.add(_item(revision.id, _REVISED))
        revision.status = VersionStatus.READY
        await session.flush()
        await session.refresh(revision, ["items"])
        await export_version(session, version_id=revision.id)
        second_record = await submit_version(session, version_id=revision.id)
        await session.commit()
        revision_id, second_id = revision.id, second_record.id
        second_key = second_record.document_storage_key

    assert second_key != sent_key, "the revision's export overwrote the sent document"
    assert readable_documents[sent_key] == sent_bytes
    assert _REVISED.encode() in readable_documents[second_key]
    assert _REVISED.encode() not in sent_bytes

    async with session_factory() as check:
        rows = list(
            (
                await check.execute(
                    sa.select(SubmittedResume).where(
                        SubmittedResume.application_id == application.id
                    )
                )
            ).scalars()
        )
        assert {r.id for r in rows} == {first_record.id, second_id}, "one of the two sends was lost"
        assert {r.resume_version_id for r in rows} == {sent.id, revision_id}
        assert len({r.document_storage_key for r in rows}) == 2

        current = await submission_for(check, application_id=application.id)
        assert current is not None and current.id == second_id

        exports = list(
            (
                await check.execute(
                    sa.select(ExportedDocument).where(
                        ExportedDocument.resume_version_id.in_([sent.id, revision_id])
                    )
                )
            ).scalars()
        )
        assert len(exports) == 2, "the revision reused the sent version's export record"
        assert len({e.resume_version_id for e in exports}) == 2


async def test_a_second_revision_creates_a_third_version(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """Revision is repeatable, and it does not start consuming its own output.

    The first revision is moved to `READY` before the second is asked for, because an
    unfinished `DRAFT` is deliberately reused — the test above states that rule. What must
    not happen is a second revision landing on a version that has been approved, which is
    the same mistake as landing on the one that was sent, one status earlier.
    """
    application, sent, _record = await _sent(db_session, sub="rev-third")

    async with session_factory() as session:
        loaded = await session.get(Application, application.id)
        assert loaded is not None
        first = await create_pending_version(session, loaded)
        first.status = VersionStatus.READY
        await session.commit()
        first_id = first.id

    async with session_factory() as session:
        loaded = await session.get(Application, application.id)
        assert loaded is not None
        second = await create_pending_version(session, loaded)
        await session.commit()
        second_id = second.id

    assert len({sent.id, first_id, second_id}) == 3

    async with session_factory() as check:
        versions = await _versions_of(check, application.id)
        assert [v.id for v in versions] == [sent.id, first_id, second_id]
        assert VersionStatus(versions[0].status) == VersionStatus.SUBMITTED
        assert VersionStatus(versions[1].status) == VersionStatus.READY
