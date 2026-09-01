"""A reasoning-step double that answers from the prompt it was handed.

Testing rule 4: a double fed by someone who read the code proves the plumbing
works when values are supplied — never that a model *could* supply them. This
one is given no fact ids, no memory ids and no figures by the test; it parses
all three **out of the rendered prompt**, exactly as a model would have to,
and builds its answer from what it found. A renderer that stopped emitting
the `[fact:]`, `[memory:]` or `[dismissed:]` markers breaks these tests
instead of quietly starving a real model.

It raises on a second call (`ScriptedSeam`'s rule): a double that repeats its
last answer would make an unbounded loop look convergent.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from careerhq.application.ports import Completion, Usage

_FACT = re.compile(r"^\[fact: (?P<id>[^\]]+)\] .*?n=(?P<num>\d+)/(?P<den>\d+)", re.M)
_MEMORY = re.compile(r"^\[memory: (?P<id>[0-9a-f-]{36})\]", re.M)
_DISMISSED = re.compile(r"^\[dismissed: (?P<id>[0-9a-f-]{36})\]", re.M)
_REQ = re.compile(r"^\[req: (?P<id>[0-9a-f-]{36})\] (?P<text>[^(]+)\(", re.M)
_APP = re.compile(r"^\[app: (?P<id>[0-9a-f-]{36})\] (?P<title>.+)$", re.M)


@dataclass(slots=True)
class ParsedPrompt:
    """What the double read out of the reasoning input."""

    facts: dict[str, tuple[int, int]]
    memory_ids: list[str]
    dismissed_ids: list[str]
    #: Grouping-prompt enumerations: requirement rows (id -> verbatim text)
    #: and application titles (id -> title), parsed the way a model would.
    req_texts: dict[str, str]
    app_titles: dict[str, str]
    text: str

    def claim_for(self, fact_id: str, template: str = "{num} of {den} applications counted") -> str:
        num, den = self.facts[fact_id]
        return template.format(num=num, den=den)


def parse_prompt(prompt: str) -> ParsedPrompt:
    return ParsedPrompt(
        facts={
            match.group("id"): (int(match.group("num")), int(match.group("den")))
            for match in _FACT.finditer(prompt)
        },
        memory_ids=[match.group("id") for match in _MEMORY.finditer(prompt)],
        dismissed_ids=[match.group("id") for match in _DISMISSED.finditer(prompt)],
        req_texts={
            match.group("id"): match.group("text").strip() for match in _REQ.finditer(prompt)
        },
        app_titles={
            match.group("id"): match.group("title").strip() for match in _APP.finditer(prompt)
        },
        text=prompt,
    )


@dataclass(slots=True)
class PromptReadingAdvisorSeam:
    """`StructuredCompletion` for advisor tests. `answer` receives the parsed
    prompt for each task call and returns the raw dict the schema validates —
    so every id and figure in the answer provably came from the prompt."""

    answer: Callable[[str, ParsedPrompt], dict[str, Any]]
    cost_per_call: Decimal = Decimal("0.01")

    #: The captured reasoning inputs, in call order — what T026 inspects.
    prompts: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    max_calls: int = 1

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        if len(self.prompts) >= self.max_calls:
            raise AssertionError(
                f"the advisor called the seam {len(self.prompts) + 1} times but this "
                f"double allows {self.max_calls} — a repeating double would make an "
                "unbounded loop look convergent"
            )
        self.prompts.append(prompt)
        self.tasks.append(task)
        raw = self.answer(task, parse_prompt(prompt))
        return Completion(
            value=schema.model_validate(raw),
            usage=Usage(
                model=f"scripted/{task}",
                input_tokens=1_000,
                output_tokens=400,
                cost=self.cost_per_call,
            ),
        )


class BilledFailure(Exception):
    """A provider failure that was still billed — carries `.usage`, which
    `UsageRecorder` duck-types on, so a failed run records real spend."""

    def __init__(self, usage: Usage) -> None:
        super().__init__("scripted provider failure")
        self.usage = usage


@dataclass(slots=True)
class FailingAdvisorSeam:
    """Raises on every call, billed. The SC-005 arm."""

    cost: Decimal = Decimal("0.007")
    calls: int = 0

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        self.calls += 1
        raise BilledFailure(
            Usage(model=f"scripted/{task}", input_tokens=900, output_tokens=0, cost=self.cost)
        )
