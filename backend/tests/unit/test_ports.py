"""The structured completion seam (T014, T015).

`contracts/extraction-seam.md` is the specification; this file is what holds it
to it. The seam is the artifact slice 004 inherits, so these tests are written
while it has exactly one caller and is still cheap to change.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from careerhq.application.ports import (
    Completion,
    StructuredCompletion,
    Usage,
    UsageRecorder,
)


class _Person(BaseModel):
    name: str
    years: int


def test_completion_carries_a_validated_value_of_the_requested_schema() -> None:
    """O1 — a schema is required and the return is typed.

    There is no call shape that yields unvalidated text, which is what makes
    FR-025 and Principle VI structural rather than remembered.
    """
    completion = Completion(
        value=_Person(name="Alex Morgan", years=8),
        usage=Usage(
            model="anthropic/claude-sonnet-5",
            input_tokens=1200,
            output_tokens=340,
            cost=Decimal("0.0141"),
        ),
    )

    assert isinstance(completion.value, _Person)
    assert completion.value.name == "Alex Morgan"


def test_usage_records_what_principle_v_requires() -> None:
    """O4, FR-026 — model, configuration, tokens and cost, per call.

    Returned rather than logged inside the adapter, so the application layer
    writes the audit record in the same transaction as the work it paid for.
    """
    usage = Usage(
        model="anthropic/claude-sonnet-5",
        input_tokens=1200,
        output_tokens=340,
        cost=Decimal("0.0141"),
    )

    assert usage.model == "anthropic/claude-sonnet-5"
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 340
    assert usage.cost == Decimal("0.0141")
    assert usage.is_fixture is False, "real usage must not claim to be fixture data"


def test_cost_is_decimal_not_float() -> None:
    """Money is never binary floating point.

    A per-call cost of 0.0141 accumulated over thousands of extractions in float
    drifts, and this value is an audit record under Principle V rather than a
    display nicety.
    """
    usage = Usage(model="m", input_tokens=1, output_tokens=1, cost=Decimal("0.0141"))
    assert isinstance(usage.cost, Decimal)


async def test_any_conforming_object_satisfies_the_protocol() -> None:
    """O6 — substitutable without a network.

    The Protocol is structural: a test double conforms by shape alone, with no
    base class to inherit and nothing to register. That is what lets the whole
    suite run with no API key.
    """

    class _Fake:
        async def complete(
            self,
            *,
            task: str,
            schema: type[BaseModel],
            prompt: str,
        ) -> Completion[BaseModel]:
            return Completion(
                value=schema.model_validate({"name": "Fake", "years": 1}),
                usage=Usage(
                    model=f"fake/{task}",
                    input_tokens=0,
                    output_tokens=0,
                    cost=Decimal("0"),
                    is_fixture=True,
                ),
            )

    client: StructuredCompletion = _Fake()
    result = await client.complete(task="cv_extraction", schema=_Person, prompt="…")

    assert isinstance(result.value, _Person)
    assert result.usage.is_fixture is True


def test_usage_rejects_negative_token_counts() -> None:
    """An audit record that can hold nonsense is not an audit record."""
    with pytest.raises(ValueError):
        Usage(model="m", input_tokens=-1, output_tokens=0, cost=Decimal("0"))


# -- usage must survive a call that failed validation ------------------------


class _Boom(RuntimeError):
    """Stands in for `ExtractionFailedError`, which the application layer must
    not import — the recorder duck-types on `.usage` for exactly that reason."""

    def __init__(self, usage: Usage | None) -> None:
        super().__init__("nope")
        self.usage = usage


def _usage(tokens: int) -> Usage:
    return Usage(
        model="anthropic/claude-sonnet-5",
        input_tokens=tokens,
        output_tokens=tokens // 2,
        cost=Decimal("0.01"),
    )


class _Seam:
    """Answers `n` times, then raises with the usage it was billed for."""

    def __init__(self, succeed: int, failure: Exception) -> None:
        self.succeed = succeed
        self.failure = failure
        self.calls = 0

    async def complete(self, *, task: str, schema: Any, prompt: str) -> Any:
        self.calls += 1
        if self.calls > self.succeed:
            raise self.failure
        return Completion(value=None, usage=_usage(1_000))  # type: ignore[arg-type]


async def test_the_recorder_keeps_usage_from_calls_that_succeeded() -> None:
    recorder = UsageRecorder(_Seam(succeed=3, failure=_Boom(None)))

    for _ in range(3):
        await recorder.complete(task="t", schema=object, prompt="p")  # type: ignore[arg-type]

    assert [u.input_tokens for u in recorder.calls] == [1_000, 1_000, 1_000]


async def test_the_recorder_keeps_usage_from_the_call_that_failed() -> None:
    """The exact loss the first real run took.

    Two calls succeeded and were billed, a third was billed and failed
    validation, and the run recorded `0 tokens, $0` for all three — because
    usage was only summed from the graph's return value, and the graph did not
    return. A run that reports zero cost reads as free rather than as
    unrecorded, which is the worse of the two errors.
    """
    recorder = UsageRecorder(_Seam(succeed=2, failure=_Boom(_usage(4_000))))

    for _ in range(2):
        await recorder.complete(task="t", schema=object, prompt="p")  # type: ignore[arg-type]
    with pytest.raises(_Boom):
        await recorder.complete(task="t", schema=object, prompt="p")  # type: ignore[arg-type]

    assert [u.input_tokens for u in recorder.calls] == [1_000, 1_000, 4_000]
    assert recorder.total_cost == Decimal("0.03")


async def test_the_recorder_re_raises_rather_than_swallowing() -> None:
    """Recording is not recovering. The run must still fail."""
    recorder = UsageRecorder(_Seam(succeed=0, failure=_Boom(_usage(500))))

    with pytest.raises(_Boom):
        await recorder.complete(task="t", schema=object, prompt="p")  # type: ignore[arg-type]


async def test_the_recorder_labels_every_call_with_the_task_that_made_it() -> None:
    """T092 — per-call persistence needs each entry to say *which* call it was.

    The adapter cannot supply the label: it knows only that it was called. The
    recorder is the one party holding both the task name and the bill, so it
    stamps the label — on the billed failure too, because run cd27b092's $0.36
    included exactly such a call and the record could not say which node spent
    it.
    """
    recorder = UsageRecorder(_Seam(succeed=2, failure=_Boom(_usage(4_000))))

    await recorder.complete(task="tailor_plan", schema=object, prompt="p")  # type: ignore[arg-type]
    await recorder.complete(task="tailor_draft", schema=object, prompt="p")  # type: ignore[arg-type]
    with pytest.raises(_Boom):
        await recorder.complete(task="tailor_review", schema=object, prompt="p")  # type: ignore[arg-type]

    assert [u.task for u in recorder.calls] == [
        "tailor_plan",
        "tailor_draft",
        "tailor_review",
    ], "every recorded call, the billed failure included, must carry its task name"


async def test_a_failure_carrying_no_usage_records_nothing_and_still_raises() -> None:
    """A transport failure never reached the provider's accounting. Inventing a
    zero-token entry for it would make the call count wrong in the other
    direction."""
    recorder = UsageRecorder(_Seam(succeed=0, failure=_Boom(None)))

    with pytest.raises(_Boom):
        await recorder.complete(task="t", schema=object, prompt="p")  # type: ignore[arg-type]

    assert recorder.calls == []
