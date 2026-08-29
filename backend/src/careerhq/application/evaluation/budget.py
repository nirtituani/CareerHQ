"""Projecting what an evaluation will cost, and refusing when it is too much.

**FR-008, SC-011.** This is the first code in the project that can spend money in
a loop, so the ceiling is enforced in two places rather than one: against the
*projection* before any call is made, and against *actuals* as they accumulate.
A projection can be wrong — the judge figure has no measurement behind it — and
a guard that only projects has no answer when it is.

**Every figure in `MEASURED_TASK_COST` was measured**, not modelled. They are the
mean cost per task over the non-fixture calls this project has actually billed,
read from `tailoring_run_calls` on 2026-08-29. The one estimated number in this
module is the judge's, and it says so at its definition.

**Nothing here hard-codes a case count or a total.** The D3 figures — 12 cases,
5 paired static arms, a $10 ceiling — are configuration and arguments. A
projection that returned $6.11 regardless of what it was asked would authorise a
run that was about to do something else.
"""

from __future__ import annotations

from decimal import Decimal


class CeilingExceededError(RuntimeError):
    """The spend ceiling would be, or has been, exceeded.

    **Raised before the call, not after it.** The class exists separately from
    every other refusal in the harness because it is the only one whose failure
    mode is money rather than a wrong number.
    """


#: Mean cost per task, in USD, over this project's non-fixture calls.
#:
#: **Measured 2026-08-29** from `tailoring_run_calls WHERE is_fixture = false`,
#: over 26 calls: `tailor_plan` n=7, `tailor_draft` n=7, `tailor_review` n=9,
#: `tailor_revise` n=2, `tailor_revise_escalated` n=1.
#:
#: `tailor_draft` dominates a non-revising run at 47% of it, and it does so
#: through **output** — 10,386 tokens against Plan's 2,757. That is the shape of
#: the bill, and it is why cost work belongs to output rather than input.
MEASURED_TASK_COST: dict[str, Decimal] = {
    "tailor_plan": Decimal("0.043233"),
    "tailor_draft": Decimal("0.120885"),
    "tailor_review": Decimal("0.090196"),
    "tailor_revise": Decimal("0.052382"),
    "tailor_revise_escalated": Decimal("0.065685"),
}

#: What one judge call is expected to cost, in USD.
#:
#: **ESTIMATED, not measured — the only such figure in this module.** Modelled on
#: `tailor_review`, which sees the same shape of input (a posting plus a composed
#: résumé) on the same model, with a smaller output because a rubric score with
#: brief justifications is shorter than a findings list: ~7,950 input at Opus
#: $5.00/MTok plus ~1,200 output at $25.00/MTok.
#:
#: **This is the number to true up first.** If it is 50% wrong across 12 judged
#: outputs the total moves by ~$0.42, which is what the ceiling's headroom is for.
ESTIMATED_JUDGE_COST = Decimal("0.070")

#: The measured proportion of succeeded runs that triggered a revision: 3 of 8,
#: 2026-08-29. Used only to express an *expected* run cost; every projection that
#: gates a ceiling uses the revising figure, because a ceiling sized on an
#: average is a ceiling that is exceeded half the time.
MEASURED_REVISION_RATE = Decimal("0.375")


def project_run_cost(*, revising: bool) -> Decimal:
    """What one tailoring run is expected to bill.

    A non-revising run is plan + draft + review. A revising one adds a revise and
    a **second** review — which is why revision is a step function worth about a
    third of a run, and why slice 006's SC-008 could not resolve a 2% threshold
    through it.
    """
    base = (
        MEASURED_TASK_COST["tailor_plan"]
        + MEASURED_TASK_COST["tailor_draft"]
        + MEASURED_TASK_COST["tailor_review"]
    )
    if not revising:
        return base
    return base + MEASURED_TASK_COST["tailor_revise"] + MEASURED_TASK_COST["tailor_review"]


def expected_run_cost() -> Decimal:
    """The revision-weighted forecast: what a run is *likely* to bill.

    `MEASURED_REVISION_RATE` of runs cost the revising figure and the rest the
    non-revising one. **This is the forecasting number and must never gate a
    ceiling** — a ceiling sized on an average is exceeded about half the time,
    which is why `project_pass_cost(revising=True)` exists beside it.
    """
    return project_run_cost(revising=True) * MEASURED_REVISION_RATE + project_run_cost(
        revising=False
    ) * (Decimal("1") - MEASURED_REVISION_RATE)


