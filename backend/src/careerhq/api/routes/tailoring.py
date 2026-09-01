"""Tailoring — start a run, read the diff, decide each proposal, approve.

Six endpoints per `specs/005-resume-tailoring/contracts/http-api.md`. The rules
that run through `applications.py` run through here too — ownership comes from
the session, and another owner's resource is **404 rather than 403** — plus two
that are specific to this surface:

* **Nothing here reads upstream of persistence.** What the provider returned is
  reachable only as validated, finalised rows. An endpoint serving the
  unfinalised draft would route around FR-018: the grounding discard is enforced
  where rows are written, so anything reading earlier bypasses it while every
  other test still passes.
* **`.items` is loaded eagerly, always.** A lazy relationship on a version is a
  `MissingGreenlet` at serialisation time, which arrives as a 500 rather than as
  a test failure. It has already cost this project two debugging sessions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from careerhq.api.deps import CompletionClient, CurrentUser, DbSession
from careerhq.application.export import ExportRefused, latest_export
from careerhq.application.export_resume import export_version
from careerhq.application.guidelines import GuidelineSource, StaticGuidelines
from careerhq.application.immutability import VersionLocked, ensure_version_mutable
from careerhq.application.plan_adherence import (
    FindingFacts,
    ItemFacts,
    emphasis_adherence,
    plan_execution,
)
from careerhq.application.ports import StructuredCompletion
from careerhq.application.retrieved_guidelines import RetrievedGuidelines
from careerhq.application.submit_resume import (
    ExportChecksumMismatch,
    SubmissionRefused,
    submit_version,
)
from careerhq.application.tailor_resume import (
    TailoringInFlight,
    TailoringRefused,
    approve_version,
    create_pending_version,
    decide_item,
    run_tailoring,
)
from careerhq.config import Settings, get_settings
from careerhq.domain.models import (
    Application,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    ReviewerFinding,
    SubmittedResume,
    TailoringRun,
    VersionStatus,
)
from careerhq.infrastructure import storage
from careerhq.infrastructure.database import get_session_factory
from careerhq.infrastructure.embeddings import get_embedding_source

logger = logging.getLogger("careerhq.tailoring")

router = APIRouter(tags=["tailoring"])

#: The decisions a client may send. `PENDING` is the initial state, not a
#: choice, and there is no way back to it — "I have not decided" cannot be
#: re-asserted once it has been.
SETTABLE_DECISIONS = frozenset(
    {ProposalDecision.ACCEPTED, ProposalDecision.REJECTED, ProposalDecision.EDITED}
)

#: Statuses in which an item decision is allowed.
#:
#: While the workflow is running there is nothing to decide on, and the items do
#: not exist yet. `READY` is included because in this slice a confirmed version
#: is still editable — nothing has left the building. **Slice 006 narrows this
#: to `AWAITING_APPROVAL` alone**, once export gives "already sent to an
#: employer" a meaning. The check lives here now rather than arriving with the
#: state that needs it, which is what the contract asks for.
DECIDABLE_STATUSES = frozenset({VersionStatus.AWAITING_APPROVAL, VersionStatus.READY})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _owned_application(
    session: DbSession, user: CurrentUser, application_id: uuid.UUID
) -> Application:
    record = await session.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return record


async def _owned_version(
    session: DbSession, user: CurrentUser, version_id: uuid.UUID
) -> ResumeVersion:
    """A version the session user owns, with its items and their findings loaded.

    Ownership travels through the application rather than being stored on the
    version, so there is one place a user id is checked and no second copy to
    fall out of step. Another owner's version is a 404: a 403 would confirm the
    id names something, which is the disclosure the rule is about.
    """
    record = await session.scalar(
        select(ResumeVersion)
        .join(Application, Application.id == ResumeVersion.application_id)
        .where(ResumeVersion.id == version_id, Application.user_id == user.id)
        .options(selectinload(ResumeVersion.items).selectinload(ResumeVersionItem.findings))
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    return record


async def _run_of(session: DbSession, version: ResumeVersion) -> TailoringRun | None:
    run: TailoringRun | None = await session.scalar(
        select(TailoringRun).where(TailoringRun.resume_version_id == version.id)
    )
    return run


def _finding_out(finding: ReviewerFinding) -> dict[str, Any]:
    return {
        "kind": finding.kind,
        "detail": finding.detail,
        "quoted_text": finding.quoted_text,
        # Which review pass caught it. A fabrication caught on attempt one and
        # fixed on attempt two still happened, and the attempt is what tells the
        # two apart when both are shown.
        "attempt": finding.attempt,
    }


def _item_out(item: ResumeVersionItem, final_attempt: int | None = None) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "source_kind": item.source_kind,
        "source_item_id": str(item.source_item_id) if item.source_item_id else None,
        "position": item.position,
        "included": item.included,
        # All three travel. The diff is unrenderable without the first two, and
        # `final_text` is materialised rather than derived so no reader —
        # slice 006's PDF export above all — re-implements the rule.
        "original_text": item.original_text,
        "proposed_text": item.proposed_text,
        "final_text": item.final_text,
        "decision": item.decision,
        # Nested under the item they concern (FR-042), and — given a run —
        # **the final pass's findings only**. The version is the decision
        # surface, and the last review re-judged the whole composed resume, so
        # its findings are a complete statement about the draft as it stands.
        # A pass-0 `ungrounded` served here would sit under the *fixed*
        # proposal that survived it, calling the current wording unsupported
        # and reprinting the fabricated `quoted_text` beside a valid proposal.
        # Earlier passes stay in the database as the audit record.
        "findings": [
            _finding_out(f)
            for f in item.findings
            if final_attempt is None or f.attempt == final_attempt
        ],
    }


def submission_out(record: SubmittedResume) -> dict[str, Any]:
    """What a submission looks like to a client. **Public, and shared on purpose.**

    `applications.py` renders the same object on the application it belongs to, and the
    "no storage key" rule below is exactly the kind that decays when it is written twice.
    One function, imported, rather than two that agree until one of them is edited.

    **No `document_storage_key`.** It is an internal address: publishing it hands a client
    something that only means anything to the bucket, invites it to be treated as a
    document reference, and outlives the route that returned it. The document is reached
    through `GET /versions/{id}/document`, which checks ownership. The same rule `export`
    and `read_original` follow.
    """
    return {
        "resume_version_id": str(record.resume_version_id),
        "checksum_sha256": record.checksum_sha256,
        "byte_size": record.byte_size,
        "submitted_at": _iso(record.submitted_at),
    }


async def _version_out(
    session: DbSession, version: ResumeVersion, run: TailoringRun | None
) -> dict[str, Any]:
    """The version as the diff surface reads it.

    While the run is in flight there are no items and no score. The interface
    renders progress from that (FR-039) — an empty diff would otherwise be
    indistinguishable from "the agent proposed nothing".
    """
    draft_findings: list[ReviewerFinding] = []
    if run is not None:
        draft_findings = list(
            await session.scalars(
                select(ReviewerFinding).where(
                    ReviewerFinding.tailoring_run_id == run.id,
                    ReviewerFinding.resume_version_item_id.is_(None),
                    # Final pass only, same rule as the item findings below: an
                    # `uncovered` the revision resolved is history; one that
                    # still holds was re-raised by the last review.
                    ReviewerFinding.attempt == run.attempts,
                )
            )
        )

    return {
        "id": str(version.id),
        "application_id": str(version.application_id),
        "name": version.name,
        "professional_title": version.professional_title,
        "status": version.status,
        "confidence_score": version.confidence_score,
        # A failed run leaves the version at `draft` carrying this, because
        # there is no `failed` status. Without it the interface can only say
        # that nothing happened.
        "failure_reason": version.failure_reason,
        # AI provenance, at the surface a person approves from (FR-022). The
        # drafting model is the one that wrote these words; the full per-task
        # configuration is on the run endpoint, which is where inspection lives.
        "model": (run.model_config_used or {}).get("tailor_draft") if run else None,
        "is_fixture": bool(run.is_fixture) if run else False,
        "cost": str(run.cost) if run else None,
        # Lineage: which state of the profile this was tailored from. A later
        # profile edit must not reach this document (Principle IV), and this is
        # what makes that checkable rather than asserted.
        "source_profile_updated_at": _iso(version.source_profile_updated_at),
        "created_at": _iso(version.created_at),
        "items": [
            _item_out(item, final_attempt=run.attempts if run else None) for item in version.items
        ],
        # Only findings with no item — `uncovered`, which concerns the draft as
        # a whole. Manufacturing an item for an unaddressed requirement would
        # repeat slice 004's `unverified`-shortfall mistake exactly.
        "draft_findings": [_finding_out(f) for f in draft_findings],
    }


def build_guideline_source(session: AsyncSession, settings: Settings) -> GuidelineSource:
    """Choose the implementation behind the port. **This is the 005/006 seam** (T030).

    One `if`, and it is the whole of what slice 006 changes about the workflow: no node,
    no state key, no finalisation rule (FR-002). The workflow cannot tell which branch
    ran, which is the property the boundary exists to preserve.

    `static` stays reachable and is not dead code. It is the documented FR-009 fallback,
    and it is the only way to take SC-008's cost baseline **in the same session** as the
    retrieval measurement — which is what makes that comparison mean anything.

    The ceiling comes from configuration. Hard-coding 1,500 here would leave FR-014's
    limit looking configurable while quietly not being.
    """
    if settings.guideline_source == "static":
        return StaticGuidelines()
    return RetrievedGuidelines(
        session,
        embedder=get_embedding_source(),
        token_ceiling=settings.retrieval_token_ceiling,
    )


async def _tailor_in_background(version_id: uuid.UUID, completion: StructuredCompletion) -> None:
    """Own session: the request's is closed by the time this runs.

    Lives in the API layer so `application/` imports no infrastructure, and the
    guideline source is chosen here — which is the 005/006 seam. Slice 006
    swaps `StaticGuidelines` for retrieval and changes nothing else.

    **The source is built per run and holds this task's session**, which is not a
    lifetime a startup singleton could have. The expensive object — the embedding model —
    *is* process-wide (`get_embedding_source`); `RetrievedGuidelines` around it is a
    handful of attributes.
    """
    async with get_session_factory()() as session:
        await run_tailoring(
            session,
            version_id=version_id,
            completion=completion,
            guidelines=build_guideline_source(session, get_settings()),
        )
        await session.commit()


@router.post(
    "/applications/{application_id}/tailor",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Tailor this resume to this job",
)
async def start_tailoring(
    application_id: uuid.UUID,
    background: BackgroundTasks,
    session: DbSession,
    user: CurrentUser,
    completion: CompletionClient,
) -> dict[str, Any]:
    """Start a run (FR-003).

    **No request body.** A model, prompt or revision budget accepted from the
    client would put cost and behaviour under the browser's control.

    The version and its run are both created before this returns, so the id is
    immediately pollable and a failure has somewhere to record itself.
    """
    application = await _owned_application(session, user, application_id)

    try:
        version = await create_pending_version(session, application)
    except TailoringInFlight as exc:
        # 409 rather than 202. Returning success here lets five clicks queue
        # five runs, each of which bills a provider. The partial unique index is
        # the real enforcement (FR-004); this is its surface.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except TailoringRefused as exc:
        # The reason travels as a field, not only as prose. "Run a match
        # analysis" and "re-run it, your profile changed" are different actions,
        # and a client that has to pattern-match on a sentence will get it wrong
        # the first time the sentence is reworded.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"reason": exc.reason, "message": exc.detail},
        ) from exc

    await session.commit()
    background.add_task(_tailor_in_background, version.id, completion)

    return {
        "version_id": str(version.id),
        "status": version.status,
        # For the audit view. The version is the polling target and the resource
        # the interface is about; the run is what explains it afterwards.
        "run_id": str(version.tailoring_run_id) if version.tailoring_run_id else None,
    }


@router.get("/applications/{application_id}/versions", summary="Versions for one job")
async def list_versions(
    application_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Newest first. Enough to render a list, not the whole diff."""
    application = await _owned_application(session, user, application_id)
    rows = await session.scalars(
        select(ResumeVersion)
        .where(ResumeVersion.application_id == application.id)
        .order_by(ResumeVersion.created_at.desc())
    )
    return {
        "versions": [
            {
                "id": str(row.id),
                "name": row.name,
                "status": row.status,
                "confidence_score": row.confidence_score,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]
    }


@router.get("/versions/{version_id}", summary="One tailored version, with its diff")
async def get_version(
    version_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    version = await _owned_version(session, user, version_id)
    return await _version_out(session, version, await _run_of(session, version))


@router.patch("/versions/{version_id}/items/{item_id}", summary="Decide one proposal")
async def patch_item(
    version_id: uuid.UUID,
    item_id: uuid.UUID,
    body: dict[str, Any],
    session: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Accept, reject, or replace one proposal (FR-024, FR-026, FR-027).

    **Rejecting triggers no AI work.** The owner's wording stands and nothing is
    re-drafted; re-running the whole tailoring is still available if the draft is
    broadly wrong. A silent re-write here would be a provider call nobody asked
    for, on the one action that means "stop".
    """
    version = await _owned_version(session, user, version_id)
    # **The lock is asked first, and it is asked rather than restated.** Both answers
    # are 409, so the only thing separating them is what the person is told: a locked
    # version is finished, and "not ready for review yet" would describe it as a state
    # still to come. `decide_item` refuses again at the point of mutation — this is not
    # a second copy of the rule but the same function, called early enough to say the
    # accurate thing.
    try:
        ensure_version_mutable(version.status)
    except VersionLocked as locked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(locked)) from locked

    if version.status not in DECIDABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This version is not ready for review yet.",
        )

    raw = body.get("decision")
    try:
        decision = ProposalDecision(str(raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown decision {raw!r}.",
        ) from exc
    if decision not in SETTABLE_DECISIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{decision.value} is not a decision a client may set.",
        )

    text = body.get("text")
    if decision is ProposalDecision.EDITED and not (text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An edited item needs text.",
        )

    # Scoped by the version in the path rather than looked up on its own, so an
    # item id alone is never enough to reach a row.
    item = next((row for row in version.items if row.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")

    await decide_item(session, item=item, decision=decision, text=text)
    await session.commit()
    # Same shape and the same final-pass filter as the version payload — the
    # client swaps this into its item list, and a decided item that regained
    # earlier passes' findings would differ from its neighbours.
    run = await _run_of(session, version)
    return _item_out(item, final_attempt=run.attempts if run else None)


@router.post("/versions/{version_id}/approve", summary="Confirm this tailored version")
async def approve(version_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    """FR-025 and FR-028.

    Every item still pending counts as accepted — the import-review precedent,
    where an untouched review adds everything not discarded. A second pattern
    for the same idea costs an affordance every time.

    **Starts nothing.** No AI work follows approval in this slice, which is
    precisely why the workflow needs no durable pause and resume.
    """
    version = await _owned_version(session, user, version_id)
    # Asked before the wrong-state check for the same reason as `patch_item`: an
    # exported version can never be awaiting approval, so "not awaiting approval" would
    # be true and useless.
    try:
        ensure_version_mutable(version.status)
    except VersionLocked as locked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(locked)) from locked

    # `!=` rather than `is not`: `status` is a `String` column, so a row loaded
    # in a session that did not create it comes back as a plain `str` and an
    # identity comparison never matches. Slice 004 shipped exactly that and left
    # every analysis `pending` forever under a green suite.
    if version.status != VersionStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This version is not awaiting approval.",
        )

    await approve_version(session, version=version)
    await session.commit()
    return await _version_out(session, version, await _run_of(session, version))


@router.post("/versions/{version_id}/export", summary="Export this version as a PDF")
async def export(version_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    """FR-015, FR-016, FR-019 — and the route owns none of those rules.

    `ensure_exportable` decides refusal (T033) and `export_version` owns render → store →
    record → transition (T036). This translates the refusal into **409** — the status
    `approve` already uses for a wrong-state request — and commits, which is the
    transaction boundary every use case here leaves to its caller.

    **The refusal's message is returned verbatim, and that is safe by construction.**
    It is authored user-facing text ("Approve the tailored resume before exporting it"),
    not an exception stringified from a driver. The rule this project follows is that the
    *detail* of an infrastructure failure goes to the log and the *type* to the browser;
    a message written for the person is the case that rule exempts.
    """
    version = await _owned_version(session, user, version_id)

    try:
        record = await export_version(session, version_id=version.id)
    except ExportRefused as refused:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refused)) from refused

    await session.commit()
    await session.refresh(version)

    body = await _version_out(session, version, await _run_of(session, version))
    # **No `document_storage_key`.** The key is an internal address; the document is
    # reached by its own route, the same rule `read_original` follows for an upload.
    body["export"] = {
        "checksum_sha256": record.checksum_sha256,
        "byte_size": record.byte_size,
        "exported_at": _iso(record.exported_at),
    }
    return body


@router.post("/versions/{version_id}/submit", summary="Mark this version as submitted")
async def submit(version_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    """FR-020, FR-021 — and the route owns none of those rules.

    `submit_version` decides submittability, picks the export, **re-reads the stored bytes
    and re-hashes them** before anything is written, inserts the record and moves the
    status (T038). This translates and commits, exactly as `export` does.

    **Two 409s that mean different things.** A wrong-state refusal is the person's to
    resolve — export it first, or revise as a new version. A checksum mismatch is not:
    the stored document is not the document its record describes, and pressing the button
    again cannot fix that. The status code cannot separate them, so the message does. The
    two exception types are deliberately unrelated (T038) precisely so this handler cannot
    collapse them by accident.

    **A mismatch is also logged, and that is not decoration.** An integrity failure whose
    only trace is a 409 in somebody's browser is invisible to whoever has to explain it.
    The identifiers go in `extra` fields because Railway blanks the message of a parsed
    JSON log and keeps the structured ones.

    **The status and `date_applied` of the application are not touched.** `docs/03` §10.2
    runs the dependency the other way — *"Moving to `Applied` requires a Submitted
    Resume"* — `date_applied` is a field the person fills in, and the status label is
    their own words. Deciding either for them here would overwrite what they said about
    their own history.
    """
    version = await _owned_version(session, user, version_id)

    try:
        record = await submit_version(session, version_id=version.id)
    except SubmissionRefused as refused:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refused)) from refused
    except ExportChecksumMismatch as mismatch:
        logger.error(
            "submission refused: the stored document no longer matches its checksum",
            extra={"version_id": str(version.id), "profile_id": str(version.profile_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(mismatch)
        ) from mismatch

    await session.commit()
    await session.refresh(version)

    body = await _version_out(session, version, await _run_of(session, version))
    body["submission"] = submission_out(record)
    return body


@router.get("/versions/{version_id}/document", summary="The exported PDF")
async def read_document(version_id: uuid.UUID, session: DbSession, user: CurrentUser) -> Response:
    """Serve the stored bytes. **Never renders, and never exports.**

    Separate from the POST so that *downloading again* is not *exporting again*:
    re-export is legitimate, but it writes a new row and a new object, and a person
    clicking download twice should not accumulate export records.

    Serves the most recent export of this version. Under FR-031 the repeats are
    byte-identical anyway, so "most recent" and "any" differ only in bookkeeping.

    Always an attachment: unlike the retained upload there is no viewer to frame it in,
    and the content type is ours rather than attacker-supplied because we rendered it.
    """
    await _owned_version(session, user, version_id)

    # The shared query, not a local one: the submit use case freezes whichever export
    # this returns, and two `ORDER BY` clauses that merely happen to agree would let a
    # person download one document and send a record of another.
    record = await latest_export(session, version_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This version has not been exported yet.",
        )

    data = await storage.get_object(record.document_storage_key)

    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="resume.pdf"',
            # One person's résumé: never held by a shared proxy.
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/versions/{version_id}/run", summary="The audit record for this version's run")
async def get_run(version_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Principle V: inputs, model configuration, token usage, cost, timings.

    Its own endpoint rather than a field on the version, because it is
    inspection rather than the document — and slice 007 reads exactly this
    shape programmatically to compute the benchmark.
    """
    version = await _owned_version(session, user, version_id)
    run = await _run_of(session, version)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No run for this version."
        )

    return {
        "id": str(run.id),
        "version_id": str(version.id),
        "status": run.status,
        "failure_reason": run.failure_reason,
        # The Tailoring Plan the draft was written against. Reading it is how a
        # person checks that the agent aimed at the right thing before deciding
        # whether it hit it.
        "plan": run.plan,
        "attempts": run.attempts,
        # How much of that plan the draft actually carried out. **A measurement,
        # not a gate** — two real runs disagreed sharply (eight planned emphases
        # and four rewrites on one job, six and one on another), and a threshold
        # chosen from two samples would encode a guess as a rule. Reported here
        # so a distribution accumulates for slice 007 to judge.
        "plan_adherence": emphasis_adherence(
            run.plan,
            rewritten_ids=[
                str(item.source_item_id)
                for item in version.items
                if item.proposed_text is not None and item.source_item_id is not None
            ],
        ),
        # The same question asked in states rather than one ratio, because D0
        # above conflates a proposal that was reverted with one that changed the
        # document, and reports a contaminated run's unknowable outcomes as
        # failures. Both are reported side by side while a distribution
        # accumulates; neither gates anything.
        "plan_execution": plan_execution(
            run.plan,
            items=[
                ItemFacts(
                    source_item_id=str(item.source_item_id),
                    source_kind=item.source_kind,
                    original_text=item.original_text,
                    proposed_text=item.proposed_text,
                    final_text=item.final_text,
                    position=item.position,
                    displaced_position=item.displaced_position,
                )
                for item in version.items
                if item.source_item_id is not None
            ],
            findings=[
                FindingFacts(
                    source_item_id=str(item.source_item_id),
                    kind=finding.kind,
                    quoted_text=finding.quoted_text,
                )
                for item in version.items
                if item.source_item_id is not None
                for finding in item.findings
            ],
            # Pre-T094 a revision replaced the draft's item set. `review_confidences`
            # is null exactly on runs persisted before that fix shipped — it and the
            # merge landed in one deployment — so a null on a run that revised dates
            # it to the code that could erase decisions.
            contaminated=run.review_confidences is None and run.attempts > 0,
            # Whether this version's rows can say "no proposal arrived" at all.
            # A run persisted before `displaced_position` existed has NULL
            # everywhere, and reading that as "the draft did nothing" is the
            # error T095 removes. Derived from the rows rather than a date so
            # nothing depends on when a migration happened to run; a run whose
            # draft proposed *nothing* would be read as unrecorded rather than
            # as inactive, which errs toward "unknown" and is the safe way to
            # be wrong.
            position_evidence=any(item.displaced_position is not None for item in version.items),
        ),
        "match_analysis_id": str(run.match_analysis_id),
        # Each with its source. Redundant while that source is a static rubric;
        # the only thing that makes slice 006's retrieval measurable once it is
        # not, and what keeps 005 and 006 runs comparable.
        "guidelines_used": run.guidelines_used or [],
        # As resolved at run time, not the configuration file's current
        # contents — which may have changed since.
        "models": run.model_config_used or {},
        "finalisation_rules_version": run.finalisation_rules_version,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        # A Decimal audit value, as a string. A float here would drift.
        "cost": str(run.cost),
        "is_fixture": run.is_fixture,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }
