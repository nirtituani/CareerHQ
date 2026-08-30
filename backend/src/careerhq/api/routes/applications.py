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

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from careerhq.api.deps import CompletionClient, CurrentUser, DbSession
from careerhq.api.routes.imports import MAX_UPLOAD_BYTES
from careerhq.api.routes.tailoring import submission_out
from careerhq.application.analyze_match import (
    create_pending_analysis,
    is_abandoned,
    run_analysis,
)
from careerhq.application.extract_job import extract_job_from_text, extract_job_from_url
from careerhq.application.import_jobtracker import import_jobtracker
from careerhq.application.match_criteria import CREDIT, Judged, cap_bit, caps_band
from careerhq.application.ports import StructuredCompletion
from careerhq.application.record_application import (
    apply_changes,
    record_application,
)
from careerhq.application.scoreability import scoreable_posting
from careerhq.application.submissions import submission_for
from careerhq.domain.models import (
    Application,
    MatchAnalysis,
    MatchRequirement,
    MatchStatus,
    NormalizedStatus,
    ProfessionalProfile,
    normalize_status,
)
from careerhq.infrastructure.database import get_session_factory
from careerhq.infrastructure.jobs import JobFetchError

router = APIRouter(prefix="/applications", tags=["applications"])
logger = logging.getLogger("careerhq.applications")


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
        # `null` and `[]` are different facts and must survive the API: `null`
        # means no posting was ever captured (a row written before slice 004),
        # `[]` means the posting was read and stated none. Collapsing them here
        # loses the only thing telling them apart (research.md R1).
        "requirements": record.requirements,
        # Whether there is posting content the analysis would actually read.
        # Computed here so the rule has one implementation: deriving it in the
        # browser would put a copy of `scoreable_posting` where nobody would
        # think to keep it in step.
        "is_scoreable": scoreable_posting(record) is not None,
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
    body: dict[str, Any],
    background: BackgroundTasks,
    session: DbSession,
    user: CurrentUser,
    completion: CompletionClient,
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

    # Reserved **in the same transaction as the application** (FR-005), so the
    # interface has something to show a spinner against and a failure has
    # somewhere to land. `None` when there is nothing to score against, which is
    # ordinary rather than an error (FR-006).
    analysis = await create_pending_analysis(session, record)
    await session.commit()
    await session.refresh(record)

    # Returns immediately; the score arrives seconds later (FR-004). Saving a
    # job is the step a person repeats, and is the worst place to spend twelve
    # seconds.
    if analysis is not None:
        background.add_task(_score_in_background, analysis.id, completion)

    state = "running" if analysis else "nothing_to_score"
    return _application_out(record) | {"match": {"state": state}}


@router.get("", summary="The session user's applications")
async def list_applications(session: DbSession, user: CurrentUser) -> dict[str, Any]:
    records = (
        await session.scalars(
            select(Application)
            .where(Application.user_id == user.id)
            .order_by(Application.date_added.desc())
        )
    ).all()

    # One join via the pointer, not one query per row.
    current = {
        analysis.id: analysis
        for analysis in await session.scalars(
            select(MatchAnalysis).where(
                MatchAnalysis.id.in_(
                    [r.current_match_analysis_id for r in records if r.current_match_analysis_id]
                )
            )
        )
    }

    out: list[dict[str, Any]] = []
    for record in records:
        analysis = current.get(record.current_match_analysis_id or uuid.uuid4())
        if analysis is None and record.requirements:
            analysis = await _latest_analysis(session, record)
        out.append(
            _application_out(record)
            | {
                "match": {
                    "state": _state_of(record, analysis),
                    # Enough for the Match column; the tab fetches the rest.
                    "band": analysis.band if analysis else None,
                    "overall_score": analysis.overall_score if analysis else None,
                }
            }
        )
    return {"applications": out}


