"""The spend ceiling, and the projection that has to happen before it (T005, T012).

**FR-008, SC-011.** The ceiling is the only thing standing between a benchmark
and an unbounded bill, and this project has never before had code that could
spend money in a loop. Every assertion here is about a refusal.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from careerhq.application.evaluation.budget import (
    MEASURED_TASK_COST,
    CeilingExceededError,
    SpendGuard,
    project_pass_cost,
    project_run_cost,
)


def test_the_measured_table_carries_every_task_a_run_bills() -> None:
    """A missing task silently under-projects, which is how a ceiling is passed."""
    assert set(MEASURED_TASK_COST) >= {
        "tailor_plan",
        "tailor_draft",
        "tailor_review",
        "tailor_revise",
        "tailor_revise_escalated",
    }
    assert len(MEASURED_TASK_COST) >= 5


def test_a_non_revising_run_is_plan_plus_draft_plus_review() -> None:
    expected = (
        MEASURED_TASK_COST["tailor_plan"]
        + MEASURED_TASK_COST["tailor_draft"]
        + MEASURED_TASK_COST["tailor_review"]
    )
    assert project_run_cost(revising=False) == expected


def test_a_revising_run_adds_a_revise_and_a_second_review() -> None:
    assert project_run_cost(revising=True) == project_run_cost(revising=False) + (
        MEASURED_TASK_COST["tailor_revise"] + MEASURED_TASK_COST["tailor_review"]
    )


def test_the_projection_is_derived_from_its_arguments_not_from_a_constant() -> None:
    """The D3 numbers must not be hard-coded anywhere.

    12 cases and 5 arms are *configuration*, not arithmetic. A projection that
    returns $6.11 regardless of what it was asked would pass a ceiling check for
    a run that was about to do something else entirely.
    """
    small = project_pass_cost(cases=1, static_arms=0, judged=0)
    large = project_pass_cost(cases=100, static_arms=0, judged=0)
    assert large > small * 50

    # Each dimension moves the total independently.
    base = project_pass_cost(cases=4, static_arms=0, judged=0)
    assert project_pass_cost(cases=4, static_arms=2, judged=0) > base
    assert project_pass_cost(cases=4, static_arms=0, judged=4) > base


def test_zero_of_everything_projects_zero() -> None:
    assert project_pass_cost(cases=0, static_arms=0, judged=0) == Decimal("0")


def test_the_guard_refuses_above_the_ceiling_and_names_both_numbers() -> None:
    guard = SpendGuard(ceiling=Decimal("1.00"))
    with pytest.raises(CeilingExceededError) as excinfo:
        guard.authorise(project_pass_cost(cases=12, static_arms=5, judged=12))
    message = str(excinfo.value)
    assert "1.00" in message
    assert "projected" in message.lower()


def test_the_guard_authorises_below_the_ceiling() -> None:
    guard = SpendGuard(ceiling=Decimal("10.00"))
    guard.authorise(project_pass_cost(cases=12, static_arms=5, judged=12))
    assert guard.authorised is True


def test_nothing_may_be_spent_before_authorisation() -> None:
    """The order matters more than the arithmetic.

    A guard that only reconciles afterwards has already spent the money.
    """
    guard = SpendGuard(ceiling=Decimal("10.00"))
    with pytest.raises(CeilingExceededError):
        guard.record(Decimal("0.01"), task="tailor_plan")


def test_actual_spend_accumulates_and_trips_the_ceiling_mid_run() -> None:
    """A projection can be wrong. The ceiling is enforced against actuals too."""
    guard = SpendGuard(ceiling=Decimal("0.50"))
    guard.authorise(Decimal("0.40"))
    guard.record(Decimal("0.30"), task="tailor_plan")
    with pytest.raises(CeilingExceededError):
        guard.record(Decimal("0.30"), task="tailor_draft")
    assert guard.spent == Decimal("0.30")


def test_the_ceiling_is_decimal_and_compares_exactly_at_the_boundary() -> None:
    """Float would make the boundary comparison unreliable in one direction."""
    guard = SpendGuard(ceiling=Decimal("0.10"))
    guard.authorise(Decimal("0.10"))
    guard.record(Decimal("0.10"), task="tailor_plan")
    assert guard.spent == Decimal("0.10")
    assert guard.remaining == Decimal("0")
