"""A completion seam that answers from a script, one entry per call.

**Why this is not in `fixture_gateway.py`**, which is what tasks.md T026
originally said. That adapter is production code, selected by
`AI_PROVIDER=fixture` for demos, and it answers by filling canned values by
field name. Scripting a *sequence* of differing answers to the same task is a
test concern and nothing else — putting the API there would ship a mechanism
only tests use, into the one adapter whose entire justification is that its
output is labelled as fake. So it lives here, and T026 was amended.

**Why a sequence per task name is necessary at all.** The tailoring workflow
calls `tailor_review` up to three times in one run, and the whole point of the
loop is that the answers differ: reject, then reject again, then accept. A seam
returning one fixed answer per task can only ever exercise the path where the
first review passes.

That is the same trap slice 004 recorded and paid for: a branch went unexercised
for the entire slice because the existing test accepted `{202, 409}` and always
got 409. An untestable path is an untested path, and the paths this unlocks are
the revision bound (FR-013) and the grounding discard (FR-018) — both release
blockers.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from careerhq.application.ports import Completion, Usage


class ScriptExhausted(AssertionError):
    """The workflow asked for more calls than the script provides.

    An `AssertionError` rather than a `RuntimeError` because it means the test's
    expectation of the workflow was wrong — usually that the loop ran more times
    than it should have, which is exactly what FR-013 bounds.
    """


@dataclass(slots=True)
class Call:
    """One completion the workflow asked for. Recorded so tests can assert
    *which model was chosen for which attempt*, which is how the Sonnet →
    Opus escalation is proved to be a task-name swap rather than a branch."""

    task: str
    prompt: str


@dataclass(slots=True)
class ScriptedSeam:
    """`StructuredCompletion` that pops one scripted answer per call.

    ``script`` maps a task name to the answers it should return, in order. Each
    answer is a plain dict validated against whatever schema the caller passes,
    so a test states only the fields it cares about and lets the schema's own
    validation do the rest — which means a scripted answer that would fail
    validation in production fails here too.
    """

    script: dict[str, Sequence[dict[str, Any]]]
    #: Per-call token counts, so a test can assert the audit sums correctly
    #: rather than only that it is non-zero.
    input_tokens: int = 1_000
    output_tokens: int = 500
    cost_per_call: Decimal = Decimal("0.01")

    calls: list[Call] = field(default_factory=list)
    _consumed: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        answers = self.script.get(task)
        if answers is None:
            raise ScriptExhausted(
                f"the workflow called task {task!r}, which the script does not cover. "
                f"Scripted tasks: {sorted(self.script)}"
            )

        index = self._consumed[task]
        if index >= len(answers):
            raise ScriptExhausted(
                f"task {task!r} was called {index + 1} times but the script provides "
                f"{len(answers)}. If this is the revision loop, it ran longer than "
                f"MAX_REVISIONS allows."
            )

        self._consumed[task] = index + 1
        self.calls.append(Call(task=task, prompt=prompt))

        return Completion(
            value=schema.model_validate(answers[index]),
            usage=Usage(
                model=f"scripted/{task}",
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cost=self.cost_per_call,
            ),
        )

    # -- assertions tests reach for often -----------------------------------

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def tasks_called(self) -> list[str]:
        """In order, so the escalation shows up as a sequence."""
        return [call.task for call in self.calls]

    def times_called(self, task: str) -> int:
        return self._consumed[task]
