"""The revised retrieval-overhead methodology (T041, SC-008 *this slice*).

**Nothing here restates SC-008 (006).** It stands at MISSED, 3.22% against an
unchanged ≤2% threshold, and the module carries that verdict verbatim rather than
recomputing it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from careerhq.application.evaluation.overhead import (
    SC008_006,
    PairedObservation,
    RunCost,
    required_pairs_for,
    retrieval_overhead,
)

PRICE = Decimal("2.00")


def _pairs(n: int, plan: int = 1715, draft: int | None = 2039) -> list[PairedObservation]:
    """Pairs shaped like the real T052 measurement: plan +1,715, draft +2,039."""
    return [
        PairedObservation(
            case_id=f"c{i}",
            static_plan_input_tokens=7221,
            retrieval_plan_input_tokens=7221 + plan,
            static_draft_input_tokens=None if draft is None else 7816,
            retrieval_draft_input_tokens=None if draft is None else 7816 + draft,
        )
        for i in range(n)
    ]


def test_the_numerator_sums_both_guidance_consuming_calls() -> None:
    """Counting only the control call halves the overhead and would fabricate a pass.

    T052 measured +3,754 total, of which `tailor_plan` was +1,715. Retrieval
    replaces the guidance block in the Draft prompt too, and that call is billed
    for it just as the Plan call is.
    """
    result = retrieval_overhead(
        pairs=_pairs(1),
        denominator_sample=[RunCost("r1", Decimal("0.233124"), False)],
        input_price_per_mtok=PRICE,
    )
    assert result["numerator_tokens_mean"] == pytest.approx(3754)
    assert result["control_tokens_mean"] == pytest.approx(1715)
    assert result["numerator_is_lower_bound"] is False


def test_a_pair_with_no_draft_observation_is_flagged_as_a_lower_bound() -> None:
    result = retrieval_overhead(
        pairs=_pairs(1, draft=None),
        denominator_sample=[RunCost("r1", Decimal("0.233124"), False)],
        input_price_per_mtok=PRICE,
    )
    assert result["numerator_is_lower_bound"] is True
    assert result["numerator_tokens_mean"] == pytest.approx(1715)


def test_slice_006s_verdict_is_carried_verbatim_and_never_recomputed() -> None:
    assert SC008_006["result_percent"] == 3.22
    assert SC008_006["threshold_percent"] == 2.0
    assert SC008_006["verdict"] == "MISSED"
    result = retrieval_overhead(
        pairs=_pairs(5),
        denominator_sample=[RunCost("r1", Decimal("0.30"), False)],
        input_price_per_mtok=PRICE,
    )
    assert result["sc008_006"]["result_percent"] == 3.22
    assert result["sc008_006"]["verdict"] == "MISSED"


def test_without_pairs_or_a_denominator_sample_nothing_is_measured() -> None:
    result = retrieval_overhead(pairs=[], denominator_sample=[], input_price_per_mtok=PRICE)
    assert result["verdict"] == "not_measured"


def test_a_wide_denominator_spread_reports_unresolved() -> None:
    """The T052 situation, reproduced: the same numerator over a 2.7x cost range."""
    result = retrieval_overhead(
        pairs=_pairs(5),
        denominator_sample=[
            RunCost("r1", Decimal("0.206268"), False),
            RunCost("r2", Decimal("0.233124"), False),
            RunCost("r3", Decimal("0.396892"), True),
            RunCost("r4", Decimal("0.547891"), True),
        ],
        input_price_per_mtok=PRICE,
    )
    assert result["verdict"] == "unresolved"
    low, high = result["interval_percent"]
    assert low < 2.0 < high
    assert "straddles" in result["reason"]
    assert "3.22" in result["reason"]


def test_a_tight_expensive_denominator_can_resolve_below() -> None:
    result = retrieval_overhead(
        pairs=_pairs(5, plan=200, draft=200),
        denominator_sample=[
            RunCost("r1", Decimal("0.50"), True),
            RunCost("r2", Decimal("0.52"), True),
            RunCost("r3", Decimal("0.51"), True),
        ],
        input_price_per_mtok=PRICE,
    )
    assert result["verdict"] == "below"


def test_a_large_numerator_resolves_above() -> None:
    result = retrieval_overhead(
        pairs=_pairs(5, plan=4500, draft=4500),
        denominator_sample=[
            RunCost("r1", Decimal("0.21"), False),
            RunCost("r2", Decimal("0.23"), False),
        ],
        input_price_per_mtok=PRICE,
    )
    assert result["verdict"] == "above"


def test_the_revision_rate_of_the_denominator_is_reported() -> None:
    """Without it, the denominator is a number with no explanation of its spread."""
    result = retrieval_overhead(
        pairs=_pairs(5),
        denominator_sample=[
            RunCost("r1", Decimal("0.21"), False),
            RunCost("r2", Decimal("0.23"), False),
            RunCost("r3", Decimal("0.40"), True),
            RunCost("r4", Decimal("0.55"), True),
        ],
        input_price_per_mtok=PRICE,
    )
    assert result["denominator_revision_rate"] == 0.5
    assert result["denominator_n"] == 4


def test_a_single_pair_reports_no_spread_rather_than_a_spread_of_zero() -> None:
    """A stdev of one observation is undefined; 0.0 would claim precision."""
    result = retrieval_overhead(
        pairs=_pairs(1),
        denominator_sample=[RunCost("r1", Decimal("0.30"), False)],
        input_price_per_mtok=PRICE,
    )
    assert result["numerator_tokens_stdev"] is None


def test_the_numerator_is_reported_per_pair_so_an_outlier_is_visible() -> None:
    result = retrieval_overhead(
        pairs=_pairs(3),
        denominator_sample=[RunCost("r1", Decimal("0.30"), False)],
        input_price_per_mtok=PRICE,
    )
    assert len(result["numerator_tokens_per_pair"]) == 3


def test_the_pair_count_is_derived_from_the_budget_not_written_down() -> None:
    """D3 approved five arms; five is what the approved figures buy."""
    assert required_pairs_for(Decimal("1.55"), Decimal("0.31")) == 5
    assert required_pairs_for(Decimal("0.62"), Decimal("0.31")) == 2
    assert required_pairs_for(Decimal("0.00"), Decimal("0.31")) == 0


def test_a_nonpositive_run_cost_is_refused() -> None:
    with pytest.raises(ValueError):
        required_pairs_for(Decimal("10"), Decimal("0"))
