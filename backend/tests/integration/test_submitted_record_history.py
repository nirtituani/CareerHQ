"""T040 — FR-023 and FR-024. **Two invariants, and they fail independently.**

**FR-023 is about the artefact.** A submitted résumé is a historical fact: what a person
sent, on the day they sent it. Later profile edits — a corrected job title, a deleted
skill, a rewritten bullet — must not reach it. `data-model.md` justifies snapshotting
rather than referencing *precisely so this holds*, and the failure is silent by
construction: the record still loads, the checksum still looks like a checksum, and the
only symptom is that the document a person is told they sent is not the one they sent.

**FR-024 is about the pointer.** Constitution IV: *"Applications in `Applied` or later
status MUST reference a Submitted Resume."* That is a different claim, over a different
row, and satisfying one says nothing about the other — a perfectly frozen record that no
application can be traced back to fails Constitution IV just as completely as a mutable
one.

**The scope of FR-024 as this system can honestly hold it.** `docs/03` §5.2 states the
rule as a universal, and the universal is **false against real data**: applications are
imported from a job tracker at `Applied`, `Interview Round 2` and `Rejected`, and none of
them has a CareerHQ document because none was ever tailored here. So what is proved below
is the reference itself — mandatory, un-danglable, resolvable, and never answered with an
editable version. What is **not** proved, because it is not true, is that every
`Applied` row has a submission. Recorded in `tasks.md` under T040 rather than papered
over by inventing rows.

**Everything is re-read in a fresh session.** A row still held in the identity map of the
session that wrote it answers with what that session believes, not with what the database
holds — the same class of mistake as slice 004's `is`-versus-`==`.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application import export_resume
from careerhq.application.export_resume import export_version
from careerhq.application.submissions import APPLIED_OR_LATER, has_applied, submission_for
from careerhq.application.submit_resume import submit_version
from careerhq.application.tailor_resume import create_pending_version
from careerhq.domain.models import (
    Application,
    ExperienceBullet,
    NormalizedStatus,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    Skill,
    SourceKind,
    SubmittedResume,
    User,
    VersionStatus,
    WorkExperience,
    normalize_status,
)
from careerhq.domain.schemas.document import ResumeDocument
from careerhq.infrastructure import storage
from careerhq.infrastructure.security import SESSION_COOKIE, create_session_token
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

_SENT = "Owned the settlement service end to end, from schema to on-call."
_LATER = "Rewrote the settlement service after they had already read the PDF."


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


@pytest.fixture
def readable_documents(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Stored bytes that can be read back and searched.

    **The renderer is replaced by one whose output is inspectable**, so the FR-023
    assertion can be *"the stored document still says what it said"* rather than only
    *"the checksum still matches"*. A checksum comparison alone is nearly a tautology
    here: both sides of it come from the same record, and an implementation that
    recomputed the whole thing from live profile data would move them together. Real
    PDF bytes are compressed and cannot be searched for a sentence.
    """
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


async def _submitted(
    session: AsyncSession, *, sub: str, label: str = "Applied"
) -> tuple[User, Application, ResumeVersion, SubmittedResume]:
    """A real run of the real path: export, then submit. No hand-built rows.

    The application's status goes through `normalize_status`, which is the only thing
    that decides the analytics category — hand-picking the enum member would test a
    classification the system never performs.
    """
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
    version.status = VersionStatus.READY
    await session.flush()
    await session.refresh(version, ["items"])

    await export_version(session, version_id=version.id)
    record = await submit_version(session, version_id=version.id)

    seeded.application.status = label
    seeded.application.normalized_status = normalize_status(label)
    await session.commit()
    return seeded.user, seeded.application, version, record


def _snapshot(record: SubmittedResume) -> dict[str, Any]:
    return {
        "id": record.id,
        "resume_version_id": record.resume_version_id,
        "application_id": record.application_id,
        "document_storage_key": record.document_storage_key,
        "checksum_sha256": record.checksum_sha256,
        "byte_size": record.byte_size,
        "submitted_at": record.submitted_at,
    }


async def _reload_record(session: AsyncSession, record_id: uuid.UUID) -> SubmittedResume:
    row = await session.scalar(select_submission(record_id))
    assert row is not None
    return row


def select_submission(record_id: uuid.UUID) -> sa.Select[tuple[SubmittedResume]]:
    return sa.select(SubmittedResume).where(SubmittedResume.id == record_id)


# ======================================================================================
# FR-023 — the artefact is a historical fact
# ======================================================================================


