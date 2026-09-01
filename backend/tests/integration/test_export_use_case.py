"""T036 — the export use case: refuse, render, store, record, transition.

**Export is a workflow operation, not a render.** The renderer turns content into bytes
(T031/T035); this turns an approved version into a *stored artefact with a lifecycle* —
which is why the ordering below is the substance of the task rather than an
implementation detail:

    ensure_exportable  →  render  →  put bytes  →  ExportedDocument  →  status = EXPORTED

**Bytes are stored before the row is written, deliberately.** Object storage is outside
the transaction, so one of the two failure directions has to be chosen. Storing first
means a failed commit leaves an orphan object — garbage, and cheap. Writing the row first
would mean a failed upload leaves a record pointing at nothing, and FR-021's checksum
would refer to bytes that do not exist. A record that lies is worse than a file nobody
reads.

**`READY` is the approved state**, not `APPROVED` (T005/T033), `EXPORTED` is re-exportable
because `ExportedDocument` has no unique constraint on the version, and `SUBMITTED` is
refused because it is terminal.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application import export_resume
from careerhq.application.export import ExportRefused
from careerhq.application.export_resume import export_version
from careerhq.application.guidelines import StaticGuidelines
from careerhq.application.tailor_resume import (
    approve_version,
    create_pending_version,
    decide_item,
    run_tailoring,
)
from careerhq.domain.models import (
    ExportedDocument,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    SourceKind,
    VersionStatus,
)
from careerhq.infrastructure import storage
from tests.integration.test_tailoring_workflow import _draft, _plan, _review
from tests.support.scripted_seam import ScriptedSeam
from tests.support.tailoring_fixtures import seed_tailorable

pytestmark = pytest.mark.asyncio

_SUMMARY = "Senior Backend Engineer with six years on payment platforms."
_BULLET = "Owned the settlement service end to end, from schema to on-call."
_DROPPED = "Ran the office five-a-side league."


class _Spy:
    """Records what the boundaries were asked to do, and in which order."""

    def __init__(self) -> None:
        self.rendered: list[object] = []
        self.stored: list[tuple[str, bytes, str]] = []
        self.order: list[str] = []
        self.pdf = b"%PDF-1.7\nfake-but-stable\n%%EOF\n"
        self.storage_fails = False

    def render(self, document: object) -> bytes:
        self.order.append("render")
        self.rendered.append(document)
        return self.pdf

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.order.append("store")
        if self.storage_fails:
            raise RuntimeError("object storage is unreachable")
        self.stored.append((key, data, content_type))


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    recorder = _Spy()
    monkeypatch.setattr(export_resume, "render_resume_pdf", recorder.render)
    monkeypatch.setattr(storage, "put_object", recorder.put)
    return recorder


async def _seed_version(session: AsyncSession, *, sub: str, status: VersionStatus) -> ResumeVersion:
    seeded = await seed_tailorable(session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(session, seeded.application)

    session.add_all(
        [
            ResumeVersionItem(
                resume_version_id=version.id,
                source_kind=SourceKind.SUMMARY,
                position=0,
                original_text=_SUMMARY,
                final_text=_SUMMARY,
                decision=ProposalDecision.ACCEPTED,
                included=True,
            ),
            ResumeVersionItem(
                resume_version_id=version.id,
                source_kind=SourceKind.EXPERIENCE_BULLET,
                position=0,
                original_text=_BULLET,
                final_text=_BULLET,
                decision=ProposalDecision.ACCEPTED,
                included=True,
            ),
            ResumeVersionItem(
                resume_version_id=version.id,
                source_kind=SourceKind.EXPERIENCE_BULLET,
                position=1,
                original_text=_DROPPED,
                final_text=_DROPPED,
                decision=ProposalDecision.ACCEPTED,
                included=False,
            ),
        ]
    )
    version.status = status
    await session.flush()
    # The version was constructed in this session with an empty `items` collection, so
    # the identity map would otherwise hand the use case a stale, empty relationship —
    # the document came out empty and two assertions passed anyway. **An awaited
    # `refresh`, never `expire`**: expiring makes the next attribute access do IO
    # synchronously, which async SQLAlchemy answers with `MissingGreenlet`.
    await session.refresh(version, ["items"])
    return version


async def test_a_rejected_drop_reaches_the_exported_document(
    db_session: AsyncSession, spy: _Spy, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The whole chain, end to end: the agent proposes removing a bullet, the
    owner rejects the removal, and the exported document carries the line.

    The export side alone is already gated (`included=False` leaves the
    document); this is the other direction — a rejection that restored
    `included` must actually be honoured by what gets rendered. Each half can
    pass while the chain is broken only at the column they meet on, which is
    why this test runs the real run, the real decision, and the real export.
    """
    seeded = await seed_tailorable(db_session, sub="export-drop", email="export-drop@example.com")
    rewritten, dropped = seeded.bullet_ids
    version = await create_pending_version(db_session, seeded.application)
    await db_session.commit()

    draft = _draft(rewritten, "Led payments for six years, matching the posting.")
    draft["items"].append(
        {
            "source_item_id": str(dropped),
            "source_kind": "experience_bullet",
            "position": 1,
            "included": False,
        }
    )
    seam = ScriptedSeam(
        script={
            "tailor_plan": [_plan()],
            "tailor_draft": [draft],
            "tailor_review": [_review(90)],
        }
    )
    async with session_factory() as session:
        await run_tailoring(
            session, version_id=version.id, completion=seam, guidelines=StaticGuidelines()
        )
        await session.commit()

    async with session_factory() as session:
        reloaded = (
            (
                await session.execute(
                    sa.select(ResumeVersion)
                    .where(ResumeVersion.id == version.id)
                    .options(sa.orm.selectinload(ResumeVersion.items))
                )
            )
            .unique()
            .scalar_one()
        )
        drop_row = next(i for i in reloaded.items if i.source_item_id == dropped)
        kept_wording = drop_row.original_text
        await decide_item(session, item=drop_row, decision=ProposalDecision.REJECTED, text=None)
        await approve_version(session, version=reloaded)
        await session.commit()

    async with session_factory() as session:
        await export_version(session, version_id=version.id)
        await session.commit()

    assert len(spy.rendered) == 1
    document = spy.rendered[0]
    lines = [
        line for section in document.sections for group in section.groups for line in group.lines
    ]  # type: ignore[attr-defined]
    assert kept_wording in lines, "the rejected removal must be back in the document"


