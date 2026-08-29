"""Turning persisted rows into the facts the metrics take.

**The only module in this package that touches the database**, so every metric
stays a pure function that can be developed and drilled without one. That split is
what lets the whole metric layer be exercised against the thirteen runs this
project has already paid for, before a benchmark case is billed.

**Reads only. Never writes.** FR-012: the harness adds rows through the runner and
modifies nothing, including the eight versions, thirteen runs, eight analyses and
one submission that cost $3.562567 and are the project's only evaluation evidence.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.evaluation.eligibility import RunProvenance
from careerhq.application.evaluation.metrics import (
    ClaimFacts,
    FindingRecord,
    GuidelineRecord,
    RequirementFacts,
)
from careerhq.application.evaluation.overhead import RunCost
from careerhq.domain.models import (
    MatchAnalysis,
    MatchRequirement,
    ResumeVersion,
    ResumeVersionItem,
    ReviewerFinding,
    TailoringRun,
)
from careerhq.domain.models.knowledge import KnowledgeDocument


async def read_claims(session: AsyncSession, version_id: uuid.UUID) -> list[ClaimFacts]:
    rows = (
        await session.scalars(
            sa.select(ResumeVersionItem).where(ResumeVersionItem.resume_version_id == version_id)
        )
    ).all()
    return [
        ClaimFacts(
            item_id=str(row.id),
            source_item_id=str(row.source_item_id) if row.source_item_id else None,
            proposed_text=row.proposed_text,
            original_text=row.original_text,
            final_text=row.final_text,
        )
        for row in rows
    ]


async def read_findings(session: AsyncSession, run_id: uuid.UUID) -> list[FindingRecord]:
    rows = (
        await session.scalars(
            sa.select(ReviewerFinding).where(ReviewerFinding.tailoring_run_id == run_id)
        )
    ).all()
    return [
        FindingRecord(
            item_id=str(row.resume_version_item_id) if row.resume_version_item_id else None,
            kind=str(row.kind),
            detail=row.detail,
            quoted_text=row.quoted_text,
        )
        for row in rows
    ]


async def read_requirements(
    session: AsyncSession, analysis_id: uuid.UUID
) -> list[RequirementFacts]:
    rows = (
        await session.scalars(
            sa.select(MatchRequirement)
            .where(MatchRequirement.analysis_id == analysis_id)
            .order_by(MatchRequirement.ordinal)
        )
    ).all()
    return [
        RequirementFacts(text=row.text_, must_have=str(row.kind) == "must_have") for row in rows
    ]


async def read_guidelines(session: AsyncSession, run: TailoringRun) -> list[GuidelineRecord]:
    """Join the run's snapshot back to the documents that produced it.

    **`source_type` is not in `guidelines_used` and must be looked up**, because
    `citation_snapshot` records what identifies a rule rather than how it was
    selected. Without the join there is no way to tell a pinned integrity rule from
    a semantically selected one — and reporting them together would count a floor
    as an achievement.

    A guideline with no `document_slug` came from the static rubric, which is a
    constant rather than a corpus chunk. It is reported as `static` rather than
    given an invented source type.
    """
    snapshot = run.guidelines_used or []
    slugs = {str(entry["document_slug"]) for entry in snapshot if entry.get("document_slug")}
    types: dict[str, str] = {}
    if slugs:
        rows = (
            await session.execute(
                sa.select(KnowledgeDocument.slug, KnowledgeDocument.source_type).where(
                    KnowledgeDocument.slug.in_(slugs)
                )
            )
        ).all()
        types = {row.slug: row.source_type for row in rows}

    records: list[GuidelineRecord] = []
    for entry in snapshot:
        slug = entry.get("document_slug")
        if not slug:
            records.append(GuidelineRecord(document_slug="", source_type="static"))
            continue
        records.append(
            GuidelineRecord(document_slug=str(slug), source_type=types.get(str(slug), "unknown"))
        )
    return records


#: What `StaticGuidelines` writes into every `Guideline.source` it produces.
#:
#: **A constant, and that is what makes it usable as evidence.** The static rubric
#: is code, so its provenance string is fixed; the corpus writes a citation
#: (`slug · locator · hash`) instead. Measured over all ten real runs carrying a
#: snapshot: seven record this exact prefix, three record citations. There is no
#: third shape and no overlap.
STATIC_RUBRIC_SOURCE = "CareerHQ house rubric"


def guidance_used(snapshot: list[dict[str, Any]] | None) -> str:
    """What guidance a run actually consumed: `corpus`, `static`, `mixed` or `none`.

    **Unambiguous, and it is the reason slice 007 needs no `guideline_source`
    column.** An earlier draft asked "what was this run *configured* with", which
    the record genuinely cannot answer — a snapshot with no content hashes is what
    a deliberately static run leaves behind *and* what a retrieval run that fell
    back leaves behind. That looked like a gap needing schema.

    It is not, because it is the wrong question. A metric describes what a run was
    advised by, not what someone intended it to be advised by: a run whose guidance
    came from the static rubric cannot support a retrieval claim **whatever it was
    configured with**. And *that* question the snapshot answers exactly —
    `citation_snapshot` writes the corpus citation for a retrieved rule and the
    rubric's constant for a static one.

    Fallback detection survives intact and needs no column either: the benchmark
    runner knows what it pointed a run at, records that in the result artifact, and
    a disagreement between the artifact and this function **is** the fallback.

    `mixed` is returned rather than a guess when a snapshot contains both, which
    nothing produces today — it would mean the retrieval path had changed shape,
    and inventing a winner would hide that.
    """
    if not snapshot:
        return "none"
    corpus = sum(1 for entry in snapshot if entry.get("content_hash"))
    static = sum(
        1 for entry in snapshot if str(entry.get("source", "")).startswith(STATIC_RUBRIC_SOURCE)
    )
    if corpus and not static:
        return "corpus"
    if static and not corpus:
        return "static"
    if corpus and static:
        return "mixed"
    return "unrecognised"


async def read_provenance(
    session: AsyncSession,
    run: TailoringRun,
    *,
    benchmark_profile_ids: set[uuid.UUID],
    guidance_intended: str | None = None,
) -> RunProvenance:
    """How a run was produced, from its own columns and its own snapshot.

    `guidance_intended` is supplied by a caller that knows — the benchmark runner
    does, from the result artifact. Historical runs pass `None`, and no fallback
    claim is then made about them in either direction.
    """
    version = await session.get(ResumeVersion, run.resume_version_id)
    return RunProvenance(
        run_id=str(run.id),
        used_fixture=bool(run.is_fixture),
        guidance_used=guidance_used(run.guidelines_used),
        guidance_intended=guidance_intended,
        model_config_used=dict(run.model_config_used or {}),
        profile_is_benchmark=(version is not None and version.profile_id in benchmark_profile_ids),
        status=str(run.status),
    )


async def read_run_costs(session: AsyncSession, *, include_fixture: bool = False) -> list[RunCost]:
    """The denominator sample: every real run's cost, and whether it revised.

    **This is why more pairs are not needed for the denominator.** Every completed
    run is already an observation of it, so the distribution the SC-008 methodology
    needs comes free with the benchmark rather than being bought.
    """
    stmt = sa.select(TailoringRun).where(TailoringRun.status == "succeeded")
    if not include_fixture:
        stmt = stmt.where(TailoringRun.is_fixture.is_(False))
    rows = (await session.scalars(stmt)).all()
    return [RunCost(run_id=str(r.id), cost=r.cost, revised=r.attempts > 0) for r in rows]


async def read_calibration_pairs(
    session: AsyncSession, ratings: dict[str, float]
) -> list[tuple[float, float]]:
    """Match scores paired with ratings, restricted to one criteria version.

    **Restricted deliberately.** A score computed under different weights is a
    different number wearing the same name, and `criteria_version` exists precisely
    so a calibration measurement cannot silently mix them.
    """
    if not ratings:
        return []
    rows = (
        await session.execute(
            sa.select(ResumeVersion.id, MatchAnalysis.overall_score, MatchAnalysis.criteria_version)
            .join(TailoringRun, TailoringRun.resume_version_id == ResumeVersion.id)
            .join(MatchAnalysis, MatchAnalysis.id == TailoringRun.match_analysis_id)
        )
    ).all()

    by_version: dict[str, list[tuple[float, float]]] = {}
    for version_id, score, criteria_version in rows:
        rating = ratings.get(str(version_id))
        if rating is None or score is None:
            continue
        by_version.setdefault(criteria_version, []).append((float(score), rating))

    if not by_version:
        return []
    return max(by_version.values(), key=len)


async def corpus_identity(session: AsyncSession) -> str:
    """A short fingerprint of the corpus a run retrieved against.

    Documents, chunks and the recorded embedding model — enough to notice that the
    corpus changed between two results, which is all a comparison needs to refuse.
    """
    documents = await session.scalar(sa.select(sa.func.count()).select_from(KnowledgeDocument))
    chunks = await session.scalar(sa.text("SELECT count(*) FROM knowledge_chunks"))
    models = (await session.scalars(sa.select(KnowledgeDocument.embedding_model).distinct())).all()
    named = sorted(m for m in models if m) or ["unknown"]
    return f"{documents}/{chunks}/{','.join(named)}"


async def read_run_summary(session: AsyncSession, run: TailoringRun) -> dict[str, Any]:
    """Everything one run contributes to a report, in one place."""
    version = await session.get(ResumeVersion, run.resume_version_id)
    return {
        "run_id": str(run.id),
        "version_id": str(run.resume_version_id),
        "status": str(run.status),
        "attempts": run.attempts,
        "cost": float(run.cost),
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "is_fixture": bool(run.is_fixture),
        "finalisation_rules_version": run.finalisation_rules_version,
        "review_confidences": run.review_confidences,
        "version_status": str(version.status) if version else None,
    }


__all__ = [
    "STATIC_RUBRIC_SOURCE",
    "corpus_identity",
    "guidance_used",
    "read_calibration_pairs",
    "read_claims",
    "read_findings",
    "read_guidelines",
    "read_provenance",
    "read_requirements",
    "read_run_costs",
    "read_run_summary",
]