@router.post("/import/jobtracker", summary="Import a JobTracker export")
async def import_jobtracker_export(
    session: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Import a JobTracker CSV export as this user's history (FR-015, D2).

    **Declared before the `/{application_id}` routes**, so `import` can never be read as an
    application id. Nothing currently collides — no `POST /{application_id}` exists — but the
    ordering is the cheap half of that guarantee and the collision would arrive as a confusing
    422 about a malformed UUID.

    **Ownership comes from the session, and the file's own `user_id` column is discarded**
    (FR-019). A JobTracker export carries the id of whoever exported it; honouring that would
    let anyone import rows attributed to another account, which is exactly the vulnerability
    the rule exists to prevent. The importer never represents that field at all.

    **Re-running is safe and is not an error.** Rows already imported are reported as
    `skipped`, refused by C3 rather than by a check that could be raced. A person who is unsure
    whether their upload worked should be able to press it again, and the honest answer is a
    report saying nothing new arrived.

    **The whole import commits or none of it does** (FR-023). Rows are classified before the
    transaction touches anything, so an unreadable row is reported while the rest still land —
    and a failure anywhere leaves no half-imported history behind.
    """
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="That file is larger than 10 MB.",
        )

    # **Read before any rollback below, and that is not tidiness.** `session.rollback()`
    # expires every loaded object, so `user.id` afterwards is a lazy refresh — synchronous IO
    # that async SQLAlchemy answers with `MissingGreenlet`. The handler would then raise while
    # handling the failure and the caller would get a 500 carrying the original driver message,
    # which is precisely the disclosure the handler exists to prevent.
    owner_id = user.id

    try:
        report = await import_jobtracker(session, user_id=owner_id, data=data)
    except ValueError as exc:
        # Nothing was written — the file is refused before the first row is examined — but the
        # rollback is explicit, because a refused upload must leave no trace. The message is
        # ours and names only the source's own column names, the same judgement `/extract`
        # makes when it hands a `JobFetchError` to the browser.
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        # C3 refused a row the pre-check believed was new, which means a second import of the
        # same file is in flight. **The detail goes to the log and the type goes to the
        # browser**: a driver's unique-violation text names the constraint, the table and the
        # values. Re-running once the other import finishes reports everything as skipped.
        await session.rollback()
        logger.warning(
            "jobtracker import conflicted with a concurrent import",
            extra={"user_id": str(owner_id), "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An import of this file is already running. Try again in a moment.",
        ) from exc

    await session.commit()

    return {
        "imported": report.imported,
        "skipped": report.skipped,
        "rejected": [
            {"source_id": rejection.source_id, "reason": rejection.reason}
            for rejection in report.rejected
        ],
        # Rows that imported but need a person's eye: an unfamiliar status, a date nobody could
        # read. Carried separately from `rejected` because the row *is* in the database — a
        # report that conflated them would send someone looking for history that is already there.
        "notices": [
            {"source_id": notice.source_id, "message": notice.message} for notice in report.notices
        ],
    }


@router.get("/{application_id}", summary="One application")
async def get_application(
    application_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """One application, and the résumé it sent if it sent one (FR-024).

    **Here and not on the list**, which renders every application a person has: the
    reference is a per-row query, and *"given an application, when I **inspect** it"* is
    the scenario the requirement states.

    **`submission_for` answers it**, rather than a query written a second time. The wrong
    second answer is always available and always plausible — the latest version, the
    latest export, the master résumé — and each would name a document nobody received
    (`docs/03` §12.2). `null` is the truthful answer for an application that sent nothing
    through CareerHQ, which every imported row has not.

    Ownership is settled by `_owned` before anything about a submission is read.
    """
    record = await _owned(session, user, application_id)
    body = _application_out(record)
    submission = await submission_for(session, application_id=record.id)
    body["submission"] = submission_out(submission) if submission else None
    return body


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
            # `!=` rather than `is not`: safe here because `normalize_status`
            # returns an enum member, but these columns are strings and the
            # identity comparison is one refactor away from silently never
            # matching. See the note in `analyze_match.run_analysis`.
            if normalize_status(row.to_status) != NormalizedStatus.REJECTED
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


def _state_of(record: Application, analysis: MatchAnalysis | None) -> str:
    """The four states, decided here rather than by each client.

    A client working out that "no score means it failed" is the conflation
    FR-022 forbids, and one implementation beats one per surface.
    """
    if not record.requirements:
        return "nothing_to_score"
    if analysis is None:
        return "nothing_to_score"
    if analysis.status == MatchStatus.READY:
        # **A zero with nothing behind it is not a score.** The spec's own edge
        # case says a posting that yielded no requirements is "nothing to score
        # against, not a failure and not a zero", and that was never
        # implemented — so an analysis run against an empty posting rendered as
        # `0/100 · low_probability`, which reads as a verdict about the person.
        #
        # Deciding it here rather than in the interface also covers rows written
        # before the guard existed, without editing any of them.
        if not analysis.requirements:
            return "nothing_to_score"
        return "ready"
    if analysis.status == MatchStatus.FAILED:
        return "failed"
    # A run nothing will finish reads as failed rather than spinning
    # forever, so the interface invites the re-run that recovers it.
    if is_abandoned(analysis):
        return "failed"
    return "running"


async def _latest_analysis(session: DbSession, record: Application) -> MatchAnalysis | None:
    """What to report about this job's scoring, in order of what matters.

    **A run in flight comes first.** `run_analysis` writes
    `current_match_analysis_id` only on success and last of all — deliberately,
    so a failed run leaves the previous score standing (FR-015). But preferring
    that pointer *unconditionally* meant that for the whole duration of a re-run
    the endpoint reported the previous analysis, and the previous analysis is
    never `running`. The interface polls only while the state is `running`, so it
    stopped on its first poll and the result arrived unobserved.

    Measured on a real run: a click at 07:03:52 started a completion that
    finished at 07:04:16 with 84/strong. Two polls, at 07:03:54 and 07:04:03,
    both read the old row; nothing was watching thirteen seconds later. This was
    never specific to any one job — every re-run of an already-scored job had it,
    showing a stale score instead of a stale "not scored".

    **Only while it is plausibly in flight.** A run that stops without finishing
    stays `pending` until the reaper marks it failed on the next scoring request.
    Returning it here would replace a good score with `failed` for a run nobody
    will finish, which is the FR-015 guarantee lost by another route — so an
    abandoned row falls through to the pointer like a failed one.

    Then the pointer, which only ever names a `ready` row, then the newest row
    for a job that has never had one.
    """
    in_flight = await session.scalar(
        select(MatchAnalysis)
        .where(
            MatchAnalysis.application_id == record.id,
            MatchAnalysis.status == MatchStatus.PENDING,
        )
        .order_by(MatchAnalysis.created_at.desc())
        .limit(1)
    )
    if in_flight is not None and not is_abandoned(in_flight):
        return in_flight

    if record.current_match_analysis_id is not None:
        current: MatchAnalysis | None = await session.get(
            MatchAnalysis, record.current_match_analysis_id
        )
        return current
    latest: MatchAnalysis | None = await session.scalar(
        select(MatchAnalysis)
        .where(MatchAnalysis.application_id == record.id)
        .order_by(MatchAnalysis.created_at.desc())
        .limit(1)
    )
    return latest


def _capped_by(analysis: MatchAnalysis, rows: list[MatchRequirement]) -> dict[str, Any] | None:
    """The requirement that held the band below its arithmetic, if one did.

    Only when the cap actually *bit*. A score already inside the ceiling band
    reaches it with or without an unmet critical requirement, and naming one
    there would claim a causation that did not happen.
    """
    if analysis.overall_score is None:
        return None

    judged = [Judged(kind=row.kind, verdict=row.verdict, importance=row.importance) for row in rows]
    if not cap_bit(analysis.overall_score, requirements=judged):
        return None

    return next(
        (
            {"ordinal": row.ordinal, "text": row.text_, "importance": row.importance}
            for row in rows
            if caps_band(row.kind, row.verdict, row.importance)
        ),
        None,
    )


def _analysis_out(analysis: MatchAnalysis | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    rows = list(analysis.requirements)
    return {
        "id": str(analysis.id),
        # The band is what the interface shows; the score is retained for
        # sorting and calibration and must not be rendered bare (FR-001a).
        "band": analysis.band,
        "overall_score": analysis.overall_score,
        # What each verdict earns, so the total is arithmetic a person can check
        # against the rows below it rather than a number they must take on
        # trust. The breakdown is the requirement list itself (research.md R11).
        "credit": {verdict.value: share for verdict, share in CREDIT.items()},
        # The band is not the score bucketed. When an important unmet
        # requirement holds it down, say which one -- otherwise the label and
        # the number disagree on screen and it reads as a bug.
        "capped_by": _capped_by(analysis, rows),
        "verdict": analysis.verdict,
        "criteria_version": analysis.criteria_version,
        "error": analysis.error,
        "coverage": {
            verdict: sum(1 for row in rows if row.verdict == verdict)
            for verdict in ("confirmed", "partial", "transferable", "gap", "unverified")
        }
        | {"total": len(rows)},
        "requirements": [
            {
                "ordinal": row.ordinal,
                "text": row.text_,
                # What the posting said, and what the model judged it is worth.
                # Both travel: the first is the employer's words, the second is
                # what the band rule actually reads.
                "kind": row.kind,
                "importance": row.importance,
                "verdict": row.verdict,
                "shortfall": row.shortfall,
                "evidence": row.evidence,
            }
            for row in rows
        ],
        "model": analysis.model,
        "input_tokens": analysis.input_tokens,
        "output_tokens": analysis.output_tokens,
        # A Decimal audit value, as a string. A float here would drift.
        "cost": None if analysis.cost is None else str(analysis.cost),
        "is_fixture": analysis.is_fixture,
        "created_at": _iso(analysis.created_at),
        "completed_at": _iso(analysis.completed_at),
    }


async def _score_in_background(analysis_id: uuid.UUID, completion: StructuredCompletion) -> None:
    """Own session: the request's is closed by the time this runs.

    Lives in the API layer so `application/` imports no infrastructure.
    """
    async with get_session_factory()() as session:
        await run_analysis(session, analysis_id=analysis_id, completion=completion)
        await session.commit()


@router.get("/{application_id}/match", summary="The current match analysis")
async def read_match(
    application_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    record = await _owned(session, user, application_id)
    analysis = await _latest_analysis(session, record)

    stale = False
    if analysis is not None and analysis.status == MatchStatus.READY:
        profile = await session.scalar(
            select(ProfessionalProfile).where(ProfessionalProfile.user_id == user.id)
        )
        # Computed here, never stored: a stored flag goes wrong the moment a
        # profile is edited without every analysis being visited (FR-025).
        stale = bool(profile and profile.updated_at > analysis.created_at)

    return {
        "state": _state_of(record, analysis),
        "analysis": _analysis_out(analysis),
        "stale": stale,
    }


@router.post(
    "/{application_id}/match",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Score this job against the profile",
)
async def trigger_match(
    application_id: uuid.UUID,
    background: BackgroundTasks,
    session: DbSession,
    user: CurrentUser,
    completion: CompletionClient,
) -> dict[str, Any]:
    """Run an analysis by hand (FR-024).

    **No request body.** A model, criteria version or prompt accepted from the
    client would put cost and behaviour under the browser's control.
    """
    record = await _owned(session, user, application_id)

    in_flight = await session.scalar(
        select(MatchAnalysis).where(
            MatchAnalysis.application_id == record.id,
            MatchAnalysis.status == MatchStatus.PENDING,
        )
    )
    if in_flight is not None and is_abandoned(in_flight):
        # Reaped, not honoured. Otherwise the row blocks every future run and
        # the job is unrecoverable without SQL.
        in_flight.status = MatchStatus.FAILED
        in_flight.error = "The analysis stopped before it finished."
        in_flight.completed_at = datetime.now(UTC)
        await session.flush()
    elif in_flight is not None:
        # 409 rather than 202: returning success here lets five clicks queue
        # five runs. The partial unique index is the enforcement; this is its
        # surface (FR-007).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An analysis is already running."
        )

    analysis = await create_pending_analysis(session, record)
    if analysis is None:
        # Well-formed request; this job simply cannot be scored yet. Not a 500,
        # and not an empty 202.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="There is nothing to score against yet.",
        )

    await session.commit()
    background.add_task(_score_in_background, analysis.id, completion)
    return {"state": "running", "analysis": _analysis_out(analysis)}


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
