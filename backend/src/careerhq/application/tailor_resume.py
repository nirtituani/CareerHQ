"""Tailoring a resume: preconditions, execution, finalisation, persistence.

**This module owns everything the graph does not.** The graph decides execution
flow; this decides what is true afterwards. Contract O3, and the split matters
most at one point: the severity rules run **here**, before any row is written,
so a claim the Reviewer judged unsupported has no persisted representation to
leak from and cannot reach an approve button.

A terminal `finalize` node that "just writes the result" would satisfy every
other rule in the contract while breaking that one. It was the single defect in
the first design sketch, and it is the easiest thing to reintroduce.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from careerhq.application.agents.tailoring import build_tailoring_graph
from careerhq.application.agents.tailoring.state import TailoringState
from careerhq.application.finalisation_rules import FINALISATION_RULES_VERSION, finalise
from careerhq.application.guidelines import GuidelineQuery, GuidelineSource
from careerhq.application.ports import (
    StructuredCompletion,
    UsageRecorder,
    safe_validation_errors,
)
from careerhq.application.scoreability import scoreable_posting
from careerhq.config import get_settings
from careerhq.domain.models import (
    Application,
    Certification,
    Education,
    Language,
    MatchAnalysis,
    MatchStatus,
    ProfessionalProfile,
    Project,
    ProposalDecision,
    ResumeProfile,
    ResumeVersion,
    ResumeVersionItem,
    ReviewerFinding,
    RunStatus,
    Skill,
    SourceKind,
    SummaryBlock,
    TailoringRun,
    TailoringRunCall,
    VersionStatus,
    WorkExperience,
)

logger = logging.getLogger(__name__)

#: A run older than this with no `finished_at` is presumed dead.
#:
#: **Not copied from match analysis's threshold**, which guards a run that
#: should take seconds. A tailoring run makes up to seven calls, three of them
#: on the slower reviewing model, and SC-001 allows three minutes for the full
#: revision budget. Releasing one that is legitimately in its second revision
#: would let a second run start against the same job — which the partial index
#: would then reject, leaving the person unable to do the one thing that
#: recovers it. That is exactly the trap slice 004 fell into three times.
ABANDONED_AFTER = timedelta(minutes=30)


class TailoringRefused(Exception):
    """A precondition is unmet. Carries a `reason` the API turns into a 422.

    The two reasons are deliberately distinct: *run a match analysis first* and
    *your profile changed, re-run the match* are different actions, and one
    message covering both makes the interface guess.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class TailoringInFlight(Exception):
    """A run is already going for this job (FR-004)."""


def is_abandoned(run: TailoringRun, *, now: datetime | None = None) -> bool:
    """Whether a run should be released so the owner can try again."""
    if run.finished_at is not None or run.status != RunStatus.RUNNING:
        return False
    moment = now or datetime.now(UTC)
    return moment - run.started_at > ABANDONED_AFTER


async def _current_analysis(
    session: AsyncSession, application: Application
) -> MatchAnalysis | None:
    if application.current_match_analysis_id is None:
        return None
    return await session.get(MatchAnalysis, application.current_match_analysis_id)


