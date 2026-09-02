"""The theme's one hop: upload → staged → Master Resume → exported document.

**The whole reason this file exists is that the theme cannot be recovered later.** It is
readable only while the upload is in memory; by approval time the only remaining copy of
the bytes is the retained original, which no extraction path may read back. So the value
has to survive being written at import, copied at approval, and read at export — and each
of those three is asserted here rather than assumed.

The model call is stubbed, as everywhere else in this suite. Nothing here contacts a
provider and nothing spends a completion.
"""

from __future__ import annotations

import pathlib
import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from careerhq.application.approve_import import approve_import
from careerhq.application.extract_resume import extract_resume
from careerhq.application.ports import Completion, Usage
from careerhq.domain.models import (
    ImportedResume,
    ProfessionalProfile,
    ResumeProfile,
    User,
)
from careerhq.domain.schemas.theme import ResumeTheme
from careerhq.infrastructure import storage
from tests.unit.test_resume_theme import _fixture_pdf

#: Read at import time. Reading it inside an async test trips ASYNC240, and the bytes do
#: not change between tests.
_DOCX = (pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sample_cv.docx").read_bytes()

_DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_EXTRACTION: dict[str, Any] = {
    "contact": {"full_name": "Dana Levi", "email": "dana@example.com", "confidence": 0.95},
    "titles": [{"title": "Senior Backend Engineer", "confidence": 0.9}],
    "summary": {"text": "Backend engineer with six years on payment platforms.", "confidence": 0.8},
    "work_experience": [
        {
            "company": "Northwind Payments",
            "title": "Senior Backend Engineer",
            "start_date": "March 2019",
            "is_current": True,
            "confidence": 0.92,
            "bullets": [{"text": "Owned the settlement service end to end.", "confidence": 0.9}],
        }
    ],
    "skills": [{"name": "Python", "confidence": 0.99}],
}


class _Stub:
    """A completion client returning a fixed payload. No network, no key."""

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        return Completion(
            value=schema.model_validate(_EXTRACTION),
            usage=Usage(
                task=task,
                model="stub",
                input_tokens=1,
                output_tokens=1,
                cost=Decimal("0.000001"),
                is_fixture=True,
            ),
        )


@pytest.fixture(autouse=True)
def _no_object_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[str, bytes] = {}

    async def _put(key: str, data: bytes, *, content_type: str) -> None:
        stored[key] = data

    async def _get(key: str) -> bytes:
        return stored[key]

    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "get_object", _get)


async def _user_with_profile(session: AsyncSession) -> ProfessionalProfile:
    user = User(google_sub=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4()}@example.com")
    session.add(user)
    await session.flush()
    profile = ProfessionalProfile(user_id=user.id)
    session.add(profile)
    await session.flush()
    return profile


async def _import(
    session: AsyncSession, user_id: uuid.UUID, data: bytes, kind: str
) -> ImportedResume:
    """Import, then re-load with `items` eagerly — exactly what the route does.

    A freshly added object's lazy relationship raises `MissingGreenlet` when approval
    walks it, so `_owned` in `api/routes/imports.py` uses `selectinload`. Mirroring that
    here keeps the test on the same path production takes.
    """
    record = await extract_resume(
        session,
        user_id=user_id,
        filename="cv.pdf" if kind == "application/pdf" else "cv.docx",
        content_type=kind,
        data=data,
        completion=_Stub(),
    )
    await session.flush()
    reloaded = await session.scalar(
        select(ImportedResume)
        .where(ImportedResume.id == record.id)
        .options(selectinload(ImportedResume.items))
    )
    assert reloaded is not None
    return reloaded


