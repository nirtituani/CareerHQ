"""The two windows over research age (OQ-E), and why they are two.

Every boundary here is a decision rather than an arithmetic fact, so each is
asserted at the edge: a window whose behaviour at exactly 30 or exactly 90 days
is unstated is a window two readers will implement differently.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from careerhq.application.research_windows import (
    RESEARCH_REUSE_DAYS,
    RESEARCH_REUSE_VERSION,
    RESEARCH_STALE_DAYS,
    RESEARCH_STALE_VERSION,
    Freshness,
    effective_retrieved_at,
    freshness,
    is_reusable,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


# -- the two windows are different, and that is the point -------------------


def test_the_two_windows_are_not_the_same_number() -> None:
    """OQ-E's whole finding: one threshold was doing two unrelated jobs.

    If these ever converge, the split has been undone by someone tidying up.
    """
    assert RESEARCH_REUSE_DAYS < RESEARCH_STALE_DAYS, (
        "reuse must take the shorter window — it decides spend, where being wrong "
        "means briefing someone with stale facts to save about $0.06"
    )


def test_both_windows_are_versioned() -> None:
    """A threshold without a version rots silently. Changing either value is a
    version bump, never an edit."""
    assert str(RESEARCH_REUSE_DAYS) in RESEARCH_REUSE_VERSION
    assert str(RESEARCH_STALE_DAYS) in RESEARCH_STALE_VERSION


# -- reuse: a write-time decision about spend -------------------------------


def test_recent_research_is_reused() -> None:
    assert is_reusable(_ago(1), now=NOW)


def test_research_past_the_reuse_window_is_not_reused() -> None:
    assert not is_reusable(_ago(RESEARCH_REUSE_DAYS + 1), now=NOW)


def test_the_reuse_boundary_is_inclusive() -> None:
    """Exactly at the window is still reusable. The number is a reasoned guess,
    so spending money on the strictest reading of its own edge is false
    precision."""
    assert is_reusable(_ago(RESEARCH_REUSE_DAYS), now=NOW)


def test_research_inside_the_reuse_window_is_still_labelled_fresh() -> None:
    """The windows must not be read off each other: reusable and fresh are
    different questions and 30 days is inside both."""
    assert is_reusable(_ago(20), now=NOW)
    assert freshness(_ago(20), now=NOW) is Freshness.FRESH


def test_research_past_reuse_but_inside_the_stale_window_is_still_fresh() -> None:
    """The gap between the windows is where they visibly differ. At 45 days a
    snapshot is too old to reuse but not old enough to warn about — and
    collapsing the two would either overspend or cry wolf."""
    age = _ago((RESEARCH_REUSE_DAYS + RESEARCH_STALE_DAYS) // 2)
    assert not is_reusable(age, now=NOW)
    assert freshness(age, now=NOW) is Freshness.FRESH


# -- staleness: a read-time label -------------------------------------------


def test_old_research_is_marked_stale_never_hidden() -> None:
    assert freshness(_ago(RESEARCH_STALE_DAYS + 1), now=NOW) is Freshness.STALE


def test_the_stale_boundary_is_inclusive() -> None:
    assert freshness(_ago(RESEARCH_STALE_DAYS), now=NOW) is Freshness.FRESH


# -- FR-033: a brief is only as fresh as what it rests on -------------------


def test_a_fresh_role_brief_on_stale_company_research_is_stale() -> None:
    """FR-033, and the reason lineage is recorded at all."""
    effective = effective_retrieved_at(
        role_retrieved_at=_ago(1), company_retrieved_at=_ago(RESEARCH_STALE_DAYS + 30)
    )
    assert freshness(effective, now=NOW) is Freshness.STALE


def test_the_older_of_the_two_wins_in_either_order() -> None:
    older, newer = _ago(200), _ago(2)
    assert effective_retrieved_at(role_retrieved_at=newer, company_retrieved_at=older) == older
    assert effective_retrieved_at(role_retrieved_at=older, company_retrieved_at=newer) == older


def test_a_missing_lineage_does_not_read_as_infinitely_stale() -> None:
    """A missing timestamp and an ancient one need different fixes, so they must
    not produce the same answer."""
    assert effective_retrieved_at(role_retrieved_at=_ago(1), company_retrieved_at=None) == _ago(1)
    assert freshness(_ago(1), now=NOW) is Freshness.FRESH


# -- naive datetimes ---------------------------------------------------------


@pytest.mark.parametrize("naive_days", [1, 200])
def test_a_naive_timestamp_is_handled_rather_than_raising(naive_days: int) -> None:
    """PostgreSQL returns aware datetimes and a hand-built one may not be.
    Comparing them raises `TypeError`, which would surface from a display path
    as a 500 on a page that only wanted to show a date."""
    naive = _ago(naive_days).replace(tzinfo=None)
    assert isinstance(freshness(naive, now=NOW), Freshness)
    assert isinstance(is_reusable(naive, now=NOW), bool)
