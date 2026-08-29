"""Retrieval's cost overhead, measured so that the answer does not depend on luck.

**This computes SC-008 (this slice). It does not compute, restate, replace or
supersede SC-008 (006), which remains MISSED at 3.22% against an unchanged ≤2%
threshold.** The two are different questions and `test_sc008_is_not_relabelled.py`
is the gate that keeps them apart.

## What T052 exposed

The quantity has two halves with completely different statistical behaviour, and
dividing one by the other loses that:

| | numerator — retrieval's added input tokens | denominator — total run cost |
|---|---|---|
| behaviour | near-deterministic: a token-count difference on a
  controlled prompt | a step function; 2.7x on whether the Reviewer revised |
| measured | +4,727 (T045), then +3,754 (T052) after the citation fix |
  $0.206268 - $0.547891 across 8 runs |
| more samples buy | very little | a distribution, which is the whole missing piece |

Two paid re-measurements made the failure mode visible from both directions: the
numerator improved 21% and the reported ratio got **worse**, 2.12% → 3.22%,
because that session's baseline happened not to revise.

## What this module does instead

**The design is asymmetric, and that asymmetry is the finding.** Pairs pin the
numerator, so a small number of them suffices. The denominator needs a *sample* —
and every benchmark run is already one, so it costs nothing extra.

**The numerator is the sum across both guidance-consuming calls, and getting this
wrong halves it.** Retrieval replaces the guidance block in *both* the Plan and the
Draft prompt, so both are billed for it; a numerator counting only `tailor_plan`
under-reports the overhead by roughly half and would turn an unresolved
measurement into a confident pass. T045 and T052 both summed the two: +4,727 and
+3,754 respectively, *of which* `tailor_plan` was +2,371 and +1,715.

`tailor_plan` is the **control**, not the measurement. Between a static and a
retrieval arm on the same case only the guidance block differs there, so its delta
is attributable to guidance alone. `tailor_draft` also carries a differing plan, so
it corroborates rather than confirms — it agreed with Plan to within 0.6% in the
T045 pair and 18.9% in the T052 one, and `plan_share` reports that agreement so a
diverging Draft is visible rather than silently folded in. A pair with no Draft
observation yields a **lower bound**, and says so.

**An interval that straddles the threshold is reported as `unresolved`, and that
is a pass of this criterion.** It is written that way deliberately, so nobody is
rewarded for hunting a denominator that resolves. Choosing the flattering
denominator is the specific temptation here: the same numerator over the older
$0.446391 baseline gives 1.68%, which T052 measured, explained and declined to
record.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

#: Slice 006's criterion, quoted so no caller has to remember it — and so that a
#: caller cannot accidentally invent a different one.
SC008_006 = {
    "criterion": "SC-008 (006)",
    "question": "does retrieval increase tailoring cost per run by no more than 2%?",
    "threshold_percent": 2.0,
    "result_percent": 3.22,
    "verdict": "MISSED",
    "note": (
        "Unchanged by slice 007. Re-measured at T052 on current code; the target was "
        "not adjusted and the metric was not redefined."
    ),
}


@dataclass(frozen=True, slots=True)
class PairedObservation:
    """One case run twice — static and retrieval — in the same process.

    `plan_input_tokens` is the controlled measurement. `draft_input_tokens` is
    recorded for corroboration and is deliberately *not* averaged into the
    numerator: it carries a differing plan as well as differing guidance.
    """

    case_id: str
    static_plan_input_tokens: int
    retrieval_plan_input_tokens: int
    static_draft_input_tokens: int | None = None
    retrieval_draft_input_tokens: int | None = None

    @property
    def plan_delta(self) -> int:
        return self.retrieval_plan_input_tokens - self.static_plan_input_tokens

    @property
    def draft_delta(self) -> int | None:
        if self.static_draft_input_tokens is None or self.retrieval_draft_input_tokens is None:
            return None
        return self.retrieval_draft_input_tokens - self.static_draft_input_tokens

    @property
    def total_delta(self) -> int:
        """What retrieval actually added to this run's input bill.

        Both guidance-consuming calls, because both carry the block. A missing
        Draft observation makes this a **lower bound**, not an estimate.
        """
        return self.plan_delta + (self.draft_delta or 0)

    @property
    def plan_share(self) -> float | None:
        """How much of the total the controlled call accounts for.

        Near 0.5 means Draft corroborates Plan. Far from it means the Draft prompt
        differed for reasons beyond guidance — which is exactly what happened in
        the T052 pair, where the plans themselves were 2,657 against 3,194 tokens.
        """
        total = self.total_delta
        return None if total == 0 else self.plan_delta / total


@dataclass(frozen=True, slots=True)
class RunCost:
    """One observed run cost, and whether the Reviewer revised on it."""

    run_id: str
    cost: Decimal
    revised: bool


Verdict = Literal["below", "above", "unresolved", "not_measured"]


def retrieval_overhead(
    *,
    pairs: list[PairedObservation],
    denominator_sample: list[RunCost],
    input_price_per_mtok: Decimal,
    threshold_percent: float = 2.0,
) -> dict[str, Any]:
    """The overhead, its denominator distribution, and whether the answer resolves.

    Returns the numerator with its spread, the denominator as a distribution with
    its revision rate, the implied ratio as an **interval**, and a verdict of
    `below` / `above` / `unresolved` / `not_measured`.

    `threshold_percent` is the position the interval is compared against. It
    defaults to 2.0 because that is the number the underlying question has always
    been asked about — **this is not a new threshold, and passing a different value
    does not make one.** The verdict here says whether *this measurement* can place
    itself relative to that position; it never restates SC-008 (006)'s verdict,
    which is carried verbatim in the result as `sc008_006`.
    """
    result: dict[str, Any] = {"sc008_006": dict(SC008_006)}

    if not pairs or not denominator_sample:
        result.update(
            verdict="not_measured",
            reason=(
                f"{len(pairs)} paired observations and {len(denominator_sample)} run costs; "
                "both are needed — pairs pin the numerator, the sample supplies the "
                "denominator's distribution"
            ),
            pairs=len(pairs),
            denominator_n=len(denominator_sample),
        )
        return result

    # Both guidance-consuming calls, because both are billed for the block. Where a
    # Draft observation is missing the pair contributes its Plan delta alone, which
    # under-counts — flagged below as a lower bound rather than silently averaged.
    totals = [p.total_delta for p in pairs]
    lower_bound = any(p.draft_delta is None for p in pairs)
    deltas = totals
    mean_delta = statistics.fmean(deltas)
    # Population spread when there is only one observation; a sample stdev of one
    # point is undefined, and reporting 0.0 would claim precision nobody measured.
    delta_stdev = statistics.stdev(deltas) if len(deltas) > 1 else None

    numerator = Decimal(str(mean_delta)) * input_price_per_mtok / Decimal("1000000")

    costs = [float(r.cost) for r in denominator_sample]
    mean_cost = statistics.fmean(costs)
    revised = sum(1 for r in denominator_sample if r.revised)

    # The interval is over the *denominator's* observed range, because that is
    # where the variance lives. Expressed against the mean, the cheapest and the
    # dearest run in the sample.
    ratio_at_mean = float(numerator) / mean_cost * 100
    ratio_at_max_cost = float(numerator) / max(costs) * 100
    ratio_at_min_cost = float(numerator) / min(costs) * 100
    low, high = sorted((ratio_at_max_cost, ratio_at_min_cost))

    if high < threshold_percent:
        verdict: Verdict = "below"
    elif low > threshold_percent:
        verdict = "above"
    else:
        verdict = "unresolved"

    result.update(
        verdict=verdict,
        pairs=len(pairs),
        numerator_tokens_mean=round(mean_delta, 1),
        numerator_tokens_stdev=(round(delta_stdev, 1) if delta_stdev is not None else None),
        numerator_tokens_per_pair={p.case_id: p.total_delta for p in pairs},
        numerator_is_lower_bound=lower_bound,
        control_tokens_mean=round(statistics.fmean([p.plan_delta for p in pairs]), 1),
        numerator_usd=float(numerator),
        denominator_n=len(denominator_sample),
        denominator_mean_usd=round(mean_cost, 6),
        denominator_min_usd=round(min(costs), 6),
        denominator_max_usd=round(max(costs), 6),
        denominator_revision_rate=round(revised / len(denominator_sample), 3),
        ratio_percent_at_mean=round(ratio_at_mean, 3),
        interval_percent=[round(low, 3), round(high, 3)],
        threshold_percent=threshold_percent,
        # Corroboration only. See the module docstring for why this is not a second
        # measurement of the same thing.
        draft_deltas={p.case_id: p.draft_delta for p in pairs if p.draft_delta is not None},
        reason=_explain(verdict, low, high, threshold_percent),
    )
    return result


def _explain(verdict: Verdict, low: float, high: float, threshold: float) -> str:
    if verdict == "below":
        return (
            f"the interval [{low:.2f}%, {high:.2f}%] sits entirely below {threshold}% "
            "across the observed denominator range"
        )
    if verdict == "above":
        return (
            f"the interval [{low:.2f}%, {high:.2f}%] sits entirely above {threshold}% "
            "across the observed denominator range"
        )
    return (
        f"the interval [{low:.2f}%, {high:.2f}%] straddles {threshold}%, so this "
        "measurement cannot place the overhead on either side of it independently of "
        "revision behaviour. Reporting *unresolved* is the honest result and is a pass "
        "of SC-008 (this slice); it says nothing about SC-008 (006), which stands as "
        "MISSED at 3.22%."
    )


def required_pairs_for(budget_usd: Decimal, cost_per_run: Decimal) -> int:
    """How many extra static arms a budget buys.

    **A pair costs one extra run, not two**: the retrieval arm is an ordinary
    benchmark run and is already paid for. Provided so the pair count is derived
    from the approved budget rather than written down as a constant — D3 approved
    five, and five is what this returns at the approved figures, but it returns it
    by arithmetic.
    """
    if cost_per_run <= 0:
        raise ValueError("a non-positive per-run cost buys an unbounded number of pairs")
    return max(0, math.floor(budget_usd / cost_per_run))


__all__ = [
    "SC008_006",
    "PairedObservation",
    "RunCost",
    "required_pairs_for",
    "retrieval_overhead",
]
