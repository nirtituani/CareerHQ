"""Applications — record a job, list them, move one through its statuses.

Endpoints per `specs/003-data-foundation/contracts/http-api.md`. The same two
rules that run through `imports.py` run through here:

* **Ownership comes from the session.** No route accepts a user id, and another
  user's application is **404 rather than 403** (FR-019), so the endpoint does
  not confirm that the id names anything.
* **Nothing here carries a `rejected` boolean** (FR-016). Rejection travels as a
  `normalized_status` value. An API field is exactly how a removed column grows
  back, which is why the contract says so explicitly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from careerhq.api.deps import CompletionClient, CurrentUser, DbSession
from careerhq.application.extract_job import extract_job_from_text, extract_job_from_url
from careerhq.application.record_application import (
    apply_changes,
    record_application,
)
from careerhq.domain.models import Application, NormalizedStatus, normalize_status
from careerhq.infrastructure.jobs import JobFetchError

router = APIRouter(prefix="/applications", tags=["applications"])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _application_out(record: Application) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "company": {
            "id": str(record.company.id),
            "name": record.company.name,
            # docs/09 §6.2's logo column resolves from this.
            "domain": record.company.domain,
        },
        "job_title": record.job_title,
        "location": record.location,
        "job_description": record.job_description,
        "job_url": record.job_url,
        "job_description_url": record.job_description_url,
        # Both, always: the label is what the user calls it, the normalized
        # value is what the table filters and the dashboard counts (FR-013).
        "status": record.status,
        "normalized_status": record.normalized_status,
        "date_added": _iso(record.date_added),
        "date_applied": _iso(record.date_applied),
        "source": record.source,
        "salary_text": record.salary_text,
        "imported_match_rating": record.imported_match_rating,
        "contact_name": record.contact_name,
        "contact_email": record.contact_email,
        "notes": record.notes,
        "import_source": record.import_source,
        "archived_at": _iso(record.archived_at),
        "status_history": [
            {
                "from_status": row.from_status,
                "to_status": row.to_status,
                "normalized_to_status": row.normalized_to_status,
                "changed_at": _iso(row.changed_at),
                "note": row.note,
            }
            for row in record.status_history
        ],
    }


async def _owned(session: DbSession, user: CurrentUser, application_id: uuid.UUID) -> Application:
    """Fetch an application the session user owns, or 404.

    404 rather than 403 for someone else's: a 403 confirms the resource exists,
    which is the disclosure FR-019 is about.
    """
    record = await session.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return record


@router.post("", status_code=status.HTTP_201_CREATED, summary="Record a job")
async def create_application(
    body: dict[str, Any], session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Create with company, title, and job description (FR-010).

    The company is resolved or created by normalized name (C2). Valid with no
    submitted resume (FR-011).
    """
    if not (body.get("company") or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A company name is required.",
        )
    if not (body.get("job_title") or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A job title is required.",
        )

    record = await record_application(session, user_id=user.id, data=body)
    await session.commit()
    await session.refresh(record)
    return _application_out(record)


@router.get("", summary="The session user's applications")
async def list_applications(session: DbSession, user: CurrentUser) -> dict[str, Any]:
    records = (
        await session.scalars(
            select(Application)
            .where(Application.user_id == user.id)
            .order_by(Application.date_added.desc())
        )
    ).all()
    return {"applications": [_application_out(record) for record in records]}


@router.get("/{application_id}", summary="One application")
async def get_application(
    application_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    return _application_out(await _owned(session, user, application_id))


@router.patch("/{application_id}", summary="Update, moving status if it changed")
async def patch_application(
    application_id: uuid.UUID, body: dict[str, Any], session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Any status change writes a history row (FR-012).

    `normalized_status` in the body is ignored — it is derived from the label
    (FR-013), because a client-settable normalized status is a second source of
    truth for the same fact.
    """
    record = await _owned(session, user, application_id)
    apply_changes(record, body)
    await session.commit()
    await session.refresh(record)
    return _application_out(record)


@router.post("/{application_id}/unreject", summary="Undo a rejection")
async def unreject(
    application_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Restore the status the application held before it was rejected.

    The source app cleared a boolean, which was easy precisely because the
    status underneath had stopped meaning anything. Here the previous label is
    read back out of the append-only history — which is what a timeline is for —
    and the undo is *appended* rather than erasing the rejection. What happened
    still happened (Constitution IV).
    """
    record = await _owned(session, user, application_id)

    previous = next(
        (
            row.to_status
            for row in reversed(record.status_history)
            if normalize_status(row.to_status) is not NormalizedStatus.REJECTED
        ),
        None,
    )
    if previous is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This application has never held another status.",
        )

    apply_changes(record, {"status": previous})
    await session.commit()
    await session.refresh(record)
    return _application_out(record)


@router.delete(
    "/{application_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an application"
)
async def delete_application(
    application_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Response:
    """Remove the record and its history.

    Constitution IV forbids *rewriting* a timeline, not a person deleting their
    own record outright — the guarantee is that history cannot be edited to say
    something different, and a deleted application asserts nothing at all.
    """
    record = await _owned(session, user, application_id)
    await session.delete(record)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/extract", summary="Read a posting into form fields — saves nothing")
async def extract_posting(
    body: dict[str, Any],
    user: CurrentUser,
    completion: CompletionClient,
) -> dict[str, Any]:
    """Turn a job URL, or pasted posting text, into fields for the form.

    **This creates nothing.** The result populates the Add Application form and
    waits for the person to confirm it (Principle II) — the same shape as the CV
    import, where a model proposes and a human approves. An endpoint that saved
    the application here would be an unreviewed extraction writing to the
    profile's neighbour.

    Authenticated deliberately: an unauthenticated fetcher is an open proxy with
    this deployment's IP address on it.

    A URL that cannot be fetched is a **400 carrying an explanation**, because
    the interface turns it into a specific next step — paste the text instead.
    Most large job boards refuse automated requests outright, so this is an
    ordinary outcome rather than an error in this system.
    """
    url = (body.get("url") or "").strip()
    text_input = (body.get("text") or "").strip()

    if not url and not text_input:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide a job URL or paste the posting text.",
        )

    try:
        result = (
            await extract_job_from_url(url, completion=completion)
            if url
            else await extract_job_from_text(text_input, completion=completion)
        )
    except JobFetchError as exc:
        # The message is written for the person reading it and names no internal
        # address — the SSRF guard's refusal must not double as a network map.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "posting": result.posting.model_dump(),
        # "the employer published this" and "a model read the page" deserve
        # different trust, and the form marks the difference.
        "provenance": result.provenance,
        "usage": (
            {
                "model": result.usage.model,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cost": str(result.usage.cost),
                "is_fixture": result.usage.is_fixture,
            }
            if result.usage
            else None
        ),
    }
