"""The advisor run's pending/abandoned lifecycle (T008, research.md D1/D15).

Pure-logic half. The database-enforced half — the partial unique index losing
a two-clicks race, the reap allowing a new run — lives in
`tests/integration/test_advisor_runs.py`, because an index can only refuse in
PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from careerhq.application.advise_career import is_abandoned
from careerhq.application.advisor_rules import RUN_ABANDONED_AFTER
from careerhq.domain.models import AdvisorRun, AdvisorRunStatus


def _run(status: AdvisorRunStatus, *, age: timedelta) -> AdvisorRun:
    run = AdvisorRun(status=status, rules_version="v1-advisor")
    run.created_at = datetime.now(UTC) - age
    return run


def test_a_fresh_pending_run_is_not_abandoned() -> None:
    run = _run(AdvisorRunStatus.PENDING, age=timedelta(seconds=30))
    assert is_abandoned(run) is False


def test_a_pending_run_past_the_deadline_is_abandoned() -> None:
    run = _run(AdvisorRunStatus.PENDING, age=RUN_ABANDONED_AFTER + timedelta(seconds=1))
    assert is_abandoned(run) is True


def test_terminal_runs_are_never_abandoned() -> None:
    """`failed` and `ready` rows are history, not blockers — reaping them
    would rewrite what happened."""
    for status in (AdvisorRunStatus.READY, AdvisorRunStatus.FAILED):
        run = _run(status, age=timedelta(days=365))
        assert is_abandoned(run) is False


def test_a_naive_datetime_is_treated_as_utc() -> None:
    """`created_at` read through some paths loses tzinfo; the comparison must
    not raise and must not silently shift by the host offset."""
    run = AdvisorRun(status=AdvisorRunStatus.PENDING, rules_version="v1-advisor")
    run.created_at = datetime.now(UTC).replace(tzinfo=None) - RUN_ABANDONED_AFTER * 2
    assert is_abandoned(run) is True


def test_status_compares_by_value_not_identity() -> None:
    """A row loaded in a fresh session holds the plain string, and `is`
    against the enum member silently never matches — shipped twice."""
    run = _run(AdvisorRunStatus.PENDING, age=RUN_ABANDONED_AFTER * 2)
    run.status = "pending"  # type: ignore[assignment]  # what a fresh session actually returns
    assert is_abandoned(run) is True
