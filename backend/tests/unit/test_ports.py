"""The structured completion seam (T014, T015).

`contracts/extraction-seam.md` is the specification; this file is what holds it
to it. The seam is the artifact slice 004 inherits, so these tests are written
while it has exactly one caller and is still cheap to change.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel

from careerhq.application.ports import Completion, StructuredCompletion, Usage


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