async def check_preconditions(
    session: AsyncSession, application: Application
) -> tuple[MatchAnalysis, ProfessionalProfile, ResumeProfile]:
    """FR-001. Refuse rather than tailor against a fit assessment that has moved.

    A plan built on an analysis computed against an **older profile** cites
    evidence that no longer exists, and the Reviewer then rejects claims that
    were properly grounded when they were analysed. That failure is expensive to
    debug and reads as the Reviewer malfunctioning.

    Staleness is computed here rather than stored, which is the rule `match.py`
    established: a stored flag is a second source of truth that goes wrong the
    moment a profile is edited without every dependent row being visited.
    """
    # **Checked first, and it is the most fundamental of the four.** Tailoring
    # had no content check at all: its precondition was a `ready` analysis, and
    # an empty-posting `0/100` is `ready`. So a five-call run at $0.30-$0.46
    # could plan and draft against `description: null` and no requirements.
    #
    # It comes before the analysis check because "add the posting" is the action
    # a person can actually take; "run a match analysis" on a job with nothing
    # to analyse sends them round a loop.
    if scoreable_posting(application) is None:
        raise TailoringRefused(
            "no_posting",
            "This job has no posting content yet. Add the job description or its "
            "requirements, run a match analysis, and then tailor.",
        )

    analysis = await _current_analysis(session, application)
    if analysis is None or analysis.status != MatchStatus.READY:
        raise TailoringRefused(
            "no_analysis",
            "This job has not been scored yet. Run a match analysis before tailoring.",
        )

    profile = await session.scalar(
        select(ProfessionalProfile).where(ProfessionalProfile.user_id == application.user_id)
    )
    if profile is None:
        raise TailoringRefused("no_profile", "No professional profile exists for this user.")

    if profile.updated_at > analysis.created_at:
        raise TailoringRefused(
            "stale_analysis",
            "Your profile has changed since this job was scored. "
            "Re-run the match analysis before tailoring.",
        )

    master = await session.scalar(
        select(ResumeProfile).where(ResumeProfile.profile_id == profile.id, ResumeProfile.is_master)
    )
    if master is None:
        raise TailoringRefused(
            "no_master", "No master resume exists yet. Approve a CV import first."
        )

    return analysis, profile, master


async def create_pending_version(session: AsyncSession, application: Application) -> ResumeVersion:
    """Reserve the version and its run, before any provider call (FR-003).

    Created **synchronously and together**, so the 202 carries an id the client
    can poll immediately and a failure has somewhere to record itself. The
    version starts at `DRAFT` — the master's content, not yet tailored — which
    is what makes `DRAFT -> TAILORING` a real transition rather than
    bookkeeping, exactly as `docs/03` §10.1 draws it.
    """
    analysis, profile, master = await check_preconditions(session, application)

    in_flight = await session.scalar(
        select(ResumeVersion).where(
            ResumeVersion.application_id == application.id,
            ResumeVersion.status.in_([VersionStatus.TAILORING, VersionStatus.REVIEWING]),
        )
    )
    if in_flight is not None:
        # The version's own pointer, not a query over every run it has ever had.
        # A reused draft accumulates runs, and an unordered `scalar()` would pick
        # among them arbitrarily.
        run = (
            await session.get(TailoringRun, in_flight.tailoring_run_id)
            if in_flight.tailoring_run_id
            else None
        )
        if run is not None and is_abandoned(run):
            # Release it rather than refusing. Slice 004 refused, three times,
            # and each recovery needed SQL by hand.
            run.status = RunStatus.ABANDONED
            run.finished_at = datetime.now(UTC)
            in_flight.status = VersionStatus.DRAFT
            in_flight.failure_reason = "The previous run stopped without finishing."
            await session.flush()
        else:
            raise TailoringInFlight("A tailoring run is already in progress for this job.")

    # **A retry reuses the draft.** data-model.md says so twice, and it is the
    # entire reason there is no `failed` version status: "the owner can retry
    # into the same `draft` rather than accumulating abandoned versions". This
    # used to create a new version every time, so the absence of a `failed`
    # status bought nothing — the Versions list filled with identical dead
    # drafts by another route.
    #
    # **Only a `draft` is a retry target.** Tailoring a job again after
    # approving a version is a new document, not a second attempt at the old
    # one, and overwriting an approved version would destroy something the owner
    # explicitly confirmed (Principle IV, FR-029).
    version = await session.scalar(
        select(ResumeVersion)
        .where(
            ResumeVersion.application_id == application.id,
            ResumeVersion.status == VersionStatus.DRAFT,
        )
        .order_by(ResumeVersion.created_at.desc())
        .limit(1)
    )

    if version is None:
        version = ResumeVersion(
            profile_id=profile.id,
            application_id=application.id,
            source_resume_profile_id=master.id,
            source_profile_updated_at=profile.updated_at,
            name=f"{application.job_title} — tailored",
            status=VersionStatus.TAILORING,
            # Assigned at construction. A lazy load on a freshly added object
            # raises MissingGreenlet when it is serialised, which slice 004 met
            # as a 500.
            items=[],
        )
        session.add(version)
    else:
        # Rows from an attempt that died after writing items and before
        # finishing — `run_tailoring` flushes items well before it writes the
        # run's totals, so that window is real. Rendering them beside this
        # attempt's proposals would show a diff assembled from two runs with
        # nothing saying which came from where.
        await session.execute(
            delete(ResumeVersionItem).where(ResumeVersionItem.resume_version_id == version.id)
        )
        # The lineage is re-snapshotted because this document is being written
        # now, against the profile the preconditions above just re-checked.
        version.source_resume_profile_id = master.id
        version.source_profile_updated_at = profile.updated_at
        version.status = VersionStatus.TAILORING
        # The previous attempt's explanation describes a run that is no longer
        # the current one. Leaving it would caption a live attempt with a dead
        # one's error.
        version.failure_reason = None
        version.confidence_score = None

    await session.flush()

    settings = get_settings()
    run = TailoringRun(
        resume_version_id=version.id,
        match_analysis_id=analysis.id,
        finalisation_rules_version=FINALISATION_RULES_VERSION,
        model_config_used={
            task: settings.model_for_task(task)
            for task in (
                "tailor_plan",
                "tailor_draft",
                "tailor_review",
                "tailor_revise",
                "tailor_revise_escalated",
            )
        },
        status=RunStatus.RUNNING,
        findings=[],
    )
    session.add(run)
    await session.flush()

    version.tailoring_run_id = run.id
    await session.flush()

    return version


