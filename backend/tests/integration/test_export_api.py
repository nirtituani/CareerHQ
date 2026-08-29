"""T037 — the export endpoint, and the download that makes FR-015 true.

**Two routes, because they are two different things.**

- `POST /api/versions/{id}/export` is the workflow operation: it refuses, renders, stores,
  records and transitions. It mirrors `POST .../approve` — the closest existing route —
  and returns the version representation the client already knows how to render.
- `GET /api/versions/{id}/document` serves the stored bytes. Separate so that *downloading
  again* is not *exporting again*: re-export is legitimate (`ExportedDocument` has no
  unique constraint) but it writes a new row and a new object, and a person clicking
  "download" twice should not accumulate export records.

**The route owns none of the rules.** `ensure_exportable` decides refusal (T033) and
`export_version` owns render → store → record → transition (T036). The route translates
`ExportRefused` into **409**, the status `approve` already uses for a wrong-state request,
and commits — the transaction boundary every other use case here follows.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from careerhq.application import export_resume
from careerhq.application.tailor_resume import create_pending_version
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

_BULLET = "Owned the settlement service end to end, from schema to on-call."


def _as(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    client.cookies.set(SESSION_COOKIE, create_session_token(str(user.id)))
    return client


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Bytes go to a dict, and are read back from it.

    Held rather than discarded so the download route is tested against what the export
    actually stored — a stub that threw them away would let the two halves disagree about
    the key and still pass. The same reasoning as the import-flow fixture.
    """
    stored: dict[str, bytes] = {}

    async def _put(key: str, data: bytes, *, content_type: str) -> None:
        stored[key] = data

    async def _get(key: str) -> bytes:
        return stored[key]

    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "get_object", _get)
    return stored


async def _ready_version(
    session: AsyncSession, *, sub: str, status: VersionStatus = VersionStatus.READY
) -> tuple[User, ResumeVersion]:
    seeded = await seed_tailorable(session, sub=sub, email=f"{sub}@example.com")
    version = await create_pending_version(session, seeded.application)
    session.add(
        ResumeVersionItem(
            resume_version_id=version.id,
            source_kind=SourceKind.EXPERIENCE_BULLET,
            position=0,
            original_text=_BULLET,
            final_text=_BULLET,
            decision=ProposalDecision.ACCEPTED,
            included=True,
        )
    )
    version.status = status
    await session.commit()
    return seeded.user, version


async def test_exporting_an_approved_version_returns_the_updated_version(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
) -> None:
    """The contract: 200, the version at `exported`, and the export's own facts."""
    user, version = await _ready_version(db_session, sub="api-export")

    response = await _as(client, user).post(f"/api/versions/{version.id}/export")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "exported"
    assert body["id"] == str(version.id)

    export = body["export"]
    assert len(export["checksum_sha256"]) == 64
    assert export["byte_size"] > 0
    assert export["exported_at"]
    assert "document_storage_key" not in export, (
        "the storage key is an internal address; the document is reached by its route"
    )

    async with session_factory() as check:
        rows = await check.execute(
            sa.select(ExportedDocument).where(ExportedDocument.resume_version_id == version.id)
        )
        records = list(rows.scalars())
    assert len(records) == 1
    assert records[0].checksum_sha256 == export["checksum_sha256"]


async def test_the_endpoint_delegates_to_the_use_case(
    client: Any,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_storage: dict[str, bytes],
) -> None:
    """The route must call `export_version`, not reproduce render/store/checksum.

    Asserted by replacing the use case: if the route still exports, it is doing the work
    itself and the T036 guarantees — ordering, checksum source, storage-before-record —
    apply to code nobody tested.
    """
    user, version = await _ready_version(db_session, sub="api-delegate")
    calls: list[uuid.UUID] = []

    async def _fake(session: AsyncSession, *, version_id: uuid.UUID) -> object:
        calls.append(version_id)
        raise RuntimeError("stand-in")

    monkeypatch.setattr(export_resume, "export_version", _fake)
    # The route imports the name, so patch where it is looked up as well.
    import careerhq.api.routes.tailoring as tailoring_routes

    monkeypatch.setattr(tailoring_routes, "export_version", _fake)

    with pytest.raises(RuntimeError, match="stand-in"):
        await _as(client, user).post(f"/api/versions/{version.id}/export")

    assert calls == [version.id], "the route did not delegate to the export use case"


