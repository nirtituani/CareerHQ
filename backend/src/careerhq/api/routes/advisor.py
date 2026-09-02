"""The Career Advisor's routes (contracts/advisor-api.md).

Ownership derives from the session — no endpoint accepts a client-supplied
user id — and every path here is enumerated by the 401 gate the moment it is
registered. Error rule throughout: the kind goes to the browser, the detail
to the log.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import func, select

from careerhq.api.deps import CompletionClient, CurrentUser, DbSession
from careerhq.application.advise_career import create_pending_run, is_abandoned, run_advisor
from careerhq.application.advisor_specifics import (
    ADVISOR_ACTION_RULES_VERSION,
    Specifics,
    assess,
    mix_of,
    recommend,
    resolve_specifics,
    specific_labels,
)
from careerhq.application.advisor_tiers import (
    ADVISOR_TIER_RULES_VERSION,
    SECTION_OF,
    classify,
    read_tier_evidence,
    topic_for,
)
from careerhq.application.ports import StructuredCompletion
from careerhq.domain.models import (
    USER_DISMISSED,
    AdvisorRun,
    AdvisorRunStatus,
    Application,
    CareerMemory,
    MatchAnalysis,
    MatchStatus,
    MemoryDisposition,
    MemoryStatus,
)
from careerhq.infrastructure.database import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/advisor", tags=["advisor"])

_ACTIVE_STATUSES = (MemoryStatus.ACTIVE, MemoryStatus.TENTATIVE)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _memory_out(
    memory: CareerMemory,
    last_disposition: MemoryDisposition | None = None,
    specifics: Specifics | None = None,
) -> dict[str, Any]:
    # Read-time tier: derived from the memory's own frozen evidence, never
    # stored. Orthogonal to the lifecycle status above it. The LLM's `priority`
    # only orders within a tier; the tier itself is deterministic.
    tier = classify(memory.evidence)
    tier_ev = read_tier_evidence(memory.evidence)
    # V2: the rows the frozen evidence points at, and the one next step they
    # support. `specifics` is None only where the caller does not resolve them
    # (the dismiss response); the mix then carries no rows and the taxonomy
    # answers with its honest refusal rather than a guess.
    mix = mix_of(specifics)
    action = recommend(tier, mix)
    return {
        "id": str(memory.id),
        "claim": memory.claim,
        "kind": memory.kind,
        "scope": {"kind": memory.scope_kind, "value": memory.scope_value},
        "status": memory.status,
        "priority": memory.priority,
        "priority_reason": memory.priority_reason,
        "tier": tier,
        "section": SECTION_OF[tier],
        "topic": topic_for(tier, memory.evidence, kind=memory.kind, scope_value=memory.scope_value),
        "counts": (
            {
                "occurrences": tier_ev.occurrences,
                "coverage": tier_ev.coverage,
                "gaps": tier_ev.gaps,
            }
            if tier_ev.is_skill
            else None
        ),
        "specifics": [
            {
                "requirement_id": str(item.requirement_id),
                "text": item.text,
                "verdict": item.verdict,
                "shortfall": item.shortfall,
                "importance": item.importance,
                "profile_quote": item.profile_quote,
                "resolved": item.resolved,
            }
            for item in (specifics.items if specifics else [])
        ],
        "specific_labels": specific_labels(specifics) if specifics else [],
        "profile_quotes": specifics.profile_quotes if specifics else [],
        "specifics_unresolved": specifics.unresolved if specifics else 0,
        "assessment": assess(tier, mix),
        "action": ({"category": action.category, "text": action.text} if action else None),
        "evidence": memory.evidence,
        "created_at": _iso(memory.created_at),
        "last_confirmed_at": _iso(memory.last_confirmed_at),
        "supersedes_id": str(memory.supersedes_id) if memory.supersedes_id else None,
        "recreates_dismissed_id": (
            str(memory.recreates_dismissed_id) if memory.recreates_dismissed_id else None
        ),
        "retired_reason": memory.retired_reason,
        "last_disposition": (
            {
                "action": last_disposition.action,
                "run_id": str(last_disposition.run_id),
                "reason": last_disposition.reason,
                "evidence_delta": last_disposition.evidence_delta,
            }
            if last_disposition
            else None
        ),
    }


def _run_out(run: AdvisorRun, *, include_dispositions: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(run.id),
        "status": run.status,
        "error": run.error,
        "rules_version": run.rules_version,
        "ops": (
            {
                "proposed": run.ops_proposed,
                "applied": run.ops_applied,
                "discarded": run.ops_discarded,
            }
            if run.ops_proposed is not None
            else None
        ),
        "models": {"grouping": run.grouping_model, "reason": run.reason_model},
        "cost": str(run.cost) if run.cost is not None else None,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "is_fixture": run.is_fixture,
        "created_at": _iso(run.created_at),
        "completed_at": _iso(run.completed_at),
    }
    if include_dispositions and run.status == AdvisorRunStatus.READY:
        out["dispositions"] = [
            {
                "memory_id": str(d.memory_id),
                "action": d.action,
                "reason": d.reason,
                "evidence_delta": d.evidence_delta,
            }
            for d in run.dispositions
        ]
    return out


async def _coverage(session: DbSession, user_id: uuid.UUID) -> dict[str, Any]:
    """FR-011's honest denominators, always present — the page renders the
    insufficient-data answer from this, spending nothing."""
    total = await session.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == user_id)
    )
    analysed = await session.scalar(
        select(func.count(func.distinct(MatchAnalysis.application_id)))
        .select_from(MatchAnalysis)
        .join(Application, Application.id == MatchAnalysis.application_id)
        .where(
            Application.user_id == user_id,
            MatchAnalysis.status == MatchStatus.READY,
        )
    )
    return {
        "applications": total or 0,
        "analysed": analysed or 0,
        "message": "Skill-level patterns grow as applications get match analyses.",
    }


@router.get("", summary="The advisor page's single read")
async def read_advisor(session: DbSession, user: CurrentUser) -> dict[str, Any]:
    memories = list(
        (
            await session.scalars(
                select(CareerMemory)
                .where(
                    CareerMemory.user_id == user.id,
                    CareerMemory.status.in_(_ACTIVE_STATUSES),
                )
                .order_by(
                    CareerMemory.priority.desc().nulls_last(),
                    CareerMemory.last_confirmed_at.desc(),
                )
            )
        ).all()
    )
    latest_run = await session.scalar(
        select(AdvisorRun)
        .where(AdvisorRun.user_id == user.id)
        .order_by(AdvisorRun.created_at.desc())
        .limit(1)
    )
    history = {
        status_value: await session.scalar(
            select(func.count())
            .select_from(CareerMemory)
            .where(CareerMemory.user_id == user.id, CareerMemory.status == status_value)
        )
        or 0
        for status_value in (MemoryStatus.SUPERSEDED, MemoryStatus.RETIRED)
    }

    last_by_memory: dict[uuid.UUID, MemoryDisposition] = {}
    if memories:
        rows = (
            await session.scalars(
                select(MemoryDisposition)
                .where(MemoryDisposition.memory_id.in_([m.id for m in memories]))
                .order_by(MemoryDisposition.created_at)
            )
        ).all()
        for row in rows:
            last_by_memory[row.memory_id] = row

    # One batched, ownership-filtered resolution for the whole page: a
    # per-memory query would put the page's cost on the number of memories.
    specifics = await resolve_specifics(
        session,
        user_id=user.id,
        evidence_by_memory={m.id: m.evidence for m in memories},
    )

    # `memories[]` is preserved for backward compatibility; `sections` is the
    # topic-first grouping the refined UI reads. Both are the same rows, only
    # partitioned by the derived tier's section — priority order within each is
    # kept from the query above.
    rendered = [_memory_out(m, last_by_memory.get(m.id), specifics.get(m.id)) for m in memories]
    sections: dict[str, list[dict[str, Any]]] = {
        "recommended": [],
        "emerging": [],
        "strengths": [],
        "portfolio": [],
        "data_notes": [],
    }
    for item in rendered:
        sections[item["section"]].append(item)

    return {
        "memories": rendered,
        "sections": sections,
        "tier_rules_version": ADVISOR_TIER_RULES_VERSION,
        "action_rules_version": ADVISOR_ACTION_RULES_VERSION,
        "coverage": await _coverage(session, user.id),
        "latest_run": _run_out(latest_run, include_dispositions=True) if latest_run else None,
        "history_counts": {
            "superseded": history[MemoryStatus.SUPERSEDED],
            "retired": history[MemoryStatus.RETIRED],
        },
    }


async def _advise_in_background(run_id: uuid.UUID, completion: StructuredCompletion) -> None:
    """Own session: the request's is closed by the time this runs. Lives in
    the API layer so `application/` imports no infrastructure."""
    async with get_session_factory()() as session:
        await run_advisor(session, run_id=run_id, completion=completion)
        await session.commit()


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, summary="Request an analysis")
async def trigger_run(
    background: BackgroundTasks,
    session: DbSession,
    user: CurrentUser,
    completion: CompletionClient,
) -> dict[str, Any]:
    """No request body — a model or rules version accepted from the client
    would put cost and behaviour under the browser's control."""
    in_flight = await session.scalar(
        select(AdvisorRun).where(
            AdvisorRun.user_id == user.id,
            AdvisorRun.status == AdvisorRunStatus.PENDING,
        )
    )
    if in_flight is not None and is_abandoned(in_flight):
        # Reaped, not honoured — otherwise the row blocks every future run.
        in_flight.status = AdvisorRunStatus.FAILED
        in_flight.error = "The analysis stopped before it finished."
        in_flight.completed_at = datetime.now(UTC)
        await session.flush()
    elif in_flight is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An analysis is already running."
        )

    run = await create_pending_run(session, user)
    if run is None:
        # Well-formed request; there is simply nothing to analyse. Distinct
        # detail from the in-flight 409, and no run row was spent.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="There is no application history to analyse yet.",
        )

    await session.commit()
    background.add_task(_advise_in_background, run.id, completion)
    return {"state": "running", "run": _run_out(run)}