async def _render_master(
    session: AsyncSession, profile_id: uuid.UUID
) -> tuple[str, list[dict[str, Any]]]:
    """The profile as text for the prompt, and its items as rows to tailor.

    Both come from the same walk, so what the model is shown and what can be
    proposed against cannot drift apart.

    **Every proposable line carries its database id**, as `[id: <uuid>]`. That
    is not decoration: `DraftedItem.source_item_id` is how a proposal maps back
    to a master row, and for two paid runs this text carried none. The Draft
    node was instructed to return the items it changed *by id* while being shown
    2,801 characters of profile and zero ids. It could not comply; it returned
    nulls; the Reviewer then had nothing to copy either and its findings failed
    validation.

    The quieter consequence was worse. With no ids, **nothing maps back** — a
    run that passed review would have persisted a diff with zero proposed
    changes, which is a tailoring feature that silently does nothing.

    Lines with no `[id: …]` — a role's heading — are context. The prompt says so,
    and there is nothing for a model to attach a proposal to there.
    """

    def _line(item_id: uuid.UUID, label: str, text: str) -> str:
        return f"[id: {item_id}] {label}: {text}"

    lines: list[str] = []
    items: list[dict[str, Any]] = []

    summaries = (
        (await session.execute(select(SummaryBlock).where(SummaryBlock.profile_id == profile_id)))
        .scalars()
        .all()
    )
    for index, summary in enumerate(summaries):
        lines.append(_line(summary.id, "SUMMARY", summary.text))
        items.append(
            {
                "source_kind": SourceKind.SUMMARY,
                "source_item_id": summary.id,
                "position": index,
                "text": summary.text,
            }
        )

    experiences = (
        (
            await session.execute(
                select(WorkExperience)
                .where(WorkExperience.profile_id == profile_id)
                .options(selectinload(WorkExperience.bullets))
            )
        )
        .scalars()
        .all()
    )
    position = 0
    for experience in experiences:
        # No id: a role heading is context, not something to propose against.
        lines.append(f"ROLE: {experience.title} at {experience.company} ({experience.start_date})")
        for bullet in experience.bullets:
            lines.append(_line(bullet.id, "BULLET", bullet.text))
            items.append(
                {
                    "source_kind": SourceKind.EXPERIENCE_BULLET,
                    "source_item_id": bullet.id,
                    "position": position,
                    "text": bullet.text,
                }
            )
            position += 1

    # Written out rather than looped over a table of (model, kind, accessor).
    # The loop was three lines shorter and mypy could not type it at all, which
    # meant the one place a column name could be wrong was the one place with no
    # checking.
    simple: list[tuple[SourceKind, list[tuple[uuid.UUID, str | None]]]] = [
        (
            SourceKind.SKILL,
            [
                (row.id, row.name)
                for row in (
                    await session.execute(select(Skill).where(Skill.profile_id == profile_id))
                )
                .scalars()
                .all()
            ],
        ),
        (
            SourceKind.PROJECT,
            [
                (row.id, row.name)
                for row in (
                    await session.execute(select(Project).where(Project.profile_id == profile_id))
                )
                .scalars()
                .all()
            ],
        ),
        (
            SourceKind.EDUCATION,
            [
                (row.id, row.institution)
                for row in (
                    await session.execute(
                        select(Education).where(Education.profile_id == profile_id)
                    )
                )
                .scalars()
                .all()
            ],
        ),
        (
            SourceKind.CERTIFICATION,
            [
                (row.id, row.name)
                for row in (
                    await session.execute(
                        select(Certification).where(Certification.profile_id == profile_id)
                    )
                )
                .scalars()
                .all()
            ],
        ),
        (
            SourceKind.LANGUAGE,
            [
                (row.id, row.name)
                for row in (
                    await session.execute(select(Language).where(Language.profile_id == profile_id))
                )
                .scalars()
                .all()
            ],
        ),
    ]

    for kind, rows in simple:
        for index, (row_id, text) in enumerate(rows):
            if not text:
                continue
            lines.append(_line(row_id, kind.value.upper(), text))
            items.append(
                {
                    "source_kind": kind,
                    "source_item_id": row_id,
                    "position": index,
                    "text": text,
                }
            )

    return "\n".join(lines), items