async def test_editing_the_profile_after_submission_changes_nothing_about_the_record(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """The scenario FR-023 is written for, through the routes a person actually has.

    The bullet that is rewritten is **the one whose text is in the submitted document**,
    which is what makes this a test of the snapshot rather than of an unrelated row: an
    implementation that derived the record from live profile data would produce different
    bytes for exactly this edit and pass any assertion made about a bullet the résumé
    never carried.
    """
    user, _application, _version, record = await _submitted(db_session, sub="hist-edit")
    before = _snapshot(record)
    key = record.document_storage_key
    sent_bytes = readable_documents[key]

    bullet = await db_session.scalar(
        sa.select(ExperienceBullet).where(
            ExperienceBullet.experience_id.in_(
                sa.select(WorkExperience.id).where(
                    WorkExperience.profile_id
                    == (
                        await db_session.scalar(
                            sa.select(ResumeVersion.profile_id).where(
                                ResumeVersion.id == _version.id
                            )
                        )
                    )
                )
            )
        )
    )
    assert bullet is not None, "the fixture seeded no bullet to edit"

    response = await _as(client, user).patch(
        f"/api/profile/bullet/{bullet.id}", json={"text": _LATER}
    )
    assert response.status_code == 200, response.text

    async with session_factory() as check:
        after = await _reload_record(check, before["id"])
        assert _snapshot(after) == before, "a profile edit moved the submitted record"

    assert readable_documents[key] == sent_bytes, "the stored document was rewritten"
    assert _SENT.encode() in readable_documents[key]
    assert _LATER.encode() not in readable_documents[key], (
        "the later edit reached the document that was already sent"
    )
    assert hashlib.sha256(readable_documents[key]).hexdigest() == before["checksum_sha256"]


async def test_deleting_profile_content_after_submission_changes_nothing(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """Deletion is a different mutation from correction, and fails differently.

    An edit changes a value the record might have copied; a deletion removes the row the
    record might have *pointed at*. A snapshot survives both; a reference survives
    neither, and only one of the two would be caught by the test above.
    """
    user, _application, _version, record = await _submitted(db_session, sub="hist-del")
    before = _snapshot(record)
    sent_bytes = readable_documents[record.document_storage_key]

    response = await _as(client, user).delete("/api/profile/skill")
    assert response.status_code == 204, response.text

    async with session_factory() as check:
        assert _snapshot(await _reload_record(check, before["id"])) == before
        remaining = await check.scalar(
            sa.select(sa.func.count())
            .select_from(Skill)
            .where(Skill.profile_id == _version.profile_id)
        )
        assert remaining == 0, "the deletion under test did not actually delete anything"

    assert readable_documents[record.document_storage_key] == sent_bytes


async def test_the_submitted_record_has_no_live_path_to_profile_data(
    db_session: AsyncSession,
) -> None:
    """The structural half, and it is the half that lasts.

    The behavioural tests above can only catch a live read that happens to change a value
    they looked at. This states the property that makes such a read impossible: every
    foreign key on `submitted_resumes` points at the version or the application, and the
    model declares **no ORM relationships at all** — so there is nothing to traverse from
    a submission to a profile, a work experience or a skill, and no lazy load that could
    quietly become the source of an answer.
    """
    targets = {
        column.name: sorted(fk.target_fullname for fk in column.foreign_keys)
        for column in SubmittedResume.__table__.columns
        if column.foreign_keys
    }
    assert targets == {
        "resume_version_id": ["resume_versions.id"],
        "application_id": ["applications.id"],
    }, f"a submission gained a foreign key into live data: {targets}"

    relationships = sorted(sa.inspect(SubmittedResume).relationships.keys())
    assert relationships == [], (
        f"a submission can traverse to live rows: {relationships}; the record is a "
        "snapshot and must have nothing to read from"
    )

    snapshotted = {"document_storage_key", "checksum_sha256", "byte_size", "submitted_at"}
    columns = {c.name for c in SubmittedResume.__table__.columns}
    assert snapshotted <= columns, f"the snapshot lost a column: {sorted(snapshotted - columns)}"


# ======================================================================================
# FR-024 — the application references it
# ======================================================================================


async def test_applied_or_later_is_every_status_only_reachable_by_applying() -> None:
    """Which categories the invariant covers, argued rather than listed.

    `NormalizedStatus` is an analytics category, not a lifecycle position, so "later" has
    to be derived from what a category *implies*. `REJECTED` and `GHOSTED` are here
    because you cannot be rejected or ghosted by an employer you never wrote to.

    **`WITHDRAWN` is deliberately excluded**, and this is the judgement worth stating:
    `docs/03` §10.2 draws `Wishlist → Withdrawn` directly, so a withdrawn application may
    never have been sent. **`OTHER` is excluded** because it is the bucket for a label
    this system does not recognise — it asserts nothing, and an invariant asserted over
    an unknown is a guess.
    """
    assert APPLIED_OR_LATER == {
        NormalizedStatus.APPLIED,
        NormalizedStatus.INTERVIEWING,
        NormalizedStatus.OFFER,
        NormalizedStatus.REJECTED,
        NormalizedStatus.GHOSTED,
    }

    earlier = [s for s in NormalizedStatus if s not in APPLIED_OR_LATER]
    assert earlier == [
        NormalizedStatus.WISHLIST,
        NormalizedStatus.WITHDRAWN,
        NormalizedStatus.OTHER,
    ], "a status was added or reclassified without deciding whether it implies applying"

    for status in APPLIED_OR_LATER:
        assert has_applied(status)
    for status in earlier:
        assert not has_applied(status)

    # `normalized_status` is a `String` column, so a row from a fresh session is a `str`.
    assert has_applied("applied") and not has_applied("wishlist")


@pytest.mark.parametrize(
    "label",
    ["Applied", "Interview Round 2", "Offer Received", "Rejected", "Ghosted"],
)
async def test_an_application_in_applied_or_later_resolves_to_its_submission(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
    label: str,
) -> None:
    """Constitution IV, through the real labels an import actually carries.

    Parametrised over the user's own words rather than the enum, because
    `normalize_status` is what turns "Interview Round 2" into a category and hand-picking
    `INTERVIEWING` would skip the only step that can get it wrong.
    """
    _user, application, version, record = await _submitted(
        db_session, sub=f"fr024-{label.split()[0].lower()}", label=label
    )

    async with session_factory() as check:
        loaded = await check.get(Application, application.id)
        assert loaded is not None
        assert has_applied(loaded.normalized_status), f"{label!r} did not normalize past wishlist"

        found = await submission_for(check, application_id=application.id)
        assert found is not None, "an applied application resolves to no submission"
        assert found.id == record.id
        assert found.resume_version_id == version.id
        assert found.checksum_sha256 == record.checksum_sha256


async def test_a_wishlist_application_has_no_submission_and_none_is_invented(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`docs/03` §5.2: *"An Application may exist without a Submitted Resume while in
    `Wishlist`."*

    The answer must be **absence**, not a nearest-available document. A version, an
    export, or the master résumé would each make the invariant appear satisfied while
    naming something the employer never received.
    """
    seeded = await seed_tailorable(db_session, sub="fr024-wish", email="fr024-wish@example.com")
    await db_session.commit()

    async with session_factory() as check:
        assert await submission_for(check, application_id=seeded.application.id) is None


async def test_an_exported_but_unsubmitted_version_is_never_offered_as_what_was_sent(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """`docs/03` §12.2: *"Applications may not reference editable Resume Versions as
    submitted documents."*

    An exported version is the closest thing to a sent document that is not one: the PDF
    exists, the checksum exists, and a lookup that fell back to "the most recent export"
    would answer confidently and wrongly. Export does not imply submission — a person may
    export a PDF and never send it.
    """
    seeded = await seed_tailorable(db_session, sub="fr024-exp", email="fr024-exp@example.com")
    version = await create_pending_version(db_session, seeded.application)
    db_session.add(
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
    version.status = VersionStatus.READY
    await db_session.flush()
    await db_session.refresh(version, ["items"])
    await export_version(db_session, version_id=version.id)

    seeded.application.status = "Applied"
    seeded.application.normalized_status = normalize_status("Applied")
    await db_session.commit()

    async with session_factory() as check:
        assert await submission_for(check, application_id=seeded.application.id) is None


async def test_each_application_resolves_to_its_own_submission(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """Two applications, two submissions, and neither answers for the other.

    A lookup that ignored the id it was given would satisfy every test above — there is
    only one row in each of them — and would show one employer's résumé under another's
    job.
    """
    _u1, first_app, _v1, first = await _submitted(db_session, sub="fr024-a")
    _u2, second_app, _v2, second = await _submitted(db_session, sub="fr024-b")
    assert first.id != second.id

    async with session_factory() as check:
        found_first = await submission_for(check, application_id=first_app.id)
        found_second = await submission_for(check, application_id=second_app.id)

    assert found_first is not None and found_second is not None
    assert found_first.id == first.id
    assert found_second.id == second.id


async def test_a_submission_cannot_exist_without_an_application(
    db_session: AsyncSession,
) -> None:
    """The reference is mandatory in the schema, not by convention.

    Constitution IV's requirement is that the application can show what it sent; a
    nullable `application_id` would let a submission exist that no application can reach,
    and the failure would be invisible until someone went looking for the document.
    """
    column = SubmittedResume.__table__.c.application_id
    assert not column.nullable, "a submission may be written with no application to reach it from"

    with pytest.raises(sa.exc.IntegrityError):
        db_session.add(
            SubmittedResume(
                resume_version_id=uuid.uuid4(),
                application_id=None,
                document_storage_key="exports/orphan.pdf",
                checksum_sha256="0" * 64,
                byte_size=1,
            )
        )
        await db_session.flush()
    await db_session.rollback()


async def test_the_application_cannot_be_deleted_out_from_under_its_submission(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """The reference cannot be made to dangle by deleting what it points at.

    ***Which constraint refuses is not what this test proves, and a drill is why that is
    stated.*** Flipping `submitted_resumes.application_id` to `CASCADE` left this green:
    `applications → resume_versions` cascades, so the delete reaches
    `submitted_resumes.resume_version_id` — also `RESTRICT` — and is refused *there*
    first. The application FK's own `ondelete` is therefore unreachable behaviourally and
    is asserted structurally in the test below instead. What this one proves is the
    outcome Constitution IV needs: the row survives, and the delete does not succeed.
    """
    _user, application, _version, record = await _submitted(db_session, sub="fr024-restrict")

    async with session_factory() as session:
        with pytest.raises(sa.exc.IntegrityError):
            await session.execute(sa.delete(Application).where(Application.id == application.id))
            await session.flush()
        await session.rollback()

    async with session_factory() as check:
        assert await _reload_record(check, record.id) is not None
        assert await check.get(Application, application.id) is not None


async def test_both_of_the_submissions_foreign_keys_refuse_deletion() -> None:
    """`RESTRICT` on both, where the rest of this schema cascades — asserted, not assumed.

    Deliberate: Constitution IV requires an application in `Applied` or later to be able
    to show what it sent, so deleting the version or the application out from under a
    submission must be **refused** rather than silently taking the evidence with it.

    Structural because it cannot be reached any other way. The cascade from
    `applications` to `resume_versions` means the version FK always answers first, so a
    behavioural test cannot tell `RESTRICT` from `CASCADE` on the application FK — and
    a drill that flipped it to `CASCADE` passed every behavioural test in this file.
    """
    rules = {
        column.name: {fk.ondelete for fk in column.foreign_keys}
        for column in SubmittedResume.__table__.columns
        if column.foreign_keys
    }
    assert rules == {
        "resume_version_id": {"RESTRICT"},
        "application_id": {"RESTRICT"},
    }, f"a submission's evidence can be deleted out from under it: {rules}"


async def test_a_later_export_for_the_same_job_does_not_touch_the_sent_document(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    readable_documents: dict[str, bytes],
) -> None:
    """The realistic way a later change *could* reach a sent document, closed off.

    Editing a profile does not by itself rewrite anything — the version already holds its
    own copies. The path that actually threatens FR-023 is the ordinary one: correct the
    profile, tailor the job again, export again. If the exporter reused a storage key,
    that second export would overwrite the bytes the first submission recorded a checksum
    for, and the submitted record would still look perfect while pointing at a document
    the employer never saw.

    T036 already asserts two exports get different keys; this asserts the consequence
    that matters — the **submitted** bytes are still there, still theirs, and still hash
    to the recorded value.
    """
    _user, application, first_version, record = await _submitted(db_session, sub="hist-reexport")
    before = _snapshot(record)
    sent_key = record.document_storage_key
    sent_bytes = readable_documents[sent_key]

    later = ResumeVersion(
        profile_id=first_version.profile_id,
        application_id=application.id,
        source_resume_profile_id=first_version.source_resume_profile_id,
        source_profile_updated_at=first_version.source_profile_updated_at,
        name="Second attempt",
        status=VersionStatus.READY,
        items=[
            ResumeVersionItem(
                source_kind=SourceKind.EXPERIENCE_BULLET,
                position=0,
                original_text=_LATER,
                final_text=_LATER,
                decision=ProposalDecision.ACCEPTED,
                included=True,
            )
        ],
    )
    db_session.add(later)
    await db_session.flush()
    second = await export_version(db_session, version_id=later.id)
    await db_session.commit()

    assert second.document_storage_key != sent_key, "the re-export overwrote the sent document"
    assert readable_documents[sent_key] == sent_bytes
    assert _LATER.encode() not in readable_documents[sent_key]
    assert hashlib.sha256(readable_documents[sent_key]).hexdigest() == before["checksum_sha256"]

    async with session_factory() as check:
        assert _snapshot(await _reload_record(check, before["id"])) == before
        # The submission still names the *first* version, not the newer document.
        assert (await _reload_record(check, before["id"])).resume_version_id == first_version.id
        found = await submission_for(check, application_id=application.id)
        assert found is not None and found.id == record.id, (
            "a later export displaced the submission the application references"
        )
