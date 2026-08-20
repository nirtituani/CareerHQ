"""CV import: upload, review, approve.

Endpoints per `specs/003-data-foundation/contracts/http-api.md`. Two rules run
through all of them:

* **Ownership comes from the session.** No route accepts a user or profile id
  (FR-019), and another user's import is **404 rather than 403**, so the
  endpoint does not confirm that it exists.
* **Nothing reaches the profile except through approve.** Upload stages; approve
  writes.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from careerhq.api.deps import CompletionClient, CurrentUser, DbSession, get_current_profile
from careerhq.application.approve_import import (
    AlreadyApprovedError,
    NothingAcceptedError,
    approve_import,
    duplicate_key,
    existing_keys,
)
from careerhq.application.extract_resume import ExtractionProducedNothingError, extract_resume
from careerhq.domain.models import (
    ExtractionItem,
    ImportedResume,
    ItemDecision,
    ProfessionalProfile,
    Source,
)
from careerhq.infrastructure import storage
from careerhq.infrastructure.documents import UnsupportedDocumentError

router = APIRouter(prefix="/imports", tags=["imports"])

#: Refused before the file is read into memory in full.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _item_out(item: ExtractionItem, existing: set[str]) -> dict[str, Any]:
    key = duplicate_key(item.kind, dict(item.payload))
    return {
        # Whether the profile already holds this fact. On a second import most
        # items are already there, and the few that are not are the only ones
        # worth the reviewer's attention — showing thirty-nine rows they have
        # approved once already is how a review stops being read.
        "already_present": key is not None and key in existing,
        "id": str(item.id),
        "kind": item.kind,
        "payload": item.payload,
        "confidence": item.confidence,
        "source": item.source,
        "decision": item.decision,
        "ordinal": item.ordinal,
        "parent_id": str(item.parent_id) if item.parent_id else None,
    }


def _import_out(record: ImportedResume, existing: set[str]) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "filename": record.filename,
        "status": record.status,
        "extraction_error": record.extraction_error,
        # Surfaced so the interface can label the whole review as fixture data.
        # Canned content mistaken for a real extraction is the one unacceptable
        # outcome of having a fixture mode at all.
        "is_fixture": record.is_fixture,
        "model": record.model,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "items": [_item_out(item, existing) for item in record.items],
    }


async def _owned(session: DbSession, user: CurrentUser, import_id: uuid.UUID) -> ImportedResume:
    """Fetch an import the session user owns, or 404.

    404 rather than 403 for someone else's: a 403 confirms the resource exists,
    which is a disclosure in itself.
    """
    record = await session.scalar(
        select(ImportedResume)
        .where(ImportedResume.id == import_id, ImportedResume.user_id == user.id)
        .options(selectinload(ImportedResume.items))
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found.")
    return record


@router.post("/resume", status_code=status.HTTP_202_ACCEPTED, summary="Upload a CV")
async def upload_resume(
    session: DbSession,
    user: CurrentUser,
    completion: CompletionClient,
    profile: Annotated[ProfessionalProfile, Depends(get_current_profile)],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Stage an uploaded CV for review. **Writes nothing to the profile.**"""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="That file is larger than 10 MB.",
        )

    try:
        record = await extract_resume(
            session,
            user_id=user.id,
            filename=file.filename or "cv",
            content_type=file.content_type or "application/octet-stream",
            data=data,
            completion=completion,
        )
    except UnsupportedDocumentError as exc:
        # Nothing was stored, so nothing to roll back — but be explicit, since a
        # refused upload must leave no trace (FR-001).
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ExtractionProducedNothingError as exc:
        # The failed import IS committed: the user should be able to see that
        # their upload arrived and why it did not work, rather than watching it
        # vanish (FR-008).
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    await session.commit()
    await session.refresh(record, attribute_names=["items"])
    return _import_out(record, await existing_keys(session, profile.id))


@router.get("/{import_id}", summary="A staged import, for review")
async def get_import(
    import_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    profile: Annotated[ProfessionalProfile, Depends(get_current_profile)],
) -> dict[str, Any]:
    record = await _owned(session, user, import_id)
    return _import_out(record, await existing_keys(session, profile.id))