async def _records(session: AsyncSession, version_id: uuid.UUID) -> list[ExportedDocument]:
    rows = await session.execute(
        sa.select(ExportedDocument).where(ExportedDocument.resume_version_id == version_id)
    )
    return list(rows.scalars())


@pytest.mark.parametrize(
    "status",
    [
        VersionStatus.DRAFT,
        VersionStatus.TAILORING,
        VersionStatus.REVIEWING,
        VersionStatus.AWAITING_APPROVAL,
        VersionStatus.SUBMITTED,
    ],
)
async def test_a_non_exportable_version_is_refused_before_rendering_or_storage(
    db_session: AsyncSession, spy: _Spy, status: VersionStatus
) -> None:
    """FR-016, and the ordering claim that makes the guard worth having.

    Asserted on the **spies**, not only on the exception: a use case that rendered, then
    checked the status, then raised would satisfy "it refused" while having spent the
    render and — worse — possibly the upload.
    """
    version = await _seed_version(db_session, sub=f"exp-{status.value[:8]}", status=status)

    with pytest.raises(ExportRefused):
        await export_version(db_session, version_id=version.id)

    assert spy.order == [], f"work was done before the refusal: {spy.order}"
    assert spy.rendered == [] and spy.stored == []
    assert await _records(db_session, version.id) == []

    await db_session.refresh(version)
    assert version.status == status, "a refused export changed the version's status"


async def test_an_approved_version_renders_stores_records_and_transitions(
    db_session: AsyncSession, spy: _Spy
) -> None:
    """The whole path, and the order it happens in."""
    version = await _seed_version(db_session, sub="exp-ready", status=VersionStatus.READY)

    record = await export_version(db_session, version_id=version.id)

    assert spy.order == ["render", "store"], f"wrong order: {spy.order}"
    assert len(spy.rendered) == 1, "the renderer was not invoked exactly once"

    key, data, content_type = spy.stored[0]
    assert data == spy.pdf, "storage did not receive the bytes the renderer produced"
    assert content_type == "application/pdf"

    assert record.document_storage_key == key, (
        "the recorded key is not the key the bytes were stored under"
    )
    assert record.checksum_sha256 == hashlib.sha256(data).hexdigest(), (
        "the checksum is not SHA-256 over the exact stored bytes"
    )
    assert record.byte_size == len(data)
    assert record.resume_version_id == version.id

    await db_session.refresh(version)
    assert version.status == VersionStatus.EXPORTED