@pytest.mark.parametrize(
    "status", [VersionStatus.DRAFT, VersionStatus.AWAITING_APPROVAL, VersionStatus.SUBMITTED]
)
async def test_a_version_that_may_not_be_exported_is_refused_with_409(
    client: Any,
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    status: VersionStatus,
) -> None:
    """FR-016 at the surface. 409, the status `approve` already uses for a wrong state."""
    user, version = await _ready_version(db_session, sub=f"api-{status.value[:6]}", status=status)

    response = await _as(client, user).post(f"/api/versions/{version.id}/export")

    assert response.status_code == 409, response.text
    assert response.json()["detail"], "the refusal carries no reason"
    assert fake_storage == {}, "a refused export still wrote bytes"


async def test_a_version_someone_else_owns_is_not_found(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """404 rather than 403: a 403 confirms the id names something."""
    _, version = await _ready_version(db_session, sub="api-owner")
    intruder, _ = await _ready_version(db_session, sub="api-intruder")

    response = await _as(client, intruder).post(f"/api/versions/{version.id}/export")

    assert response.status_code == 404


async def test_another_owner_cannot_download_the_document(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """**The drill found this missing.** Ownership was asserted on the export but not on
    the download, and removing `_owned_version` from the download route changed nothing.

    It is the more serious of the two: the POST only refuses an action, while the GET
    hands over somebody's résumé — name, email, phone and employment history — to anyone
    who can guess a version id.
    """
    owner, version = await _ready_version(db_session, sub="dl-owner")
    intruder, _ = await _ready_version(db_session, sub="dl-intruder")
    await _as(client, owner).post(f"/api/versions/{version.id}/export")

    response = await _as(client, intruder).get(f"/api/versions/{version.id}/document")

    assert response.status_code == 404, response.text
    assert b"%PDF" not in response.content


async def test_a_missing_version_is_a_404(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    user, _ = await _ready_version(db_session, sub="api-missing")

    response = await _as(client, user).post(f"/api/versions/{uuid.uuid4()}/export")

    assert response.status_code == 404


async def test_the_document_route_serves_the_exported_bytes(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """FR-015: the person gets the PDF. Served from storage, never re-rendered."""
    user, version = await _ready_version(db_session, sub="api-download")
    await _as(client, user).post(f"/api/versions/{version.id}/export")

    response = await _as(client, user).get(f"/api/versions/{version.id}/document")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content == next(iter(fake_storage.values()))


async def test_downloading_before_any_export_is_a_404(
    client: Any, db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """Nothing has been rendered, so there is nothing to serve — and the download route
    must not quietly export on the user's behalf."""
    user, version = await _ready_version(db_session, sub="api-nodoc")

    response = await _as(client, user).get(f"/api/versions/{version.id}/document")

    assert response.status_code == 404
    assert fake_storage == {}, "the download route exported something"


async def test_re_export_is_allowed_and_the_download_serves_the_latest(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict[str, bytes],
) -> None:
    """`EXPORTED` stays exportable, and each export is its own object."""
    user, version = await _ready_version(db_session, sub="api-reexport")

    first = await _as(client, user).post(f"/api/versions/{version.id}/export")
    second = await _as(client, user).post(f"/api/versions/{version.id}/export")

    assert first.status_code == 200 and second.status_code == 200
    assert len(fake_storage) == 2, "the second export overwrote the first object"

    async with session_factory() as check:
        rows = await check.execute(
            sa.select(ExportedDocument).where(ExportedDocument.resume_version_id == version.id)
        )
        assert len(list(rows.scalars())) == 2


async def test_a_storage_failure_is_not_reported_as_a_successful_export(
    client: Any,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_storage: dict[str, bytes],
) -> None:
    """The failure must not leave a record, a status change, or a 200."""
    user, version = await _ready_version(db_session, sub="api-storagefail")

    async def _boom(key: str, data: bytes, *, content_type: str) -> None:
        raise RuntimeError("object storage is unreachable")

    monkeypatch.setattr(storage, "put_object", _boom)

    with pytest.raises(RuntimeError, match="object storage"):
        await _as(client, user).post(f"/api/versions/{version.id}/export")

    async with session_factory() as check:
        rows = await check.execute(
            sa.select(ExportedDocument).where(ExportedDocument.resume_version_id == version.id)
        )
        assert list(rows.scalars()) == []
        fresh = await check.get(ResumeVersion, version.id)
        assert fresh is not None
        assert fresh.status == VersionStatus.READY, "the version moved on despite the failure"
