"""T038 — the submission path: refuse, re-read, re-verify, record, transition.

**Submission promotes an export; it never produces one.** The bytes an employer
received already exist, and the only honest thing to record about them is what they
actually are *now* — which is why the order below is the substance of the task:

    ensure_submittable  →  load the stored bytes  →  SHA-256  →  compare the recorded
    checksum  →  SubmittedResume  →  status = SUBMITTED

**The recorded checksum is not evidence about the bytes.** It is evidence about what the
export *believed* it stored. FR-021 asks for "a stable checksum of the exact document
sent", and Constitution IV rests on being able to show that document later; trusting the
row would make submission a copy operation that verifies nothing, and would pass happily
against an object that had been replaced, truncated or lost. So the bytes are read back
and hashed, and the comparison is the precondition.

**A mismatch refuses, and repairs nothing.** Not by re-rendering — the version's items may
have moved on, so a re-render is a *different* document wearing the same lifecycle — and
not by rewriting the export's checksum, which would launder the corruption into a record
that then looks verified forever. The refusal leaves both the object and the row exactly
as they were, for a person to look at.
"""

from __future__ import annotations

import ast
import hashlib
import pathlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from careerhq.application.submit_resume import (
    ExportChecksumMismatch,
    SubmissionRefused,
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
    VersionStatus,
)
from careerhq.infrastructure import storage
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

#: Read at import time, not inside the test. Every test in this module carries the
#: module-wide `asyncio` mark, and `pathlib` inside an async function is refused by
#: ASYNC240 — the file is read once here instead of the rule being suppressed.
_SUBMIT_SOURCE = pathlib.Path("src/careerhq/application/submit_resume.py").read_text()

_PDF = b"%PDF-1.7\nthe-document-that-was-sent\n%%EOF\n"
_TAMPERED = b"%PDF-1.7\nsomething-else-entirely\n%%EOF\n"
_SUMMARY = "Senior Backend Engineer with six years on payment platforms."


