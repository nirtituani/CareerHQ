"""The gateway adapters (T016, T017, T018).

No test here contacts a provider. The LiteLLM call is substituted at the module
boundary, which is what FR-027 requires and what T049 verifies from the other
direction by unsetting the key entirely.
"""

from __future__ import annotations

import json
import logging
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


# -- T-fix-1: a schema failure must say which field, and nothing the model wrote


class _Review(BaseModel):
    """Shaped like `ReviewResult`, so the diagnostics are exercised against the
    schema that actually failed in production."""

    confidence: int
    finding: str


async def test_a_schema_failure_logs_which_field_and_why(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The real run failed with `error: "ValidationError"` and nothing else.

    That named the exception class and not one useful fact: not the field, not
    the constraint, not whether the model had returned prose or a well-formed
    object with a missing key. Diagnosing it took a reproduction; it should have
    taken one line of the log.
    """

    async def _bad(**_: Any) -> dict[str, Any]:
        return _response('{"confidence": 88}')  # `finding` missing

    monkeypatch.setattr(litellm_gateway, "_acompletion", _bad)

    with caplog.at_level(logging.INFO, logger="careerhq.ai"):
        with pytest.raises(litellm_gateway.ExtractionFailedError):
            await litellm_gateway.LiteLLMGateway().complete(
                task="tailor_review", schema=_Review, prompt="…"
            )

    record = next(
        r for r in caplog.records if r.msg == "extraction output did not satisfy the schema"
    )
    assert record.task == "tailor_review"  # type: ignore[attr-defined]
    assert record.schema_errors == [{"at": "finding", "type": "missing"}]  # type: ignore[attr-defined]


async def test_a_schema_failure_never_logs_what_the_model_wrote(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The constraint that makes the diagnostic above safe to keep.

    `ValidationError.errors()` carries an `input` key holding the offending
    value — which here is model output derived from a CV, and this record
    travels into logs a third party operates. `include_input=False` is the
    explicit guarantee, and this is what proves it stays.

    `msg` is kept only for `value_error`, where the text is our own validator's
    sentence. Pydantic's parsing messages can echo a fragment of the input —
    `uuid_parsing` reports the character it choked on — so they are dropped in
    favour of the error `type`, which is a fixed code.
    """
    secret = "Ran Kubernetes clusters for the Ministry of Fabricated Experience"

    async def _bad(**_: Any) -> dict[str, Any]:
        return _response(json.dumps({"confidence": "not-a-number", "finding": secret}))

    monkeypatch.setattr(litellm_gateway, "_acompletion", _bad)

    with caplog.at_level(logging.INFO, logger="careerhq.ai"):
        with pytest.raises(litellm_gateway.ExtractionFailedError):
            await litellm_gateway.LiteLLMGateway().complete(
                task="tailor_review", schema=_Review, prompt="…"
            )

    everything = " ".join(
        f"{r.getMessage()} {getattr(r, 'schema_errors', '')}" for r in caplog.records
    )
    assert secret not in everything
    assert "not-a-number" not in everything
    # Still diagnostic: the field and the constraint survive.
    assert "confidence" in everything


async def test_our_own_validator_message_survives(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A `value_error` message is text this repository wrote, not the model.

    It is also the single most useful line — "a overstated finding must name the
    item it concerns" is the whole diagnosis, where `type: value_error` alone
    would send the next reader back to the source.
    """
    from careerhq.domain.schemas.tailoring import ReviewResult

    async def _bad(**_: Any) -> dict[str, Any]:
        return _response(
            json.dumps(
                {
                    "confidence": 78,
                    "findings": [
                        {"kind": "overstated", "detail": "Inflated.", "quoted_text": "Owned"}
                    ],
                }
            )
        )

    monkeypatch.setattr(litellm_gateway, "_acompletion", _bad)

    with caplog.at_level(logging.INFO, logger="careerhq.ai"):
        with pytest.raises(litellm_gateway.ExtractionFailedError):
            await litellm_gateway.LiteLLMGateway().complete(
                task="tailor_review", schema=ReviewResult, prompt="…"
            )

    errors = next(
        r.schema_errors  # type: ignore[attr-defined]
        for r in caplog.records
        if r.msg == "extraction output did not satisfy the schema"
    )
    assert errors[0]["at"] == "findings.0"
    assert "must name the item it concerns" in errors[0]["why"]


# -- T-fix-3: the provider billed for the call that failed validation


async def test_a_validation_failure_carries_the_usage_it_was_billed_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The call happened. The tokens were spent. The audit record must say so.

    Before this, a run that failed validation recorded `0 tokens, $0` — for the
    failing call **and** for every successful call before it, because usage was
    only summed after the graph returned. Principle V requires the audit record
    to be written in the same transaction as the work; a run that silently
    reports zero cost is worse than one reporting none, because it reads as free.
    """

    async def _bad(**_: Any) -> dict[str, Any]:
        return _response('{"confidence": 88}')

    monkeypatch.setattr(litellm_gateway, "_acompletion", _bad)
    monkeypatch.setattr(litellm_gateway, "_completion_cost", lambda _: Decimal("0.031"))

    with pytest.raises(litellm_gateway.ExtractionFailedError) as failed:
        await litellm_gateway.LiteLLMGateway().complete(
            task="tailor_review", schema=_Review, prompt="…"
        )

    usage = failed.value.usage
    assert usage is not None
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 340
    assert usage.cost == Decimal("0.031")
    assert usage.is_fixture is False


async def test_the_calibrated_tasks_carry_their_configured_thinking_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2's and PE1's adoptions: `tailor_draft` and `tailor_plan` run explicit
    adaptive thinking at the configured effort, and **only** tasks with an
    effort configured send the parameters at all — every other task's request
    is byte-identical to before, which is what confines each calibration to
    exactly the tasks it was measured on.

    Measured basis: E2 (24 treatment runs) — ~59% of the draft's billed output
    was invisible default-effort thinking; medium cut draft cost ~50% and
    latency ~53% with judge-equivalent final quality. PE1 (2026-09-02, paired
    against the pc1 post-contract pass) — the Action Contract's explicit
    three-way decision tripled the plan call's billed thinking; medium cut
    plan output tokens 73% and plan cost 61% with action validity 100%, zero
    keep violations, zero ungrounded, and no revision-rate increase.

    **Review is deliberately not configured.** Opus review is the grounding
    guardrail and no effort experiment has measured it; it must keep the
    provider default until one does.
    """
    seen: list[dict[str, Any]] = []

    async def _capture(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return _response('{"name": "Alex", "years": 8}')

    monkeypatch.setattr(litellm_gateway, "_acompletion", _capture)

    gateway = litellm_gateway.LiteLLMGateway()
    await gateway.complete(task="tailor_draft", schema=_Person, prompt="…")
    await gateway.complete(task="tailor_plan", schema=_Person, prompt="…")
    await gateway.complete(task="tailor_review", schema=_Person, prompt="…")

    draft, plan, review = seen
    for calibrated in (draft, plan):
        assert calibrated["thinking"] == {"type": "adaptive"}
        assert calibrated["output_config"] == {"effort": "medium"}
    # No other stage changes: the keys must be absent, not merely None — an
    # explicit None would still be a different request than today's.
    assert "thinking" not in review
    assert "output_config" not in review


def test_effort_is_resolved_from_the_task_name() -> None:
    """The same discipline as `model_for_task`: callers name the task, never
    the parameters. An unconfigured task gets None — the provider default,
    exactly what every call sent before this setting existed."""
    from careerhq.config import get_settings

    settings = get_settings()
    assert settings.effort_for_task("tailor_draft") == "medium"
    assert settings.effort_for_task("tailor_plan") == "medium"
    for task in ("tailor_review", "tailor_revise", "tailor_revise_escalated"):
        assert settings.effort_for_task(task) is None