@pytest.mark.asyncio
async def test_the_theme_is_staged_on_the_import(db_session: AsyncSession) -> None:
    """Written in the same transaction as the extraction it came from."""
    profile = await _user_with_profile(db_session)
    record = await _import(db_session, profile.user_id, _fixture_pdf(), "application/pdf")

    assert record.theme is not None, "no design was staged for a themed CV"
    theme = ResumeTheme.model_validate(record.theme)
    assert theme.font_family == "Poppins"
    assert theme.section_heading_color == "#00786C"


@pytest.mark.asyncio
async def test_approval_carries_the_theme_onto_the_master_resume(
    db_session: AsyncSession,
) -> None:
    """The hop that matters: after this the upload's bytes are unreachable."""
    profile = await _user_with_profile(db_session)
    record = await _import(db_session, profile.user_id, _fixture_pdf(), "application/pdf")

    master = await approve_import(db_session, imported_resume=record, profile_id=profile.id)
    await db_session.flush()

    assert master.theme is not None
    assert ResumeTheme.model_validate(master.theme).section_heading_color == "#00786C"


@pytest.mark.asyncio
async def test_a_docx_import_stages_no_theme_and_still_approves(
    db_session: AsyncSession,
) -> None:
    """No geometry is an ordinary outcome, not a failed import.

    The Master Resume is created with a NULL theme and the export renders the plain ATS
    template — exactly what every profile did before this existed.
    """
    profile = await _user_with_profile(db_session)
    record = await _import(db_session, profile.user_id, _DOCX, _DOCX_TYPE)

    assert record.theme is None

    master = await approve_import(db_session, imported_resume=record, profile_id=profile.id)
    await db_session.flush()
    assert master.theme is None


@pytest.mark.asyncio
async def test_a_second_import_does_not_overwrite_an_existing_theme(
    db_session: AsyncSession,
) -> None:
    """**The invariant that keeps an exported document from changing underneath itself.**

    A locked version re-renders from this row, so replacing the theme on a re-import
    would alter the bytes an `EXPORTED` document recorded a checksum over — the hazard
    that made role context a snapshot rather than a live read (FR-023). Drilled with a
    genuinely *different* design, so a no-op implementation cannot pass it.
    """
    profile = await _user_with_profile(db_session)
    first = await _import(db_session, profile.user_id, _fixture_pdf(), "application/pdf")
    master = await approve_import(db_session, imported_resume=first, profile_id=profile.id)
    await db_session.flush()
    original = dict(master.theme or {})
    assert original

    second = await _import(db_session, profile.user_id, _fixture_pdf(), "application/pdf")
    second.theme = {**original, "name_color": "#B3001B", "body_font_size_pt": 12.0}
    await approve_import(db_session, imported_resume=second, profile_id=profile.id)
    await db_session.flush()

    reread = await db_session.scalar(select(ResumeProfile).where(ResumeProfile.id == master.id))
    assert reread is not None
    assert reread.theme == original, "a later import replaced the design an export depends on"


@pytest.mark.asyncio
async def test_a_master_with_no_theme_gains_one_from_a_later_import(
    db_session: AsyncSession,
) -> None:
    """Write-once is not never-write — **while nothing depends on the rendering yet.**

    Someone whose first CV was a DOCX has no design; a later PDF should give them one.
    Nothing is overwritten, because there was nothing there, and no version built from
    this master has produced a document. The moment one has, the sibling test
    `test_a_later_import_cannot_change_what_an_exported_version_re_renders_to` takes over
    and the backfill is refused.
    """
    profile = await _user_with_profile(db_session)

    first = await _import(db_session, profile.user_id, _DOCX, _DOCX_TYPE)
    master = await approve_import(db_session, imported_resume=first, profile_id=profile.id)
    await db_session.flush()
    assert master.theme is None

    second = await _import(db_session, profile.user_id, _fixture_pdf(), "application/pdf")
    await approve_import(db_session, imported_resume=second, profile_id=profile.id)
    await db_session.flush()

    reread = await db_session.scalar(select(ResumeProfile).where(ResumeProfile.id == master.id))
    assert reread is not None and reread.theme is not None
    assert ResumeTheme.model_validate(reread.theme).font_family == "Poppins"


