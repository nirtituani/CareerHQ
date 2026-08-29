"""Nothing may bill past the ceiling — checked before the call and after it."""

from __future__ import annotations

from decimal import Decimal

import pytest

from careerhq.application.evaluation.budget import CeilingExceededError, SpendGuard
from careerhq.application.evaluation.guarded import GuardedCompletion
from careerhq.application.ports import Usage
from careerhq.domain.schemas.evaluation import JudgeVerdict
from tests.support.scripted_seam import ScriptedSeam

pytestmark = pytest.mark.asyncio


def _verdict() -> dict[str, object]:
    return {
        "dimensions": [
            {"dimension": d, "score": 3, "justification": "A specific sentence about it."}
            for d in ("relevance", "coverage", "specificity", "plausibility", "presentation")
        ],
        "overall": 3,
        "strongest": "Something concrete and specific.",
        "weakest": "Something else concrete and specific.",
    }


async def test_a_call_that_would_exceed_the_ceiling_is_refused_before_it_is_made() -> None:
    """The whole point: the refusal happens before the provider is reached."""
    guard = SpendGuard(ceiling=Decimal("0.01"))
    guard.authorise(Decimal("0.01"))
    seam = ScriptedSeam(script={"eval_judge": [_verdict()]})
    guarded = GuardedCompletion(inner=seam, guard=guard)

    with pytest.raises(CeilingExceededError) as excinfo:
        await guarded.complete(task="eval_judge", schema=JudgeVerdict, prompt="p")

    assert "BEFORE calling" in str(excinfo.value)
    assert seam.call_count == 0, "the provider was reached despite the refusal"


async def test_actual_cost_is_recorded_and_accumulates() -> None:
    guard = SpendGuard(ceiling=Decimal("10.00"))
    guard.authorise(Decimal("1.00"))
    seam = ScriptedSeam(
        script={"eval_judge": [_verdict(), _verdict()]}, cost_per_call=Decimal("0.07")
    )
    guarded = GuardedCompletion(inner=seam, guard=guard)

    await guarded.complete(task="eval_judge", schema=JudgeVerdict, prompt="p")
    await guarded.complete(task="eval_judge", schema=JudgeVerdict, prompt="p")

    assert guard.spent == Decimal("0.14")
    assert len(guarded.calls) == 2
    assert guarded.calls[-1]["cumulative"] == 0.14


async def test_an_unknown_task_reserves_the_most_expensive_measured_task() -> None:
    """A new task name must not slip past the ceiling by being unrecognised."""
    guard = SpendGuard(ceiling=Decimal("0.05"))
    guard.authorise(Decimal("0.05"))
    seam = ScriptedSeam(script={"something_new": [_verdict()]})
    guarded = GuardedCompletion(inner=seam, guard=guard)

    with pytest.raises(CeilingExceededError):
        await guarded.complete(task="something_new", schema=JudgeVerdict, prompt="p")
    assert seam.call_count == 0


async def test_the_itemised_bill_names_every_call() -> None:
    guard = SpendGuard(ceiling=Decimal("10.00"))
    guard.authorise(Decimal("1.00"))
    seam = ScriptedSeam(script={"eval_judge": [_verdict()]})
    guarded = GuardedCompletion(inner=seam, guard=guard)
    await guarded.complete(task="eval_judge", schema=JudgeVerdict, prompt="p")

    call = guarded.calls[0]
    assert call["task"] == "eval_judge"
    assert call["input_tokens"] > 0
    assert "model" in call


async def test_a_call_that_was_billed_but_failed_validation_is_still_charged() -> None:
    """The hole the first real judge call fell through.

    `ExtractionFailedError` carries the usage the provider billed. A guard that
    only records successes reads $0 while money leaves, and enough failing calls
    would spend straight past the ceiling.

    Duck-typed on `.usage`, exactly as `UsageRecorder` does — the exception class
    lives in `infrastructure/` and this layer must not import it.
    """

    class _BilledFailure(RuntimeError):
        def __init__(self) -> None:
            super().__init__("did not match the expected structure")
            self.usage = Usage(
                model="claude-opus-5",
                input_tokens=8000,
                output_tokens=400,
                cost=Decimal("0.05"),
            )

    class _AlwaysFails:
        async def complete(self, *, task: str, schema: object, prompt: str) -> object:
            raise _BilledFailure()

    guard = SpendGuard(ceiling=Decimal("10.00"))
    guard.authorise(Decimal("1.00"))
    guarded = GuardedCompletion(inner=_AlwaysFails(), guard=guard)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await guarded.complete(task="eval_judge", schema=JudgeVerdict, prompt="p")

    assert guard.spent == Decimal("0.05"), "a billed failure was recorded as free"
    assert guarded.calls[-1]["outcome"] == "billed, failed validation"


async def test_an_exception_carrying_no_usage_charges_nothing() -> None:
    """A call that never reached the provider was never billed.

    Inventing a zero-token entry for it would make the call count wrong in the
    other direction.
    """

    class _NeverReached:
        async def complete(self, *, task: str, schema: object, prompt: str) -> object:
            raise ConnectionError("dns")

    guard = SpendGuard(ceiling=Decimal("10.00"))
    guard.authorise(Decimal("1.00"))
    guarded = GuardedCompletion(inner=_NeverReached(), guard=guard)  # type: ignore[arg-type]

    with pytest.raises(ConnectionError):
        await guarded.complete(task="eval_judge", schema=JudgeVerdict, prompt="p")

    assert guard.spent == Decimal("0")
    assert guarded.calls == []
