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

from careerhq.application.ports import Completion, Usage
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
    """


# -- provider-shaped seams, substituted in tests ----------------------------


async def _acompletion(**kwargs: Any) -> Any:
    return await litellm.acompletion(**kwargs)


def _model_for_task(task: str) -> str:
    return get_settings().model_for_task(task)


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

        response = await _acompletion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract the requested information and reply with a single JSON "
                        "object matching the schema. Reply with JSON only — no prose, no "
                        "code fences. Omit any field you cannot find rather than inventing "
                        "a value."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )

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
                extra={"task": task, "model": model, "error": exc.__class__.__name__},
            )
            raise ExtractionFailedError(
                "The model's response did not match the expected structure."
            ) from exc

        usage = response.get("usage") or {}
        return Completion(
            value=value,
            usage=Usage(
                # The model that actually ran, which a provider may substitute.
                model=str(response.get("model") or model),
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                cost=_completion_cost(response),
                is_fixture=False,
            ),
        )


__all__ = ["ExtractionFailedError", "LiteLLMGateway"]