@pytest.mark.asyncio
async def test_the_export_renders_in_the_theme_the_version_was_built_from(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third hop: a stored design has to reach the renderer.

    Followed through `source_resume_profile_id` — the lineage the version already
    records — rather than through whichever master happens to exist now, so a document
    renders in the design it was created under.
    """
    from careerhq.application import export_resume as export_module
    from careerhq.application.export_resume import export_version
    from careerhq.application.tailor_resume import create_pending_version
    from careerhq.domain.models import (
        ProposalDecision,
        ResumeVersionItem,
        SourceKind,
        VersionStatus,
    )
    from tests.support.tailoring_fixtures import seed_tailorable

    seeded = await seed_tailorable(db_session, sub=f"sub-{uuid.uuid4()}", email="theme@example.com")
    themed = ResumeTheme(font_family="Poppins", name_color="#00786C").model_dump(mode="json")
    seeded.master.theme = themed
    await db_session.flush()

    version = await create_pending_version(db_session, seeded.application)
    db_session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.SUMMARY,
            position=0,
            original_text="Backend engineer with six years on payment platforms.",
            final_text="Backend engineer with six years on payment platforms.",
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    version.status = VersionStatus.READY
    await db_session.flush()

    seen: list[ResumeTheme | None] = []

    def _render(document: object, theme: ResumeTheme | None = None) -> bytes:
        seen.append(theme)
        return b"%PDF-1.7\nstub\n%%EOF\n"

    monkeypatch.setattr(export_module, "render_resume_pdf", _render)
    await export_version(db_session, version_id=version.id)

    assert seen and seen[0] is not None, "the export rendered on the plain template"
    assert seen[0].name_color == "#00786C"


@pytest.mark.asyncio
async def test_an_unthemed_profile_still_exports_on_the_plain_template(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The common case, and the one every profile predating this takes.

    Without this the previous test would pass against an implementation that always
    passed *something* — a gate with nothing to distinguish.
    """
    from careerhq.application import export_resume as export_module
    from careerhq.application.export_resume import export_version
    from careerhq.application.tailor_resume import create_pending_version
    from careerhq.domain.models import (
        ProposalDecision,
        ResumeVersionItem,
        SourceKind,
        VersionStatus,
    )
    from tests.support.tailoring_fixtures import seed_tailorable

    seeded = await seed_tailorable(db_session, sub=f"sub-{uuid.uuid4()}", email="plain@example.com")
    assert seeded.master.theme is None

    version = await create_pending_version(db_session, seeded.application)
    db_session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.SUMMARY,
            position=0,
            original_text="Backend engineer.",
            final_text="Backend engineer.",
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    version.status = VersionStatus.READY
    await db_session.flush()

    seen: list[ResumeTheme | None] = []

    def _render(document: object, theme: ResumeTheme | None = None) -> bytes:
        seen.append(theme)
        return b"%PDF-1.7\nstub\n%%EOF\n"

    monkeypatch.setattr(export_module, "render_resume_pdf", _render)
    await export_version(db_session, version_id=version.id)

    assert seen == [None]


@pytest.mark.asyncio
async def test_a_stored_theme_that_no_longer_validates_falls_back_to_plain(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed vocabulary that narrows later must not fail historical exports.

    A résumé somebody is waiting for is worse lost than plain, so an unreadable design is
    logged and skipped rather than raised.
    """
    from careerhq.application import export_resume as export_module
    from careerhq.application.export_resume import export_version
    from careerhq.application.tailor_resume import create_pending_version
    from careerhq.domain.models import (
        ProposalDecision,
        ResumeVersionItem,
        SourceKind,
        VersionStatus,
    )
    from tests.support.tailoring_fixtures import seed_tailorable

    seeded = await seed_tailorable(db_session, sub=f"sub-{uuid.uuid4()}", email="stale@example.com")
    seeded.master.theme = {"font_family": "Helvetica From The Future", "name_color": "purple"}
    await db_session.flush()

    version = await create_pending_version(db_session, seeded.application)
    db_session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.SUMMARY,
            position=0,
            original_text="Backend engineer.",
            final_text="Backend engineer.",
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    version.status = VersionStatus.READY
    await db_session.flush()

    seen: list[ResumeTheme | None] = []

    def _render(document: object, theme: ResumeTheme | None = None) -> bytes:
        seen.append(theme)
        return b"%PDF-1.7\nstub\n%%EOF\n"

    monkeypatch.setattr(export_module, "render_resume_pdf", _render)
    record = await export_version(db_session, version_id=version.id)

    assert seen == [None]
    assert record.checksum_sha256


@pytest.mark.asyncio
async def test_a_later_import_cannot_change_what_an_exported_version_re_renders_to(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The invariant, drilled through the exact sequence that broke it.**

    Export reads `ResumeProfile.theme` live — `ResumeVersion` carries no snapshot — and
    re-export is legitimate (`EXPORTABLE_STATUSES` includes `EXPORTED`). So filling a
    NULL theme after a document exists would change what a user gets when they
    re-download "the same version": a visibly different résumé from the one they sent.

        DOCX import (theme NULL) -> approve -> export V  (plain, checksum recorded)
        PDF import (theme found) -> approve              <- must NOT fill the theme
        re-export V                                       -> still plain

    The earlier rule only refused to *replace* a theme, and a test blessed the NULL case
    as "write-once is not never-write" — which is true only while nothing depends on the
    rendering yet.
    """
    from careerhq.application import export_resume as export_module
    from careerhq.application.export_resume import export_version
    from careerhq.application.tailor_resume import create_pending_version
    from careerhq.domain.models import (
        ProposalDecision,
        ResumeVersionItem,
        SourceKind,
        VersionStatus,
    )
    from tests.support.tailoring_fixtures import seed_tailorable

    seeded = await seed_tailorable(
        db_session, sub=f"sub-{uuid.uuid4()}", email="frozen@example.com"
    )
    assert seeded.master.theme is None, "the fixture must start with no design"

    version = await create_pending_version(db_session, seeded.application)
    db_session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.SUMMARY,
            position=0,
            original_text="Backend engineer with six years on payment platforms.",
            final_text="Backend engineer with six years on payment platforms.",
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    version.status = VersionStatus.READY
    await db_session.flush()

    seen: list[ResumeTheme | None] = []

    def _render(document: object, theme: ResumeTheme | None = None) -> bytes:
        seen.append(theme)
        return b"%PDF-1.7\nstub\n%%EOF\n"

    monkeypatch.setattr(export_module, "render_resume_pdf", _render)

    # 1. The document exists, rendered on the plain template.
    await export_version(db_session, version_id=version.id)
    assert seen == [None]

    # 2. A themed PDF is imported and approved afterwards.
    themed_import = await _import(db_session, seeded.user.id, _fixture_pdf(), "application/pdf")
    assert themed_import.theme is not None, "the fixture PDF must yield a design to stage"
    await approve_import(db_session, imported_resume=themed_import, profile_id=seeded.profile.id)
    await db_session.flush()

    # 3. The master keeps no design, because a document already depends on the rendering.
    reread = await db_session.scalar(
        select(ResumeProfile).where(ResumeProfile.id == seeded.master.id)
    )
    assert reread is not None
    assert reread.theme is None, (
        "a later import filled the theme of a master whose version has already been "
        "exported; re-exporting that version would now produce a different document"
    )

    # 4. And the re-export is still the document the user already has.
    version.status = VersionStatus.EXPORTED
    await db_session.flush()
    await export_version(db_session, version_id=version.id)
    assert seen == [None, None], "the re-export rendered in a design the first export did not use"
