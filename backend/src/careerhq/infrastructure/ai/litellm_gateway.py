"""The LiteLLM adapter — the only module in this codebase that imports litellm.

That exclusivity is not a style preference. Constitution Principle V says
business domains must not call AI providers, and the only way that stays true is
if exactly one module can. A test walks the import graph and asserts it, because
a boundary maintained by reviewer attention is not a boundary.

Everything provider-shaped lives behind `_acompletion`, `_model_for_task` and
`_completion_cost`, which are module-level so tests can substitute them. The
suite therefore runs with no API key and no network (FR-027).
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any

import litellm
from pydantic import BaseModel

from careerhq.application.ports import Completion, Usage, safe_validation_errors
from careerhq.config import get_settings

logger = logging.getLogger("careerhq.ai")

#: Fenced code blocks the model may wrap JSON in despite being asked not to.
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class ExtractionFailedError(RuntimeError):
    """The provider answered, and the answer could not be used.

    Deliberately distinct from a transport failure. A model returning prose, or
    an object missing required fields, has told you it did not understand the
    document — so this surfaces to the user as FR-008 ("extraction produced
    nothing usable") rather than as an error implying the system broke.

    The message never includes the provider's raw output: it can contain the
    contents of a CV, and this exception travels into logs.

    **It carries the usage it was billed for.** The provider ran the completion
    and charged for it; whether the result validated is our problem, not the
    accountant's. Before this, a run that failed validation recorded `0 tokens,
    $0` — which reads as a free run rather than an unrecorded one, and Principle
    V asks for the opposite. `UsageRecorder` in `application/ports.py` reads this
    attribute by duck-typing, so nothing above the seam imports this module.
    """

    def __init__(self, message: str, *, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


# -- provider-shaped seams, substituted in tests ----------------------------


async def _acompletion(**kwargs: Any) -> Any:
    return await litellm.acompletion(**kwargs)


def _model_for_task(task: str) -> str:
    return get_settings().model_for_task(task)


def _effort_for_task(task: str) -> str | None:
    return get_settings().effort_for_task(task)


def _completion_cost(response: Any) -> Decimal:
    """Best-effort cost from the provider's own accounting.

    LiteLLM prices per model; if it cannot (an unknown model, a substituted
    response in tests) the call is still recorded with a zero cost and a warning
    rather than failing. Losing an extraction because its price could not be
    computed would be the wrong trade — but a silent zero would undermine the
    audit record, so it is logged.
    """
    try:
        return Decimal(str(litellm.completion_cost(completion_response=response)))
    except Exception as exc:  # pragma: no cover - provider accounting varies
        logger.warning("could not price completion", extra={"error": str(exc)})
        return Decimal("0")


def _usage_of(response: Any, model: str) -> Usage:
    """What this call cost, read from the provider's own accounting.

    Extracted so the success path and the validation-failure path report the
    same call the same way. They used to differ by one reporting nothing at all.
    """
    usage = response.get("usage") or {}
    return Usage(
        # The model that actually ran, which a provider may substitute.
        model=str(response.get("model") or model),
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        cost=_completion_cost(response),
        is_fixture=False,
    )


def _parse_json(raw: str) -> Any:
    fenced = _FENCE.match(raw)
    return json.loads(fenced.group(1) if fenced else raw)


class LiteLLMGateway:
    """`StructuredCompletion` over LiteLLM.

    Conforms structurally rather than by inheritance — the Protocol has no base
    class, which is what lets a plain object stand in for it in tests.
    """

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        model = _model_for_task(task)

        # Thinking effort, when the task has one configured (E2: tailor_draft
        # at "medium"). Sonnet 5 thinks adaptively by default at effort high,
        # billed invisibly as output tokens; a configured task states its depth
        # explicitly. An unconfigured task adds NOTHING to the request — the
        # keys are absent, not None — so every other stage's call is
        # byte-identical to what it sent before this existed.
        effort = _effort_for_task(task)
        thinking_kwargs: dict[str, Any] = (
            {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
            if effort
            else {}
        )

        # The schema is sent, not described. An early version said "matching the
        # schema" without including one, and the model answered plausibly and
        # wrongly — `confidence: "high"` where a float was required, and
        # `language` where the field is `name`. It was caught by validation
        # rather than reaching a user, but an extraction that always fails is
        # not much better than one that lies.
        response = await _acompletion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Reply with a single JSON object conforming to this JSON Schema. "
                        "Reply with JSON only — no prose, no code fences.\n\n"
                        # This said "between 0 and 1" until the first real
                        # tailoring run. That was written for slice 003's
                        # extraction schemas, where confidence is a fraction —
                        # but it is sent with *every* task, and `ReviewResult`
                        # types confidence as an integer 0-100. One sentence
                        # cannot serve both, and the schema already carries the
                        # range per field, so it no longer tries.
                        "Every `confidence` is a NUMBER, never a word — in the range the "
                        "schema gives for that field.\n"
                        "Use exactly the field names in the schema.\n"
                        # Qualified for the same reason. Unconditional, this
                        # invited omitting a field the schema's own description
                        # marks as conditionally required.
                        "Omit anything you cannot find rather than inventing a value, unless "
                        "the field's description says it is required.\n\n"
                        f"{json.dumps(schema.model_json_schema())}"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            **thinking_kwargs,
        )

        # Read once, before validation, so the success and failure paths report
        # the same billed call rather than two implementations of one sum.
        billed = _usage_of(response, model)

        content = response["choices"][0]["message"]["content"]
        try:
            payload = _parse_json(content)
            value = schema.model_validate(payload)
        except Exception as exc:
            # Validation failure IS extraction failure (O2, FR-025). Accepting
            # the fields that happen to parse would present a guess as an
            # understanding.
            logger.info(
                "extraction output did not satisfy the schema",
                extra={
                    "task": task,
                    "model": model,
                    "error": exc.__class__.__name__,
                    # Which field, and why. Never the value — see `_schema_errors`.
                    "schema_errors": safe_validation_errors(exc),
                },
            )
            raise ExtractionFailedError(
                "The model's response did not match the expected structure.",
                usage=billed,
            ) from exc

        return Completion(value=value, usage=billed)


__all__ = ["ExtractionFailedError", "LiteLLMGateway"]
