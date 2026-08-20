"""Score one job against the profile (User Story 1).

The **third** `complete()` call site. Like the other two it does not loop, use
tools, or react to its own previous output — which is the line T096's amended
scope guard actually protects.

Split in two on purpose:

* `create_pending_analysis` runs in the same transaction as the application, so
  a background run is visible rather than mysterious. The interface has
  something to show a spinner against and a failure has somewhere to land
  instead of leaving a blank forever.
* `run_analysis` is the background half. It never raises into the caller: a
  fire-and-forget task has nowhere to raise *to*, so every failure is recorded
  on the row instead.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from careerhq.application.match_criteria import (
    CRITERIA_VERSION,
    Judged,
    band_for,
    overall_score,
)
from careerhq.application.ports import StructuredCompletion
from careerhq.domain.models import (
    Application,
    Certification,
    ContactInformation,
    Education,
    Language,
    MatchAnalysis,
    MatchRequirement,
    MatchStatus,
    MilitaryService,
    ProfessionalProfile,
    ProfessionalTitle,
    Project,
    RequirementKind,
    RequirementVerdict,
    Shortfall,
    Skill,
    SummaryBlock,
    VolunteerExperience,
    WorkExperience,
)
from careerhq.domain.schemas.match import MatchJudgement

logger = logging.getLogger(__name__)

TASK = "match_analysis"

#: Postings run 2,400-4,500 tokens and profiles about 760, so this is generous
#: rather than tight. Truncation is at the **end** and is recorded: requirements
#: cluster in the second half of a posting, so trimming from the middle would
#: drop exactly what is being scored, invisibly (P1).
MAX_POSTING_CHARS = 40_000

_TRUNCATED = "\n\n[posting truncated]"

_PROMPT = """You are assessing how well one person's professional profile fits one job.

Rules, in order of importance:

1. Judge only against the profile below. Never assert experience it does not
   contain, and never assert an absence it does not demonstrate.
2. Every verdict except `unverified` must quote the profile in `evidence`,
   worded as the profile words it.
   - `confirmed` — the profile directly shows it.
   - `partial` — the profile shows some of it (three years against a five-year ask).
   - `transferable` — the same capability in another context. Say what transfers.
   - `gap` — the profile shows the person FALLS SHORT. Quote the text that shows
     the shortfall. If you cannot quote anything, this is not a gap.
   - `unverified` — the profile says nothing either way. Carries no evidence.
3. Silence is `unverified`, never `gap`. A profile that does not mention a
   requirement has not been shown to fail it. This is the most common mistake:
   do not turn "not mentioned" into "does not have".
4. Use all five verdicts. Most real profiles are mostly `partial`,
   `transferable` and `unverified`. A judgement that is only `confirmed` and
   `gap` is wrong.
5. `transferable` is not `confirmed`. Do not present adjacent experience as
   direct experience.
6. Copy each requirement as the posting worded it. Do not paraphrase or merge.
7. `partial`, `transferable` and `gap` state a `shortfall`: `wording` (the
   profile has it but words it differently), `evidence` (plausible but
   unproven), or `capability` (genuinely not there). `confirmed` and
   `unverified` carry NO shortfall — the first has nothing to explain, and the
   second has nothing to explain it with. Do not guess why a profile is silent.
8. Rate each requirement's `importance` from 0 to 100 — how much it really
   matters to this recruiter for this role. **Do not read it off the heading.**
   A "must have" list is often a wishlist and a "nice to have" is sometimes the
   whole job. Judge from how the posting is written:
   - Requirements stated EARLIER matter more. Recruiters lead with what they
     care about and pad the end.
   - Repeated across sections, named in the job title, or restated in the
     summary — that is the core of the role.
   - Tied to what the team actually does, versus generic to any job at this
     level (communication, teamwork, "fast-paced environment").
   - Specific and checkable ("5 years of Kubernetes in production") versus
     boilerplate ("passion for technology").

   Anchor the scale:
   - 80-100 — the role is *about* this. Remove it and it is a different job.
   - 60-79 — clearly required; a candidate without it is a hard sell.
   - 40-59 — expected, but would not decide the hire on its own.
   - 0-39  — nice to have, boilerplate, or legal/EEO text.

   Most postings have only two to five requirements above 80. If you rate ten
   that way, you have taken the heading at face value instead of judging.

Rate four dimensions from 0 to 100:
- `direct`: same capability, same domain, comparable scale.
- `transferable`: the same capability in a different context.
- `adjacent`: touched as a secondary responsibility, or related tooling.
- `impact`: the kind of outcome this posting values.

