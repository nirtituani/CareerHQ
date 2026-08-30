"""A completion seam that cannot spend past the ceiling.

**Two checks per call, because a projection is a belief and a bill is a fact.**
Before the call, the measured cost of that task must fit in what is left; after it,
the actual cost is recorded. A guard that only reconciles afterwards has already
spent the money, and a guard that only estimates never notices being wrong.

**It wraps rather than replaces.** The workflow calls `complete()` exactly as it
always does and cannot tell this is here, so nothing about what is measured changes
because it is being measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel

from careerhq.application.evaluation.budget import (
    ESTIMATED_JUDGE_COST,
    MEASURED_TASK_COST,
    CeilingExceededError,
    SpendGuard,
)
from careerhq.application.ports import Completion, StructuredCompletion, Usage


@dataclass
class GuardedCompletion:
    """Wraps a seam so every call is checked against, and charged to, a `SpendGuard`."""

    inner: StructuredCompletion
    guard: SpendGuard
    #: Every call made, in order, for the result file's itemised bill.
    calls: list[dict[str, object]] = field(default_factory=list)

    def _reserve(self, task: str) -> Decimal:
        """What this call is expected to cost, refusing now if it cannot fit.

        An unknown task reserves the most expensive measured task rather than zero:
        a new task name must not be able to slip past the ceiling by being unknown.
        """
        expected = MEASURED_TASK_COST.get(
            task,
            ESTIMATED_JUDGE_COST if task.startswith("eval_") else max(MEASURED_TASK_COST.values()),
        )
        if self.guard.spent + expected > self.guard.ceiling:
            raise CeilingExceededError(
                f"refused BEFORE calling {task}: ${self.guard.spent:.6f} already spent and this "
                f"call is expected to cost ${expected:.6f}, which would exceed the "
                f"${self.guard.ceiling:.2f} ceiling. Stopping rather than improvising."
            )
        return expected

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        self._reserve(task)
        try:
            result = await self.inner.complete(task=task, schema=schema, prompt=prompt)
        except Exception as exc:
            # **A call that failed validation was still billed**, and this is the
            # only place that knows it. `ExtractionFailedError` carries the usage
            # precisely so a failure is not reported as free — the same reason
            # `UsageRecorder` wraps the seam for the tailoring graph. Missing it
            # here was a hole in the ceiling: enough failing calls would spend past
            # it while the guard read $0.
            #
            # Found the first time a real judge call failed validation, which cost
            # a measurement rather than money.
            # **Duck-typed on `.usage`, never imported**, exactly as
            # `UsageRecorder` does and for the same reason: `ExtractionFailedError`
            # lives in `infrastructure/` and this layer must not reach into it. An
            # exception carrying a `Usage` is one the provider billed for; one that
            # does not never reached the provider's accounting, and inventing a
            # zero-token entry would make the count wrong in the other direction.
            billed = getattr(exc, "usage", None)
            if isinstance(billed, Usage):
                self.guard.record(billed.cost, task=task)
                self.calls.append(
                    {
                        "task": task,
                        "model": billed.model,
                        "input_tokens": billed.input_tokens,
                        "output_tokens": billed.output_tokens,
                        "cost": float(billed.cost),
                        "cumulative": float(self.guard.spent),
                        "outcome": "billed, failed validation",
                    }
                )
            raise
        self.guard.record(result.usage.cost, task=task)
        self.calls.append(
            {
                "task": task,
                "model": result.usage.model,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cost": float(result.usage.cost),
                "cumulative": float(self.guard.spent),
            }
        )
        return result


__all__ = ["GuardedCompletion"]