class _Storage:
    """An object store that records what it was asked to do, and in which order."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.order: list[str] = []
        self.read_keys: list[str] = []

    async def get(self, key: str) -> bytes:
        self.order.append("read")
        self.read_keys.append(key)
        return self.objects[key]

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.order.append("write")
        self.objects[key] = data


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Storage:
    fake = _Storage()
    monkeypatch.setattr(storage, "get_object", fake.get)
    monkeypatch.setattr(storage, "put_object", fake.put)
    return fake


@pytest.fixture
def no_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Submission must not render. Asserted by making a render impossible, not implied.

    A test that only checks the output would pass against a use case that re-rendered
    and happened to get the same bytes back — which is exactly what FR-031's
    byte-determinism would arrange on this runtime, so the strongest guarantee in the
    export path is what would hide the defect here.
    """
    import careerhq.infrastructure.documents.render as render_module

    def _forbidden(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("submission rendered the resume instead of reading stored bytes")

    monkeypatch.setattr(render_module, "render_resume_pdf", _forbidden)


async def _seed_version(session: AsyncSession, *, sub: str, status: VersionStatus) -> ResumeVersion:
    seeded = await seed_tailorable(session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(session, seeded.application)
    session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.SUMMARY,
            position=0,
            original_text=_SUMMARY,
            final_text=_SUMMARY,
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    version.status = status
    await session.flush()
    await session.refresh(version, ["items"])
    return version


async def _seed_export(
    session: AsyncSession,
    store: _Storage,
    version: ResumeVersion,
    *,
    data: bytes = _PDF,
    at: datetime | None = None,
) -> ExportedDocument:
    """An export exactly as `export_version` leaves one: bytes stored, row recorded.

    `at` is set explicitly wherever a test cares which export is the later one.
    `exported_at` defaults to `now()`, which PostgreSQL evaluates **once per
    transaction** — so two exports seeded here would otherwise carry the same timestamp,
    which no pair of real exports does: each is its own request and its own transaction.
    """
    key = f"exports/{version.profile_id}/{version.id}/{uuid.uuid4()}.pdf"
    store.objects[key] = data
    record = ExportedDocument(
        resume_version_id=version.id,
        document_storage_key=key,
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )
    if at is not None:
        record.exported_at = at
    session.add(record)
    await session.flush()
    return record


async def _submissions(session: AsyncSession, version_id: uuid.UUID) -> list[SubmittedResume]:
    rows = await session.execute(
        sa.select(SubmittedResume).where(SubmittedResume.resume_version_id == version_id)
    )
    return list(rows.scalars())


@pytest.mark.parametrize(
    "status",
    [
        VersionStatus.DRAFT,
        VersionStatus.TAILORING,
        VersionStatus.REVIEWING,
        VersionStatus.AWAITING_APPROVAL,
        VersionStatus.READY,
        VersionStatus.SUBMITTED,
    ],
)
async def test_a_non_exported_version_is_refused_before_any_storage_read(
    db_session: AsyncSession, store: _Storage, no_renderer: None, status: VersionStatus
) -> None:
    """The precondition is `EXPORTED`, and it is checked before anything with a cost.

    `READY` is the one worth reading twice: the version *is* approved, and every other
    part of the system treats that as the green light. Submission is different — there
    is no document to be the record of, so there is nothing to verify and nothing to
    freeze. `SUBMITTED` is refused because it is terminal.

    Asserted on the **spy**, not only on the exception: a use case that read the object,
    then checked the status, then raised would satisfy "it refused" while having already
    gone to object storage for a version that may not have one.
    """
    version = await _seed_version(db_session, sub=f"sub-{status.value[:9]}", status=status)

    with pytest.raises(SubmissionRefused):
        await submit_version(db_session, version_id=version.id)

    assert store.order == [], f"work was done before the refusal: {store.order}"
    assert await _submissions(db_session, version.id) == []

    await db_session.refresh(version)
    assert version.status == status, "a refused submission changed the version's status"


async def test_a_second_submission_is_refused_without_going_to_object_storage(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """The refusal-ordering claim, tested in the one state where it can actually fail.

    **Added because a drill exposed the test above as weaker than the claim it makes.**
    Moving `ensure_submittable` to *after* the storage read left that test green: none of
    its statuses has an exported document to read, so there was nothing for a
    mis-ordered use case to do early. A submitted version does have one — it was
    exported before it was sent — which makes this the state that distinguishes a guard
    that runs first from one that merely runs.
    """
    version = await _seed_version(db_session, sub="sub-twice", status=VersionStatus.EXPORTED)
    await _seed_export(db_session, store, version)
    await submit_version(db_session, version_id=version.id)
    store.order.clear()
    store.read_keys.clear()

    with pytest.raises(SubmissionRefused):
        await submit_version(db_session, version_id=version.id)

    assert store.order == [], f"the guard ran after object storage was read: {store.order}"
    assert len(await _submissions(db_session, version.id)) == 1, "a second submission was recorded"


async def test_an_exported_version_whose_bytes_still_match_is_submitted(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """The whole path, and the order it happens in."""
    version = await _seed_version(db_session, sub="sub-ok", status=VersionStatus.EXPORTED)
    export = await _seed_export(db_session, store, version)

    record = await submit_version(db_session, version_id=version.id)

    assert store.order == ["read"], f"wrong order, or extra work: {store.order}"
    assert store.read_keys == [export.document_storage_key], (
        "the bytes were not read back from the key the export recorded"
    )

    assert record.resume_version_id == version.id
    assert record.application_id == version.application_id, (
        "the submission is not bound to the application it was sent for (FR-024)"
    )
    assert record.document_storage_key == export.document_storage_key, (
        "the submission points at a different object than the export it promotes"
    )
    assert record.checksum_sha256 == hashlib.sha256(_PDF).hexdigest(), (
        "the recorded checksum is not SHA-256 over the bytes storage returned"
    )
    assert record.byte_size == len(_PDF)

    await db_session.refresh(version)
    assert version.status == VersionStatus.SUBMITTED


async def test_the_checksum_is_computed_from_the_bytes_storage_returned(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """The claim the whole task rests on, stated so that copying the row cannot satisfy it.

    The stored object is replaced *after* the export recorded its checksum, and the
    recorded value is left alone. A use case that trusted the row would submit happily;
    one that hashes what storage handed back cannot.
    """
    version = await _seed_version(db_session, sub="sub-tamper", status=VersionStatus.EXPORTED)
    export = await _seed_export(db_session, store, version)
    store.objects[export.document_storage_key] = _TAMPERED

    with pytest.raises(ExportChecksumMismatch):
        await submit_version(db_session, version_id=version.id)

    assert store.order == ["read"], "the bytes were never read back"


async def test_a_checksum_mismatch_writes_no_submission_and_does_not_transition(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """A refusal that still left a record, or still moved the status, is not a refusal.

    Both halves are asserted because they fail independently: a use case that added the
    row before verifying would be caught by the first, and one that set the status first
    — the ordering mistake that costs nothing until it happens — only by the second.
    """
    version = await _seed_version(db_session, sub="sub-nowrite", status=VersionStatus.EXPORTED)
    export = await _seed_export(db_session, store, version)
    store.objects[export.document_storage_key] = _TAMPERED

    with pytest.raises(ExportChecksumMismatch):
        await submit_version(db_session, version_id=version.id)

    assert await _submissions(db_session, version.id) == [], (
        "a submission was recorded for a document that does not match its checksum"
    )
    await db_session.refresh(version)
    assert version.status == VersionStatus.EXPORTED, "the version was submitted despite a mismatch"


async def test_a_checksum_mismatch_repairs_nothing(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """Neither the object nor the export row may be corrected on the way past.

    Rewriting the checksum to agree with the bytes, or re-uploading bytes to agree with
    the checksum, would each turn an unexplained discrepancy into a record that looks
    verified — and destroy the only evidence that something went wrong.
    """
    version = await _seed_version(db_session, sub="sub-norepair", status=VersionStatus.EXPORTED)
    export = await _seed_export(db_session, store, version)
    recorded = export.checksum_sha256
    store.objects[export.document_storage_key] = _TAMPERED

    with pytest.raises(ExportChecksumMismatch):
        await submit_version(db_session, version_id=version.id)

    assert "write" not in store.order, "the stored export was overwritten by a submission"
    await db_session.refresh(export)
    assert export.checksum_sha256 == recorded, "the export's recorded checksum was rewritten"
    assert store.objects[export.document_storage_key] == _TAMPERED, (
        "the stored object was replaced instead of the discrepancy being reported"
    )


async def test_the_most_recently_exported_document_is_the_one_submitted(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """The document a person can download is the document they submit.

    Re-export is legitimate and writes a second row against the same version, so
    "which export" is a real question. It must be answered the same way the download
    route answers it, or a person downloads one object and freezes another.
    """
    version = await _seed_version(db_session, sub="sub-latest", status=VersionStatus.EXPORTED)
    earlier = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
    await _seed_export(db_session, store, version, at=earlier)
    second = await _seed_export(
        db_session, store, version, data=_PDF + b"% second\n", at=earlier + timedelta(minutes=5)
    )

    record = await submit_version(db_session, version_id=version.id)

    assert record.document_storage_key == second.document_storage_key
    assert store.read_keys == [second.document_storage_key]


async def test_an_exported_version_with_no_export_record_is_refused(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """A status that disagrees with the tables is refused, not crashed through.

    `export_version` writes the row and moves the status together, so this state should
    be unreachable — which is exactly why the behaviour has to be pinned: an
    inconsistency that surfaces as a `TypeError` deep in a hash call tells the person
    nothing and the operator less.
    """
    version = await _seed_version(db_session, sub="sub-norow", status=VersionStatus.EXPORTED)

    with pytest.raises(SubmissionRefused):
        await submit_version(db_session, version_id=version.id)

    assert store.order == []
    await db_session.refresh(version)
    assert version.status == VersionStatus.EXPORTED


async def test_the_use_case_reads_stored_bytes_and_never_renders(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """FR-021 is about *the document sent*, which only object storage has.

    Stated twice, because the behavioural half is weak on its own: the renderer is
    patched to raise, **and** the module is parsed to show it cannot reach one. A
    re-render on a byte-deterministic runtime produces the same bytes, so the output of
    a rendering implementation would be indistinguishable from a correct one right up
    until the version's items changed.
    """
    version = await _seed_version(db_session, sub="sub-norender", status=VersionStatus.EXPORTED)
    export = await _seed_export(db_session, store, version)

    await submit_version(db_session, version_id=version.id)

    assert store.read_keys == [export.document_storage_key], "storage was not read"


async def test_the_submit_use_case_cannot_reach_a_renderer() -> None:
    """The structural half, and it is the half that lasts.

    The behavioural test above patches the renderer to raise — but a re-render on a
    byte-deterministic runtime produces exactly the bytes that are already stored, so an
    implementation that rendered would be indistinguishable from a correct one until the
    version's items changed. This states it as an import-graph property instead:
    `submit_resume` imports no renderer, and does not import `export_resume` either,
    which can. `export.py` — where `latest_export` lives — is renderer-free by T033's
    own gate, which is what makes that one import safe.
    """
    tree = ast.parse(_SUBMIT_SOURCE, filename="submit_resume.py")

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert len(imported) >= 5, f"the check examined almost nothing: {sorted(imported)}"

    reachable = ("documents.render", "weasyprint", "export_resume")
    forbidden = {name for name in imported if any(word in name for word in reachable)}
    assert not forbidden, f"the submit use case can reach a renderer: {sorted(forbidden)}"


async def test_the_use_case_does_not_commit(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """The transaction boundary this project already uses.

    `run_tailoring` and `export_version` flush and leave the commit to the caller, so a
    route can span several use cases in one transaction. A use case that commits takes
    that decision away from every caller it will ever have.
    """
    version = await _seed_version(db_session, sub="sub-tx", status=VersionStatus.EXPORTED)
    await _seed_export(db_session, store, version)

    await submit_version(db_session, version_id=version.id)

    assert db_session.in_transaction(), "the use case committed or rolled back on its own"


async def test_a_missing_version_is_reported_not_silently_ignored(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """A use case that returns `None` for a missing id makes the route guess."""
    with pytest.raises(LookupError):
        await submit_version(db_session, version_id=uuid.uuid4())

    assert store.order == []


async def test_an_integrity_failure_is_not_a_state_refusal(
    db_session: AsyncSession, store: _Storage, no_renderer: None
) -> None:
    """Two different failures, two types, and neither may be caught as the other.

    A wrong-state refusal is the person's to resolve — export first. A checksum
    mismatch is nobody's to resolve by clicking again: the document is not what the
    record says it is. If `ExportChecksumMismatch` were a `SubmissionRefused`, a route
    handling refusals would report corruption as "export it first", and an
    implementation that deleted the integrity check entirely could still satisfy a test
    that only asked for "a refusal".
    """
    assert not issubclass(ExportChecksumMismatch, SubmissionRefused)
    assert not issubclass(SubmissionRefused, ExportChecksumMismatch)


async def test_writing_a_submission_emits_an_insert_and_never_an_update(
    engine: AsyncEngine,
    db_session: AsyncSession,
    store: _Storage,
    no_renderer: None,
) -> None:
    """T042's dynamic complement — what the database is actually told to do.

    **It does not replace the structural gate**, and cannot: watching one run prove that
    *these* operations emitted no UPDATE says nothing about the paths this run did not
    take, which is the whole of an absence claim.
    `test_architecture.py::test_a_submitted_resume_is_insert_only` is where that lives.

    What this adds is the other direction. The gate reads syntax and reasons about what a
    statement *would* be; this reads the statements. An ORM has more than one way to turn
    a save into an UPDATE — a merge, a re-added detached instance, a flush of something
    the identity map already knows — and none of those looks different in a syntax tree
    from the insert beside it. So the cursor is watched, and every statement naming
    `submitted_resumes` is classified.
    """
    seen: list[str] = []

    def _record(conn: object, cursor: object, statement: str, *args: object) -> None:
        if "submitted_resumes" in statement.lower():
            seen.append(statement.strip().split()[0].upper())

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        version = await _seed_version(db_session, sub="sub-stmts", status=VersionStatus.EXPORTED)
        await _seed_export(db_session, store, version)
        record = await submit_version(db_session, version_id=version.id)
        await db_session.flush()

        # A read afterwards, so the SELECT side of the classification is exercised too
        # and "no UPDATE" is not satisfied by the table never being touched at all.
        await db_session.scalar(sa.select(SubmittedResume).where(SubmittedResume.id == record.id))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)

    assert seen, "no statement touched submitted_resumes; the watch examined nothing"
    assert seen.count("INSERT") == 1, f"expected exactly one INSERT, saw {seen}"
    assert set(seen) <= {"INSERT", "SELECT"}, (
        f"a submission was written with something other than an INSERT: {seen}"
    )
