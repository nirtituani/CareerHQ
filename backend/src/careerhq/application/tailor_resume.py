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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from careerhq.application.agents.tailoring import build_tailoring_graph
from careerhq.application.agents.tailoring.state import TailoringState
from careerhq.application.finalisation_rules import FINALISATION_RULES_VERSION, finalise
from careerhq.application.guidelines import GuidelineQuery, GuidelineSource
from careerhq.application.ports import StructuredCompletion
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

    existing = await session.scalar(
        select(ResumeVersion).where(
            ResumeVersion.application_id == application.id,
            ResumeVersion.status.in_([VersionStatus.TAILORING, VersionStatus.REVIEWING]),
        )
    )
    if existing is not None:
        run = await session.scalar(
            select(TailoringRun).where(TailoringRun.resume_version_id == existing.id)
        )
        if run is not None and is_abandoned(run):
            # Release it rather than refusing. Slice 004 refused, three times,
            # and each recovery needed SQL by hand.
            run.status = RunStatus.ABANDONED
            run.finished_at = datetime.now(UTC)
            existing.status = VersionStatus.DRAFT
            existing.failure_reason = "The previous run stopped without finishing."
            await session.flush()
        else:
            raise TailoringInFlight("A tailoring run is already in progress for this job.")

    version = ResumeVersion(
        profile_id=profile.id,
        application_id=application.id,
        source_resume_profile_id=master.id,
        source_profile_updated_at=profile.updated_at,
        name=f"{application.job_title} — tailored",
        status=VersionStatus.TAILORING,
        # Assigned at construction. A lazy load on a freshly added object raises
        # MissingGreenlet when it is serialised, which slice 004 met as a 500.
        items=[],
    )
    session.add(version)
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
    """
    lines: list[str] = []
    items: list[dict[str, Any]] = []

    summaries = (
        (await session.execute(select(SummaryBlock).where(SummaryBlock.profile_id == profile_id)))
        .scalars()
        .all()
    )
    for index, summary in enumerate(summaries):
        lines.append(f"SUMMARY: {summary.text}")
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
        lines.append(f"ROLE: {experience.title} at {experience.company} ({experience.start_date})")
        for bullet in experience.bullets:
            lines.append(f"  - {bullet.text}")
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
            lines.append(f"{kind.value.upper()}: {text}")
            items.append(
                {
                    "source_kind": kind,
                    "source_item_id": row_id,
                    "position": index,
                    "text": text,
                }
            )

    return "\n".join(lines), items


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
    run = await session.scalar(
        select(TailoringRun).where(TailoringRun.resume_version_id == version_id)
    )
    if run is None:
        return

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

        result = await build_tailoring_graph(completion).ainvoke(state)

        # The graph is done. Everything below is this module's job.
        proposed = list(result["items"])
        findings = list(result["findings"])
        usage = list(result["usage"])

        # Principle III, before anything is written.
        finalised = finalise(proposed, findings)

        by_source = {
            str(item.source_item_id): item
            for item in finalised.items
            if item.source_item_id is not None
        }

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

        for finding in finalised.findings:
            key = str(finding.source_item_id) if finding.source_item_id else None
            session.add(
                ReviewerFinding(
                    tailoring_run_id=run.id,
                    resume_version_item_id=rows[key].id if key and key in rows else None,
                    kind=finding.kind,
                    detail=finding.detail,
                    quoted_text=finding.quoted_text,
                    attempt=result["attempt"],
                )
            )

        run.plan = result["plan"]
        run.guidelines_used = state.guidelines
        run.attempts = result["attempt"]
        run.input_tokens = sum(u.input_tokens for u in usage)
        run.output_tokens = sum(u.output_tokens for u in usage)
        run.cost = sum((u.cost for u in usage), start=run.cost)
        run.is_fixture = any(u.is_fixture for u in usage)
        run.status = RunStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)

        version.confidence_score = result["confidence"]
        version.status = VersionStatus.AWAITING_APPROVAL
        await session.flush()

    except Exception as exc:
        logger.warning(
            "tailoring run failed",
            extra={"version_id": str(version_id), "error": type(exc).__name__},
        )
        run.status = RunStatus.FAILED
        run.failure_reason = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(UTC)
        # Back to DRAFT, not to a `failed` status that does not exist. What is
        # left is an untailored resume plus a run explaining the attempt, and a
        # retry reuses this draft rather than creating another version.
        version.status = VersionStatus.DRAFT
        version.failure_reason = f"{type(exc).__name__}: {exc}"
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
