"""The test double gets its own tests, because the loop's tests depend on it.

If the seam silently returned the same answer twice, every revision-path test
would still pass while proving nothing — the workflow would appear to converge
because the Reviewer never changed its mind. A broken test double is worse than
no test, so this one is checked before anything relies on it.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from tests.support.scripted_seam import ScriptedSeam, ScriptExhausted


class Answer(BaseModel):
    confidence: int


@pytest.mark.asyncio
async def test_successive_calls_to_one_task_return_successive_answers() -> None:
    """The whole reason this exists: reject, reject, accept."""
    seam = ScriptedSeam(
        script={"tailor_review": [{"confidence": 10}, {"confidence": 40}, {"confidence": 90}]}
    )

    scores = [
        (await seam.complete(task="tailor_review", schema=Answer, prompt="p")).value.confidence
        for _ in range(3)
    ]

    assert scores == [10, 40, 90]
    assert seam.times_called("tailor_review") == 3


@pytest.mark.asyncio
async def test_running_past_the_script_raises_rather_than_repeating() -> None:
    """A seam that repeated its last answer would let an unbounded loop look
    convergent — which is precisely the failure FR-013's bound prevents."""
    seam = ScriptedSeam(script={"tailor_review": [{"confidence": 10}]})
    await seam.complete(task="tailor_review", schema=Answer, prompt="p")

    with pytest.raises(ScriptExhausted, match="MAX_REVISIONS"):
        await seam.complete(task="tailor_review", schema=Answer, prompt="p")


@pytest.mark.asyncio
async def test_an_unscripted_task_names_what_was_asked_for() -> None:
    """Including the escalated revision name, which is easy to typo and whose
    absence would otherwise surface as a confusing KeyError."""
    seam = ScriptedSeam(script={"tailor_review": [{"confidence": 90}]})

    with pytest.raises(ScriptExhausted, match="tailor_revise_escalated"):
        await seam.complete(task="tailor_revise_escalated", schema=Answer, prompt="p")


@pytest.mark.asyncio
async def test_the_order_of_task_names_is_recorded() -> None:
    """How the Sonnet -> Opus escalation is proved to be a task-name swap."""
    seam = ScriptedSeam(
        script={
            "tailor_review": [{"confidence": 10}, {"confidence": 90}],
            "tailor_revise": [{"confidence": 0}],
        }
    )

    await seam.complete(task="tailor_review", schema=Answer, prompt="p")
    await seam.complete(task="tailor_revise", schema=Answer, prompt="p")
    await seam.complete(task="tailor_review", schema=Answer, prompt="p")

    assert seam.tasks_called == ["tailor_review", "tailor_revise", "tailor_review"]
    assert seam.call_count == 3


@pytest.mark.asyncio
async def test_a_scripted_answer_still_faces_the_schema() -> None:
    """A test cannot script something production would reject.

    Without this the double would be a way to smuggle invalid payloads past
    validation, and the loop's tests would prove the workflow handles data the
    provider could never actually return.
    """
    seam = ScriptedSeam(script={"tailor_review": [{"confidence": "not a number"}]})

    with pytest.raises(ValueError):
        await seam.complete(task="tailor_review", schema=Answer, prompt="p")