async def _record_usage(session: AsyncSession, run: TailoringRun, recorder: UsageRecorder) -> None:
    """Write what the provider billed onto the run. **Both paths call this.**

    Success and failure used to account differently: success summed the graph's
    return value, and failure recorded nothing at all — because a graph that
    raises does not return. So a run that made three calls and was billed for
    all three reported `0 tokens, $0`, which reads as free rather than as
    unrecorded (FR-035).

    The totals answer "what did this run cost"; the `tailoring_run_calls` rows
    answer the question run `cd27b092` could not — *which call* spent it
    (T092). Both are written here, from the same recorder, so they cannot
    drift; and both survive a failure, because the calls a failed run made
    were billed whether or not the run finished.

    Starts from zero rather than from the run's current cost, and the rows are
    delete-then-insert for the same reason: calling this twice — a success
    that then fails on the flush re-enters through the failure path — must not
    double-count. The unique (run, sequence) index is the schema's own guard
    for the day this rule is broken.
    """
    run.input_tokens = recorder.total_input_tokens
    run.output_tokens = recorder.total_output_tokens
    run.cost = recorder.total_cost
    run.is_fixture = recorder.any_fixture

    await session.execute(
        delete(TailoringRunCall).where(TailoringRunCall.tailoring_run_id == run.id)
    )
    for sequence, call in enumerate(recorder.calls):
        session.add(
            TailoringRunCall(
                tailoring_run_id=run.id,
                sequence=sequence,
                # Always stamped by the recorder; a `None` slipping through is
                # caught by the column's NOT NULL rather than papered over.
                task=call.task,
                model=call.model,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                cost=call.cost,
                is_fixture=call.is_fixture,
            )
        )