@router.get("", summary="The caller's uploads, newest first")
async def list_imports(session: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Where the profile's facts came from.

    The profile shows facts without saying which document produced them,
    and a person may have imported more than once — the profile is a merge.
    This is how the viewer knows which upload to render.

    `storage_key` is deliberately absent: it is an internal address, and
    the file is reached through the route that checks ownership rather than
    by naming a bucket location.
    """
    records = (
        await session.scalars(
            select(ImportedResume)
            .where(ImportedResume.user_id == user.id)
            .order_by(ImportedResume.created_at.desc())
        )
    ).all()

    return {
        "imports": [
            {
                "id": str(record.id),
                "filename": record.filename,
                "content_type": record.content_type,
                "byte_size": record.byte_size,
                "status": record.status,
                "is_fixture": record.is_fixture,
                "created_at": record.created_at.isoformat(),
                "approved_at": (record.approved_at.isoformat() if record.approved_at else None),
            }
            for record in records
        ]
    }


@router.get("/{import_id}/file", summary="The retained original, as uploaded")
async def read_original(import_id: uuid.UUID, session: DbSession, user: CurrentUser) -> Response:
    """Serve the uploaded CV back to the person who uploaded it.

    Three things are deliberate here.

    **The stored content type is not echoed back.** It came from the
    upload, so it is attacker-controlled, and serving arbitrary content
    inline from our own origin is an XSS vector — a file declared
    `text/html` would run as a same-origin page. Only PDF renders inline;
    anything else is sent as an attachment.

    **`X-Frame-Options` is narrowed to `SAMEORIGIN`.**
    `SecurityHeadersMiddleware` sets `DENY` on every response, which is the
    right default and wrong for the one response the profile renders in a
    frame. The middleware uses `setdefault`, so a route may narrow it —
    better than weakening the default everywhere for one viewer.

    **The filename is quoted and stripped of quotes and control
    characters**, because it is user-supplied and goes into a header.
    """
    record = await _owned(session, user, import_id)

    data = await storage.get_object(record.storage_key)

    inline = record.content_type == "application/pdf"
    safe_name = re.sub(r"[^\w.\- ]", "_", record.filename)[:120] or "cv"
    disposition = "inline" if inline else "attachment"

    return Response(
        content=data,
        media_type="application/pdf" if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe_name}"',
            "X-Frame-Options": "SAMEORIGIN",
            # Never cached by a shared proxy: this is one person's CV.
            "Cache-Control": "private, no-store",
        },
    )


@router.patch("/{import_id}/items/{item_id}", summary="Correct, accept or discard one item")
async def patch_item(
    import_id: uuid.UUID,
    item_id: uuid.UUID,
    body: dict[str, Any],
    session: DbSession,
    user: CurrentUser,
    profile: Annotated[ProfessionalProfile, Depends(get_current_profile)],
) -> dict[str, Any]:
    """Update one staged item.

    Changing the payload marks it `user_corrected` (FR-004): the distinction
    between what the model produced and what the person confirmed has to survive
    into the profile, so it is recorded the moment it happens.
    """
    record = await _owned(session, user, import_id)
    item = next((i for i in record.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")

    if "payload" in body:
        item.payload = body["payload"]
        item.source = Source.USER_CORRECTED
    if "decision" in body:
        item.decision = ItemDecision(body["decision"])

    await session.commit()
    return _item_out(item, await existing_keys(session, profile.id))


@router.post("/{import_id}/approve", summary="Approve — the only path that writes the profile")
async def approve(
    import_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    profile: Annotated[ProfessionalProfile, Depends(get_current_profile)],
) -> dict[str, Any]:
    record = await _owned(session, user, import_id)

    try:
        master = await approve_import(session, imported_resume=record, profile_id=profile.id)
    except AlreadyApprovedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except NothingAcceptedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    await session.commit()
    return {"master_resume_id": str(master.id), "status": record.status}


@router.delete(
    "/{import_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Discard a staged import"
)
async def discard(import_id: uuid.UUID, session: DbSession, user: CurrentUser) -> Response:
    """Abandon a review. The profile is untouched (FR-007)."""
    record = await _owned(session, user, import_id)
    await session.delete(record)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