`verdict` is one sentence a person can act on.

Do not return an overall score; it is computed from the four dimensions.

=== PROFILE ===
{profile}

=== JOB POSTING ===
{posting}
"""


def _line(*parts: object) -> str:
    return " · ".join(str(p) for p in parts if p)


async def _render_profile(session: AsyncSession, profile_id: uuid.UUID) -> str:
    """The whole profile as plain text.

    Everything, not a selection. The feature's central question is *which
    requirements do I lack*, which can only be answered by seeing all of it — a
    missing bullet becomes an invented gap, silently (research.md R4).
    """

    async def _rows[M](model: type[M], owner: object) -> list[M]:
        return list(await session.scalars(select(model).where(owner == profile_id)))  # type: ignore[arg-type]

    out: list[str] = []

    for contact in await _rows(ContactInformation, ContactInformation.profile_id):
        out.append(_line(contact.full_name, contact.location))
    for title in await _rows(ProfessionalTitle, ProfessionalTitle.profile_id):
        out.append(_line(title.title))
    for summary in await _rows(SummaryBlock, SummaryBlock.profile_id):
        out.append(summary.text)

    roles = list(
        await session.scalars(
            select(WorkExperience)
            .where(WorkExperience.profile_id == profile_id)
            .options(selectinload(WorkExperience.bullets))
        )
    )
    if roles:
        out.append("\nEXPERIENCE")
        for role in roles:
            dates = _line(role.start_date, role.end_date or ("present" if role.is_current else ""))
            out.append(_line(role.title, role.company, role.location, dates))
            out.extend(f"  - {bullet.text}" for bullet in role.bullets)

    skills = await _rows(Skill, Skill.profile_id)
    if skills:
        out.append("\nSKILLS")
        out.append(", ".join(_line(s.name) for s in skills))

    projects = await _rows(Project, Project.profile_id)
    if projects:
        out.append("\nPROJECTS")
        out.extend(_line(p.name, p.description, p.url) for p in projects)

    education = await _rows(Education, Education.profile_id)
    if education:
        out.append("\nEDUCATION")
        out.extend(
            _line(e.qualification, e.field_of_study, e.institution, e.start_date, e.end_date)
            for e in education
        )

    certifications = await _rows(Certification, Certification.profile_id)
    if certifications:
        out.append("\nCERTIFICATIONS")
        out.extend(_line(c.name, c.issuer, c.year) for c in certifications)

    languages = await _rows(Language, Language.profile_id)
    if languages:
        out.append("\nLANGUAGES")
        out.append(", ".join(_line(x.name, x.proficiency) for x in languages))

    service = await _rows(MilitaryService, MilitaryService.profile_id)
    if service:
        out.append("\nMILITARY SERVICE")
        out.extend(_line(m.role, m.branch, m.start_date, m.end_date, m.details) for m in service)

    volunteering = await _rows(VolunteerExperience, VolunteerExperience.profile_id)
    if volunteering:
        out.append("\nVOLUNTEERING")
        out.extend(
            _line(v.role, v.organisation, v.start_date, v.end_date, v.description)
            for v in volunteering
        )

    return "\n".join(line for line in out if line.strip())


async def create_pending_analysis(
    session: AsyncSession, application: Application
) -> MatchAnalysis | None:
    """Reserve a row for the run, or decline to score.

    Returns `None` when there is nothing to score against, which is a state the
    interface renders as ordinary rather than as an error (FR-006):

    * `requirements is None` — a **legacy row**. No posting was ever captured;
      `job_description` holds a joined requirements list. Scoring it would
      compare the profile against that list while the prompt claims to read a
      whole posting, and the resulting number would look entirely normal
      (research.md R1).
    * `requirements == []` — the posting was read and stated none. An analysis
      against an empty requirement list returns a number with nothing behind it.
    """
    if not application.requirements:
        logger.info(
            "match analysis declined",
            extra={
                "application_id": str(application.id),
                "reason": "legacy_row" if application.requirements is None else "no_requirements",
            },
        )
        return None

    analysis = MatchAnalysis(
        application_id=application.id,
        status=MatchStatus.PENDING,
        criteria_version=CRITERIA_VERSION,
        # Initialised, not left to be fetched. A pending analysis has no
        # requirements by definition, and on a freshly added object the
        # relationship is unloaded — so reading it would attempt a lazy load,
        # which async SQLAlchemy cannot do outside an awaited context. Assigning
        # here marks the collection loaded, so serialising the row for the 202
        # response does no IO.
        requirements=[],
    )
    session.add(analysis)
    await session.flush()
    return analysis


async def run_analysis(
    session: AsyncSession, *, analysis_id: uuid.UUID, completion: StructuredCompletion
) -> None:
    """Fill in a pending analysis. Never raises.

    A background task has nowhere to raise to, so a failure that escaped here
    would leave the row `pending` forever — the one outcome the pending row
    exists to prevent.
    """
    analysis = await session.get(MatchAnalysis, analysis_id)
    # `==`, never `is`. `status` is a `String(16)` column, so a row loaded in a
    # fresh session — which is exactly what the background task does — returns
    # the plain string `'pending'`, and `is` matches the enum member only.
    #
    # This was a real total failure, not a hypothetical: the guard read `is not
    # MatchStatus.PENDING`, which is always true for a string, so every real
    # analysis returned here and sat `pending` forever. Nothing raised, nothing
    # logged, and the suite stayed green because every test passed the session
    # that created the row, whose identity map still held the enum member.
    if analysis is None or analysis.status != MatchStatus.PENDING:
        # Completed after its application was deleted, or already finished.
        return

    application = await session.get(Application, analysis.application_id)
    if application is None:
        return

    profile = await session.scalar(
        select(ProfessionalProfile).where(ProfessionalProfile.user_id == application.user_id)
    )
    if profile is None:
        await _fail(session, analysis, "No profile to score against.")
        return

    try:
        posting = (application.job_description or "").strip()
        if len(posting) > MAX_POSTING_CHARS:
            posting = posting[:MAX_POSTING_CHARS] + _TRUNCATED

        result = await completion.complete(
            task=TASK,
            schema=MatchJudgement,
            prompt=_PROMPT.format(
                profile=await _render_profile(session, profile.id), posting=posting
            ),
        )
    except Exception as exc:  # Recorded on the row, never re-raised — see the docstring.
        logger.warning(
            "match analysis failed",
            extra={"analysis_id": str(analysis_id), "error": exc.__class__.__name__},
        )
        await _fail(session, analysis, "The analysis could not be completed.")
        return

    judgement = result.value
    verdicts = [
        Judged(
            kind=RequirementKind(r.kind),
            verdict=RequirementVerdict(r.verdict),
            importance=r.importance,
        )
        for r in judgement.requirements
    ]
    score = overall_score(
        judgement.direct, judgement.transferable, judgement.adjacent, judgement.impact
    )

    analysis.overall_score = score
    analysis.band = band_for(score, requirements=verdicts)
    # Kept, not discarded once summed: they are what lets the interface say
    # where the number came from instead of asserting it.
    analysis.direct = judgement.direct
    analysis.transferable = judgement.transferable
    analysis.adjacent = judgement.adjacent
    analysis.impact = judgement.impact
    analysis.verdict = judgement.verdict
    analysis.status = MatchStatus.READY
    analysis.completed_at = datetime.now(UTC)

    # Principle V: the audit record lands in the same transaction as the work it
    # paid for. Infrastructure returns usage; it never logs it itself (O4).
    analysis.model = result.usage.model
    analysis.input_tokens = result.usage.input_tokens
    analysis.output_tokens = result.usage.output_tokens
    analysis.cost = result.usage.cost
    analysis.is_fixture = result.usage.is_fixture

    for ordinal, judged in enumerate(judgement.requirements):
        session.add(
            MatchRequirement(
                analysis_id=analysis.id,
                ordinal=ordinal,
                text_=judged.text,
                kind=RequirementKind(judged.kind),
                importance=judged.importance,
                verdict=RequirementVerdict(judged.verdict),
                shortfall=Shortfall(judged.shortfall) if judged.shortfall else None,
                evidence=judged.evidence,
            )
        )

    # Last, and only now: a failed run must leave the previous score standing.
    application.current_match_analysis_id = analysis.id
    await session.flush()

    logger.info(
        "match analysis ready",
        extra={
            "analysis_id": str(analysis.id),
            "score": score,
            "band": analysis.band,
            "model": result.usage.model,
            "cost": str(result.usage.cost),
        },
    )


async def _fail(session: AsyncSession, analysis: MatchAnalysis, reason: str) -> None:
    """Record the failure on the row. The pointer is deliberately not touched."""
    analysis.status = MatchStatus.FAILED
    analysis.error = reason
    analysis.completed_at = datetime.now(UTC)
    await session.flush()


__all__ = ["MAX_POSTING_CHARS", "TASK", "create_pending_analysis", "run_analysis"]