async def run_tailoring(
    session: AsyncSession,
    *,
    version_id: uuid.UUID,
    completion: StructuredCompletion,
    guidelines: GuidelineSource,
) -> None:
    """Run the workflow and persist what it produced. **Never raises.**

    A background task has nowhere to raise to, so an escaping failure would
    leave the version `TAILORING` forever — the one outcome the reserved row
    exists to prevent.
    """
    version = await session.get(ResumeVersion, version_id)
    if version is None:
        return
    # **The version's own pointer, never a query over its runs.** A reused
    # draft has one run per attempt, and an unordered `scalar()` returns
    # whichever the database hands back first — so a successful retry could
    # write its plan, tokens and cost onto the *failed* run and leave the
    # current one reading `running` forever. That was harmless only while every
    # version had exactly one run.
    run = (
        await session.get(TailoringRun, version.tailoring_run_id)
        if version.tailoring_run_id
        else None
    )
    if run is None:
        return

    # Wraps the seam so every billed call is remembered even when one of them
    # raises. The graph, the state and the nodes are untouched.
    recorder = UsageRecorder(completion)

    try:
        application = await session.get(Application, version.application_id)
        analysis = await session.get(MatchAnalysis, run.match_analysis_id)
        if application is None or analysis is None:
            raise RuntimeError("the job or its analysis vanished mid-run")

        master_text, master_items = await _render_master(session, version.profile_id)

        requirements = (
            (
                await session.execute(
                    select(MatchAnalysis)
                    .where(MatchAnalysis.id == analysis.id)
                    .options(selectinload(MatchAnalysis.requirements))
                )
            )
            .unique()
            .scalar_one()
            .requirements
        )

        guidance = await guidelines.guidelines_for(
            context=GuidelineQuery(
                role_title=application.job_title,
                requirements=[r.text_ for r in requirements],
            )
        )

        state = TailoringState(
            # `master_items` is the same list used below to build version rows,
            # so what the Reviewer is shown and what is persisted cannot drift.
            master_items=master_items,
            job={
                "title": application.job_title,
                "description": application.job_description,
                "requirements": application.requirements or [],
            },
            master=master_text,
            match={
                "score": analysis.overall_score,
                "band": analysis.band,
                "requirements": [
                    {
                        "text": r.text_,
                        "importance": r.importance,
                        "verdict": r.verdict,
                        "evidence": r.evidence,
                    }
                    for r in requirements
                ],
            },
            guidelines=[{"text": g.text, "source": g.source} for g in guidance],
        )

        version.status = VersionStatus.REVIEWING
        await session.flush()

        result = await build_tailoring_graph(recorder).ainvoke(state)

        # The graph is done. Everything below is this module's job.
        proposed = list(result["items"])
        # Each entry pairs the Reviewer's finding with the pass that raised it
        # (`RaisedFinding`). The pairing was made in the review node — the one
        # place that knows which attempt is running — because stamping at
        # write time can only ever stamp the run's *final* attempt, which is
        # the defect T093 removes.
        raised = list(result["findings"])

        # Principle III, before anything is written.
        finalised = finalise(proposed, [entry.finding for entry in raised])

        by_source = {
            str(item.source_item_id): item
            for item in finalised.items
            if item.source_item_id is not None
        }

        # A proposal can only be applied to a line it names, so anything naming
        # nothing real is dropped — no fabricated id can reach a resume. But
        # dropping it *silently* makes "the model proposed nothing" and "the
        # model proposed things we could not place" the same observation, and
        # they need very different responses. That ambiguity is what let two
        # paid runs look like ordinary empty results.
        known = {str(item["source_item_id"]) for item in master_items}
        unplaceable = sorted(set(by_source) - known)
        missing_id = sum(1 for item in finalised.items if item.source_item_id is None)
        if unplaceable or missing_id:
            logger.warning(
                "proposals could not be placed against the master",
                extra={
                    "version_id": str(version_id),
                    # Counts and ids only — an id is ours, never model prose.
                    "unplaceable_ids": unplaceable,
                    "proposals_with_no_id": missing_id,
                    "proposals_total": len(finalised.items),
                },
            )

        rows: dict[str, ResumeVersionItem] = {}
        for master_item in master_items:
            source_id = str(master_item["source_item_id"])
            proposal = by_source.get(source_id)
            original = master_item["text"]
            row = ResumeVersionItem(
                resume_version_id=version.id,
                source_kind=master_item["source_kind"],
                source_item_id=master_item["source_item_id"],
                position=proposal.position if proposal else master_item["position"],
                # NULL when no proposal arrived — the only record that the
                # draft named this item, since a position-only or
                # inclusion-only proposal leaves `proposed_text` null too.
                # `position` above has already taken the proposed value, so
                # without this the master's ordering is gone for exactly the
                # items the draft touched (T095, FR-030).
                displaced_position=master_item["position"] if proposal else None,
                original_text=original,
                proposed_text=proposal.text if proposal else None,
                # Materialised rather than derived, so no later reader — the PDF
                # export above all — re-implements the rule and gets it wrong.
                final_text=(proposal.text if proposal and proposal.text else original),
                decision=ProposalDecision.PENDING,
                included=proposal.included if proposal else True,
            )
            session.add(row)
            rows[source_id] = row
        await session.flush()

        # Iterated as `raised` rather than `finalised.findings` because each
        # row needs the pass that raised it, and `finalise` echoes every
        # finding back unchanged — its docstring says so, and the guardrail
        # record surviving the discard is the point of that rule.
        for entry in raised:
            finding = entry.finding
            key = str(finding.source_item_id) if finding.source_item_id else None
            session.add(
                ReviewerFinding(
                    tailoring_run_id=run.id,
                    resume_version_item_id=rows[key].id if key and key in rows else None,
                    kind=finding.kind,
                    detail=finding.detail,
                    quoted_text=finding.quoted_text,
                    # The pass that raised this finding, not the run's final
                    # attempt — the run-level total is `run.attempts` below.
                    attempt=entry.attempt,
                )
            )

        run.plan = result["plan"]
        run.guidelines_used = state.guidelines
        run.attempts = result["attempt"]
        # Every review pass's confidence, in pass order. The final element is
        # what `confidence_score` below records; the earlier ones are what a
        # revised run's first judgement looked like — observability slice 007
        # measures against. Null on runs that predate the column: that history
        # was destroyed before persistence and is never reconstructed.
        run.review_confidences = [int(value) for value in result["confidences"]]
        await _record_usage(session, run, recorder)
        run.status = RunStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)

        version.confidence_score = result["confidence"]
        version.status = VersionStatus.AWAITING_APPROVAL
        await session.flush()

    except Exception as exc:
        # **The kind of failure to the owner, the detail to the log** — the rule
        # `health.py` established under T068, applied here because these two
        # columns are returned verbatim by two endpoints and rendered on screen.
        #
        # This was the wrong way round until T090's review, and the consequence
        # is not hypothetical: a `psycopg.OperationalError` stringifies to
        # `connection to server at "172.19.0.4", port 5432 failed: FATAL:
        # password authentication failed for user "careerhq"`. That is the
        # internal address, port and database user, written into a column the
        # interface renders in an alert box.
        #
        # `str(exc)` still exists, in the log, where an operator can read it and
        # a browser cannot. Losing it entirely would trade a disclosure for an
        # undebuggable failure, which is not a trade worth making — and on
        # Railway it must travel in `extra={}` regardless, because the platform
        # blanks the `message` field of parsed JSON logs.
        # `str(exc)` for most failures — but **never** for a pydantic
        # `ValidationError`, whose `__str__` embeds `input_value=`, and the
        # input is model output that may derive from a CV. Found during the
        # verification of this very fix: the gateway strips input from its own
        # log while this line was reinstating it one layer up, by a different
        # route. One extractor now serves both.
        structured = safe_validation_errors(exc)
        logger.warning(
            "tailoring run failed",
            extra={
                "version_id": str(version_id),
                "error": type(exc).__name__,
                "detail": structured if structured else str(exc),
            },
        )
        # The calls that ran were paid for whether or not the run finished.
        await _record_usage(session, run, recorder)
        run.status = RunStatus.FAILED
        run.failure_reason = type(exc).__name__
        run.finished_at = datetime.now(UTC)
        # Back to DRAFT, not to a `failed` status that does not exist. What is
        # left is an untailored resume plus a run explaining the attempt, and a
        # retry reuses this draft rather than creating another version.
        version.status = VersionStatus.DRAFT
        # One sentence, written for the person reading it and naming no
        # internals. **Deliberately just the fact.** The interface already says
        # what it means — that nothing was saved and the profile is untouched —
        # and a message repeating that puts the same reassurance on screen
        # twice, which reads as though something went wrong twice. The run's
        # `failure_reason` beside it carries the exception class, which is what
        # makes a support conversation possible without a stack trace.
        version.failure_reason = "The tailoring run stopped before it finished."
        await session.flush()


