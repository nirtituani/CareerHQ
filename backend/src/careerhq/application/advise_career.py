"""The Career Advisor use case: reserve a run, execute it, apply what survives.

The lifecycle is `analyze_match.py`'s, deliberately (research.md D1): a
`pending` row committed before any provider call — so the interface has
something to poll and a failure has somewhere to record itself — one in flight
per **user** enforced by a partial unique index where it cannot be raced, and
an abandonment deadline so a process restart mid-run cannot strand the feature
behind a 409 forever (that lesson cost hand-written SQL three times).

The pipeline itself is linear and owns everything (research.md D13 — no
LangGraph: there is no conditional edge and no revision loop):

    evidence pack (deterministic) -> [grouping? Haiku] -> counting ->
    reasoning (Sonnet) -> grounding gate -> one transaction

The model is never the source of a number; `advisor_evidence.py` is. The gate
in `advisor_grounding.py` discards what it cannot verify before anything is
persisted, and everything that survives — memory inserts, status transitions,
disposition rows, the run's own completion — commits together, so a failure
anywhere leaves the memory set byte-for-byte unchanged (SC-005).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.advisor_rules import ADVISOR_RULES_VERSION, RUN_ABANDONED_AFTER
from careerhq.domain.models import Application, AdvisorRun, AdvisorRunStatus, User

logger = logging.getLogger(__name__)

#: Task names, resolved to models by `model_for_task` — configuration, never a
#: branch (docs/08 §3.2.3). Both have explicit `llm_model_*` entries; the
#: fallback is Opus and says nothing while it overcharges.
GROUPING_TASK = "advisor_grouping"
REASON_TASK = "advisor_reason"


def is_abandoned(run: AdvisorRun, *, now: datetime | None = None) -> bool:
    """Whether a `pending` row has outlived any completion that could finish it.

    Generous on purpose: a run is at most two completions, and an over-eager
    deadline would let two real runs race. Compares status with ``==`` — a row
    from a fresh session holds a plain string, and ``is`` against the enum
    member silently never matches (shipped twice).
    """
    if run.status != AdvisorRunStatus.PENDING:
        return False
    started = run.created_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - started > RUN_ABANDONED_AFTER


async def create_pending_run(session: AsyncSession, user: User) -> AdvisorRun | None:
    """Reserve a row for the run, or decline because there is nothing to read.

    Returns `None` for a user with no applications at all: the spec's
    no-history rule is that the honest empty state costs nothing — no run row,
    no completion, nothing for a poller to watch fail.

    The one-in-flight rule is **not** checked here: the partial unique index
    is the enforcement, and the caller's flush is where a lost race surfaces.
    An application-level pre-check would be the raceable copy of it.
    """
    application_count = await session.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == user.id)
    )
    if not application_count:
        logger.info(
            "advisor run declined",
            extra={"user_id": str(user.id), "reason": "no_history"},
        )
        return None

    run = AdvisorRun(
        user_id=user.id,
        status=AdvisorRunStatus.PENDING,
        rules_version=ADVISOR_RULES_VERSION,
        dispositions=[],
    )
    session.add(run)
    await session.flush()
    return run