@router.get("/runs/{run_id}", summary="Poll one run")
async def read_run(run_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    run = await session.scalar(
        select(AdvisorRun).where(AdvisorRun.id == run_id, AdvisorRun.user_id == user.id)
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such run.")
    return _run_out(run, include_dispositions=True)


@router.get("/memories/{memory_id}", summary="One memory with lineage")
async def read_memory(
    memory_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    memory = await session.scalar(
        select(CareerMemory).where(CareerMemory.id == memory_id, CareerMemory.user_id == user.id)
    )
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such memory.")

    # Walk the supersession chain to the root. Bounded by run count, so a
    # plain loop; each hop is ownership-filtered by the user_id above having
    # matched the head (lineage never crosses users — same-user FKs).
    lineage: list[CareerMemory] = []
    cursor = memory
    while cursor.supersedes_id is not None:
        predecessor = await session.scalar(
            select(CareerMemory).where(
                CareerMemory.id == cursor.supersedes_id,
                CareerMemory.user_id == user.id,
            )
        )
        if predecessor is None:
            break
        lineage.append(predecessor)
        cursor = predecessor

    dispositions = list(
        (
            await session.scalars(
                select(MemoryDisposition)
                .where(MemoryDisposition.memory_id == memory_id)
                .order_by(MemoryDisposition.created_at)
            )
        ).all()
    )

    # The head memory resolves its rows; lineage entries stay lean — they are
    # history, read for how the understanding changed, not for today's advice.
    head_specifics = (
        await resolve_specifics(
            session, user_id=user.id, evidence_by_memory={memory.id: memory.evidence}
        )
    ).get(memory.id)

    return {
        "memory": _memory_out(memory, None, head_specifics),
        "lineage": [_memory_out(m) for m in lineage],
        "dispositions": [
            {
                "run_id": str(d.run_id),
                "action": d.action,
                "reason": d.reason,
                "evidence_delta": d.evidence_delta,
                "created_at": _iso(d.created_at),
            }
            for d in dispositions
        ],
    }


@router.post("/memories/{memory_id}/dismiss", summary="Dismiss a memory")
async def dismiss_memory(
    memory_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    memory = await session.scalar(
        select(CareerMemory).where(CareerMemory.id == memory_id, CareerMemory.user_id == user.id)
    )
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such memory.")
    # `==` semantics: this row came from this request's session, but the rule
    # is uniform — and terminal rows refuse re-termination as well as
    # resurrection.
    if memory.status not in ("active", "tentative"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an active memory can be dismissed.",
        )

    memory.status = MemoryStatus.RETIRED
    memory.retired_reason = USER_DISMISSED
    await session.commit()
    logger.info(
        "memory dismissed by the user",
        extra={"memory_id": str(memory_id), "user_id": str(user.id)},
    )
    return {"memory": _memory_out(memory)}