async def decide_item(
    session: AsyncSession,
    *,
    item: ResumeVersionItem,
    decision: ProposalDecision,
    text: str | None = None,
) -> ResumeVersionItem:
    """Record the owner's choice for one proposal (FR-024, FR-026, FR-027).

    Rejecting **triggers no AI work**. The version keeps what the master said,
    and re-running the whole tailoring is still available if the draft is
    broadly wrong.
    """
    # `==` throughout, never `is`. `decision` is an enum member when a route
    # passes one, but these columns are `String`, so anything read back from the
    # database is a plain `str` and the identity comparison silently never
    # matches. See `approve_version` below, where that is not hypothetical.
    if decision == ProposalDecision.ACCEPTED:
        item.final_text = item.proposed_text or item.original_text
    elif decision == ProposalDecision.REJECTED:
        item.final_text = item.original_text
    elif decision == ProposalDecision.EDITED:
        if not (text or "").strip():
            raise ValueError("an edited item needs text")
        item.final_text = text or ""

    item.decision = decision
    await session.flush()
    return item


async def approve_version(session: AsyncSession, *, version: ResumeVersion) -> ResumeVersion:
    """Confirm the draft (FR-025, FR-028).

    Every item still `PENDING` counts as accepted — the import-review precedent,
    where an untouched review adds everything not discarded. A second pattern
    for the same idea costs an affordance every time.

    **Starts nothing.** No AI work follows approval in this slice, which is
    precisely why the workflow needs no durable pause/resume.
    """
    for item in version.items:
        # `==`, not `is`. `decision` is a `String(16)` column, so an item loaded
        # by a route — a session that did not create the row — returns a plain
        # `str` and `is ProposalDecision.PENDING` is never true. Nothing raises;
        # approval simply accepts nothing and every item stays `pending`. That
        # is precisely the defect slice 004 shipped in `run_analysis` under a
        # green suite, and the tests missed it there for the same reason they
        # would here: they hold the session that wrote the row, whose identity
        # map still has the enum member.
        if item.decision == ProposalDecision.PENDING:
            item.decision = ProposalDecision.ACCEPTED
            item.final_text = item.proposed_text or item.original_text

    version.status = VersionStatus.READY
    await session.flush()
    return version


__all__ = [
    "ABANDONED_AFTER",
    "TailoringInFlight",
    "TailoringRefused",
    "approve_version",
    "check_preconditions",
    "create_pending_version",
    "decide_item",
    "is_abandoned",
    "run_tailoring",
]