def project_pass_cost(
    *,
    cases: int,
    static_arms: int,
    judged: int,
    revising: bool = False,
    expected: bool = False,
) -> Decimal:
    """What a whole pass is expected to bill, from what it was actually asked to do.

    `static_arms` are the extra runs the SC-008 pairing needs. **A pair costs one
    extra run, not two**: the retrieval arm of a pair *is* an ordinary benchmark
    run and is already counted in `cases`.

    `revising=True` prices every run as though the Reviewer revised. That is the
    right basis for a ceiling check and the wrong basis for a forecast, so it is
    a parameter rather than a default in either direction.
    """
    if min(cases, static_arms, judged) < 0:
        raise ValueError("counts cannot be negative")
    if expected and revising:
        raise ValueError(
            "expected and revising are two different bases and asking for both is a "
            "question with no answer: expected weights by the measured revision rate, "
            "revising assumes every run revises"
        )
    per_run = expected_run_cost() if expected else project_run_cost(revising=revising)
    return (per_run * (cases + static_arms)) + (ESTIMATED_JUDGE_COST * judged)


class SpendGuard:
    """Authorise first, then spend — and stop at the ceiling either way.

    **Two enforcement points, because a projection is a belief and a bill is a
    fact.** `authorise` refuses a plan that cannot fit. `record` refuses the call
    after the one that would take actual spend past the ceiling, so a projection
    that was too optimistic costs one call rather than a run.

    `Decimal` throughout. The ceiling is compared against costs stored as
    `Numeric(12, 6)`, and a float ceiling would not compare equal to itself at
    the boundary.
    """

    def __init__(self, *, ceiling: Decimal) -> None:
        if ceiling < 0:
            raise ValueError("a negative ceiling authorises nothing and refuses everything")
        self._ceiling = ceiling
        self._spent = Decimal("0")
        self._authorised = False
        self._projection: Decimal | None = None

    @property
    def ceiling(self) -> Decimal:
        return self._ceiling

    @property
    def spent(self) -> Decimal:
        return self._spent

    @property
    def authorised(self) -> bool:
        return self._authorised

    @property
    def projection(self) -> Decimal | None:
        """What was projected at authorisation, so the report can compare."""
        return self._projection

    @property
    def remaining(self) -> Decimal:
        return self._ceiling - self._spent

    def authorise(self, projection: Decimal) -> None:
        """Refuse the whole plan, before anything is billed.

        **Names both numbers.** A refusal that says only "too expensive" sends
        the reader to look up two values the refusal already knew.
        """
        if projection > self._ceiling:
            raise CeilingExceededError(
                f"refused before any billable call: projected ${projection:.6f} "
                f"exceeds the ceiling ${self._ceiling:.2f}. "
                f"Raising it needs explicit approval, not a larger number here."
            )
        self._projection = projection
        self._authorised = True

    def record(self, cost: Decimal, *, task: str) -> None:
        """Account for a call that has been made, and refuse the next one if needed.

        Refusing on an **unauthorised** guard is not a formality: it is the rule
        that makes "project before you spend" enforceable rather than advisory.
        """
        if not self._authorised:
            raise CeilingExceededError(
                f"refused: {task} attempted to spend ${cost:.6f} with no authorised "
                f"projection. Call authorise() first — a guard that only reconciles "
                f"afterwards has already spent the money."
            )
        if self._spent + cost > self._ceiling:
            raise CeilingExceededError(
                f"refused at {task}: ${self._spent:.6f} already spent, ${cost:.6f} more "
                f"would exceed the ceiling ${self._ceiling:.2f}."
            )
        self._spent += cost


__all__ = [
    "ESTIMATED_JUDGE_COST",
    "MEASURED_REVISION_RATE",
    "MEASURED_TASK_COST",
    "CeilingExceededError",
    "SpendGuard",
    "expected_run_cost",
    "project_pass_cost",
    "project_run_cost",
]
