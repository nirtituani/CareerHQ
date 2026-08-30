"""Two windows over research age, answering two unrelated questions (OQ-E).

One threshold was doing both jobs and they pull in opposite directions:

**Reuse — 30 days.** Do we spend on a fresh Layer 1? Being wrong means briefing
someone with stale facts before an interview, to save about $0.06.

**Stale — 90 days.** Do we warn the reader? Being wrong means hiding research
that is still useful, or crying wolf on research that is fine.

**Reuse takes the shorter window** because the saving is small and the downside
is not — cheap insurance. **Display takes the longer one** because old research
stays useful when honestly labelled: three-month-old research "is still useful,
but it must be visibly three months old rather than silently wrong."

**They are read at different times against different inputs, and that is what
stops them collapsing back into one.** Reuse is a *write-time* decision about
Layer 1's own `retrieved_at`. Staleness is a *read-time* label over
`effective_retrieved_at`, which for Layer 2 is the older of its own timestamp and
its Layer 1's (FR-033).

**Reuse applies to Layer 1 only.** Layer 2 is application-scoped and is never
reused across applications, so asking whether to reuse one is a question with no
caller.

**The staleness label is derived and never stored** (approved decision B).
Changing `RESEARCH_STALE_DAYS` therefore re-classifies existing snapshots, and
that is intended: slice 004's rule against editing a threshold in place protects
*stored* scores, where a silent reinterpretation rewrites what a person was told.
This is a live judgement about how old a row is today, and a row does keep
ageing.

**A reuse leaves no audit row** (approved decision A). Nothing re-ran, so FR-011
does not apply; what records the decision is Layer 2's lineage — which Layer 1 it
used, and that snapshot's `retrieved_at`. Slice 007 can recompute what any window
would have decided from those two facts, which is why
`RESEARCH_REUSE_VERSION` needs no column.

**Both are versioned reasoned guesses, not measurements** — the same posture as
slice 005's `CONFIDENCE_THRESHOLD`: "a placeholder with a version number, which is
the only kind of placeholder that does not rot silently." Changing either value
is a version bump.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime, timedelta

#: Beyond this, re-run Layer 1 rather than reuse it.
RESEARCH_REUSE_VERSION = "v1-30d"
RESEARCH_REUSE_DAYS = 30

#: Beyond this, mark visibly — never hide.
RESEARCH_STALE_VERSION = "v1-90d"
RESEARCH_STALE_DAYS = 90


class Freshness(enum.StrEnum):
    """How a snapshot should be presented, never how it should be trusted.

    `STALE` does not mean wrong. What actually ages is the perishable end of a
    brief — funding, headcount, leadership, hiring focus — while what a company
    fundamentally does moves in years. Citations do not age at all: excerpts are
    verified verbatim at write time (FR-032), so a source 404ing later
    invalidates nothing already stored.
    """

    FRESH = "fresh"
    STALE = "stale"


def _aware(moment: datetime) -> datetime:
    """PostgreSQL hands back an aware datetime; a hand-built one may not be.

    Comparing the two raises `TypeError`, which would surface from a display
    path as a 500 on a page that merely wanted to show a date.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def effective_retrieved_at(
    *, role_retrieved_at: datetime, company_retrieved_at: datetime | None
) -> datetime:
    """FR-033 — a Layer 2 brief is only as fresh as what it rests on.

    Returns the **older** of the two. A role analysis written this morning on top
    of company research from a year ago is not fresh, and presenting it as fresh
    is the "silently wrong" failure the product notes warn against.

    A `None` company timestamp means no Layer 1 was recorded. That cannot make
    the brief *fresher* than its own timestamp, so the role's own time stands —
    deliberately not treated as infinitely stale, because a missing lineage and
    an aged one need different fixes and must not look alike.
    """
    role = _aware(role_retrieved_at)
    if company_retrieved_at is None:
        return role
    return min(role, _aware(company_retrieved_at))


def is_reusable(retrieved_at: datetime, *, now: datetime | None = None) -> bool:
    """Whether a Layer 1 snapshot is fresh enough to skip a re-run (Layer 1 only).

    Boundary: exactly `RESEARCH_REUSE_DAYS` old is still reusable. The window is
    a reasoned guess, so spending money on the strictest reading of its own edge
    would be false precision.
    """
    moment = now or datetime.now(UTC)
    return moment - _aware(retrieved_at) <= timedelta(days=RESEARCH_REUSE_DAYS)


def freshness(retrieved_at: datetime, *, now: datetime | None = None) -> Freshness:
    """How to label a snapshot of this age. Derived at read time, never stored.

    Callers pass `effective_retrieved_at()` for a Layer 2 brief and the row's own
    `retrieved_at` for Layer 1 — the distinction is FR-033's and belongs to the
    caller, because only it knows which layer it is holding.
    """
    moment = now or datetime.now(UTC)
    if moment - _aware(retrieved_at) > timedelta(days=RESEARCH_STALE_DAYS):
        return Freshness.STALE
    return Freshness.FRESH


__all__ = [
    "RESEARCH_REUSE_DAYS",
    "RESEARCH_REUSE_VERSION",
    "RESEARCH_STALE_DAYS",
    "RESEARCH_STALE_VERSION",
    "Freshness",
    "effective_retrieved_at",
    "freshness",
    "is_reusable",
]
