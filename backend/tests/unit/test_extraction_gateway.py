"""The gateway adapters (T016, T017, T018).

No test here contacts a provider. The LiteLLM call is substituted at the module
boundary, which is what FR-027 requires and what T049 verifies from the other
direction by unsetting the key entirely.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from careerhq.infrastructure.ai import fixture_gateway, litellm_gateway


class _Person(BaseModel):
    name: str
    years: int


def _response(content: str, *, model: str = "anthropic/claude-sonnet-5") -> dict[str, Any]:
    """The shape LiteLLM returns, reduced to what the adapter reads."""
    return {
        "model": model,
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 340},
    }


async def test_output_failing_the_schema_raises_rather_than_returning_partial_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O2, FR-025 — validation failure IS extraction failure.

    A model that returned malformed output has told you it did not understand
    the document. Repairing it by hand, or accepting the fields that happen to
    parse, would present a guess as an understanding — which is the thing FR-008
    exists to prevent, wearing better manners.
    """

    async def _bad(**_: Any) -> dict[str, Any]:
        return _response('{"name": "Alex Morgan"}')  # `years` missing

    monkeypatch.setattr(litellm_gateway, "_acompletion", _bad)

    with pytest.raises(litellm_gateway.ExtractionFailedError):
        await litellm_gateway.LiteLLMGateway().complete(
            task="cv_extraction", schema=_Person, prompt="…"
        )


async def test_output_that_is_not_json_at_all_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of O2 — prose where an object was required."""

    async def _prose(**_: Any) -> dict[str, Any]:
        return _response("I'm sorry, I can't help with that.")

    monkeypatch.setattr(litellm_gateway, "_acompletion", _prose)

    with pytest.raises(litellm_gateway.ExtractionFailedError):
        await litellm_gateway.LiteLLMGateway().complete(
            task="cv_extraction", schema=_Person, prompt="…"
        )


async def test_model_resolves_from_the_task_name_not_from_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O3 — the property slice 004 depends on.

    Two task names resolve to two models with no change at the call site. That
    is how docs/08 §3.2.3 becomes configuration: the escalation from Sonnet to
    Opus after a failed revision is a different task name, not a branch inside
    workflow code.
    """
    seen: list[str] = []

    async def _capture(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs["model"])
        return _response('{"name": "Alex", "years": 8}', model=kwargs["model"])

    monkeypatch.setattr(litellm_gateway, "_acompletion", _capture)
    monkeypatch.setattr(
        litellm_gateway,
        "_model_for_task",
        lambda task: {"cheap": "anthropic/claude-sonnet-5"}.get(task, "anthropic/claude-opus-5"),
    )

    gateway = litellm_gateway.LiteLLMGateway()
    await gateway.complete(task="cheap", schema=_Person, prompt="…")
    await gateway.complete(task="expensive", schema=_Person, prompt="…")

    assert seen == ["anthropic/claude-sonnet-5", "anthropic/claude-opus-5"]


async def test_usage_is_returned_with_the_model_actually_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O4 — and the model recorded is the one that ran, not the one requested."""

    async def _ok(**kwargs: Any) -> dict[str, Any]:
        return _response('{"name": "Alex", "years": 8}', model=kwargs["model"])

    monkeypatch.setattr(litellm_gateway, "_acompletion", _ok)

    result = await litellm_gateway.LiteLLMGateway().complete(
        task="cv_extraction", schema=_Person, prompt="…"
    )

    assert result.usage.input_tokens == 1200
    assert result.usage.output_tokens == 340
    assert result.usage.cost >= Decimal("0")
    assert result.usage.is_fixture is False


async def test_fixture_gateway_labels_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """R3 — the label is the whole point.

    Fixture content that could be mistaken for a real extraction is worse than
    no fixture mode at all: it would mean approving invented content into a real
    professional profile.
    """
    result = await fixture_gateway.FixtureGateway().complete(
        task="cv_extraction", schema=_Person, prompt="…"
    )

    assert result.usage.is_fixture is True
    assert result.usage.cost == Decimal("0")
    assert isinstance(result.value, _Person)


async def test_real_gateway_never_claims_to_be_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """The inverse, which is the one that matters on a deployed system."""

    async def _ok(**kwargs: Any) -> dict[str, Any]:
        return _response('{"name": "Alex", "years": 8}', model=kwargs["model"])

    monkeypatch.setattr(litellm_gateway, "_acompletion", _ok)

    result = await litellm_gateway.LiteLLMGateway().complete(
        task="cv_extraction", schema=_Person, prompt="…"
    )

    assert result.usage.is_fixture is False