async def test_the_document_carries_the_included_items_and_not_the_dropped_one(
    db_session: AsyncSession, spy: _Spy
) -> None:
    """FR-017 at the use-case boundary: what the renderer is handed.

    A dropped item (`included=False`) is still a row — the diff shows it — and must not
    reach the document. **A rejected proposal is different and is not a drop**: its
    `final_text` is the owner's original wording, which does belong in the résumé.
    """
    version = await _seed_version(db_session, sub="exp-content", status=VersionStatus.READY)

    await export_version(db_session, version_id=version.id)

    document = spy.rendered[0]
    lines = document.lines_in_order()  # type: ignore[attr-defined]

    assert _SUMMARY in lines and _BULLET in lines
    assert _DROPPED not in lines, "an item the owner dropped was exported"


async def test_re_exporting_an_exported_version_is_allowed_and_records_both(
    db_session: AsyncSession, spy: _Spy
) -> None:
    """`ExportedDocument` has no unique constraint on the version, on purpose.

    A download that failed, a second copy: the honest record is that the export happened
    twice. Asserted on **two rows**, because a use case that quietly updated the first
    would satisfy "re-export is allowed" while destroying the earlier record.
    """
    version = await _seed_version(db_session, sub="exp-again", status=VersionStatus.READY)

    first = await export_version(db_session, version_id=version.id)
    await db_session.refresh(version)
    assert version.status == VersionStatus.EXPORTED

    second = await export_version(db_session, version_id=version.id)

    rows = await _records(db_session, version.id)
    assert len(rows) == 2, f"re-export produced {len(rows)} record(s)"
    assert first.id != second.id
    assert first.document_storage_key != second.document_storage_key, (
        "the second export overwrote the first one's object"
    )


async def test_a_storage_failure_records_no_export_and_leaves_the_status_alone(
    db_session: AsyncSession, spy: _Spy
) -> None:
    """The reason bytes are stored before the row is written.

    A record whose checksum refers to bytes that were never stored is worse than no
    record: FR-021's re-verification would fail on a document the user believes exists.
    """
    spy.storage_fails = True
    version = await _seed_version(db_session, sub="exp-nostore", status=VersionStatus.READY)

    with pytest.raises(RuntimeError, match="object storage"):
        await export_version(db_session, version_id=version.id)

    assert spy.order == ["render", "store"], "the upload was never attempted"
    assert await _records(db_session, version.id) == [], "an export was recorded without bytes"

    await db_session.refresh(version)
    assert version.status == VersionStatus.READY, "the version moved on despite the failure"


async def test_the_use_case_does_not_commit(db_session: AsyncSession, spy: _Spy) -> None:
    """The transaction boundary this project already uses.

    `run_tailoring` flushes and the caller commits, so a route can span several use cases
    in one transaction. Export must not differ: a use case that commits takes that
    decision away from every caller it will ever have.
    """
    version = await _seed_version(db_session, sub="exp-tx", status=VersionStatus.READY)

    await export_version(db_session, version_id=version.id)

    assert db_session.in_transaction(), "the use case committed or rolled back on its own"


async def test_exported_document_has_no_unique_constraint_on_the_version() -> None:
    """The schema property re-export depends on. Asserted, not remembered."""
    unique_on_version = [
        c
        for c in ExportedDocument.__table__.constraints
        if isinstance(c, sa.UniqueConstraint)
        and [col.name for col in c.columns] == ["resume_version_id"]
    ]
    indexes = [
        i
        for i in ExportedDocument.__table__.indexes
        if i.unique and [col.name for col in i.columns] == ["resume_version_id"]
    ]

    assert not unique_on_version and not indexes, (
        "a unique constraint on resume_version_id would refuse a legitimate re-export"
    )


async def test_a_missing_version_is_reported_not_silently_ignored(
    db_session: AsyncSession, spy: _Spy
) -> None:
    """A use case that returns `None` for a missing id makes the route guess."""
    with pytest.raises(LookupError):
        await export_version(db_session, version_id=uuid.uuid4())

    assert spy.order == []


async def test_the_use_case_is_a_separate_module_from_the_guard() -> None:
    """T033 asserts the *precondition* module imports no renderer, and it still must not.

    The use case therefore lives in `export_resume.py` — matching `extract_resume.py` and
    `tailor_resume.py` — rather than in `export.py`. `plan.md`'s file map put both in
    `export.py`; that would have made T033's guarantee unassertable.
    """
    import careerhq.application.export as guard

    assert not hasattr(guard, "export_version")
    assert hasattr(export_resume, "export_version")
