"""Ports the application layer depends on, implemented in `infrastructure/`.

The specification for this file is
`specs/003-data-foundation/contracts/extraction-seam.md`. Read that for the
reasoning; what follows is the shape it requires.

**This is the artifact later slices inherit**, which is why it was defined with
one caller rather than discovered with five. There are now four call sites —
`extract_resume`, `extract_job`, `analyze_match`, and the four nodes of the
slice 005 tailoring graph — and the signature has not changed for any of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

# Every completion is validated against a caller-supplied Pydantic model. The
# `BaseModel` bound on each type parameter below is what makes "there is no way
# to get unvalidated text back" a fact about the type signature rather than a
# convention.


class Usage(BaseModel):
    """What one completion consumed.

    Constitution Principle V requires every AI execution to preserve its inputs,
    model configuration, token usage and cost. This is returned to the caller
    rather than logged inside the adapter (obligation O4), so the application
    layer writes the audit record in the same transaction as the work it paid
    for — infrastructure stays dumb, and the trail lands where the data does.
    """

    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    #: Decimal, never float. A per-call cost accumulated over thousands of
    #: extractions in binary floating point drifts, and this is an audit record
    #: rather than a display value.
    cost: Decimal

    #: True only from the fixture adapter. Propagates to `ImportedResume` and is
    #: shown in the interface, because canned content mistaken for a real
    #: extraction would mean approving invented history into a real profile.
    is_fixture: bool = False

    #: Which task asked for this completion — `tailor_plan`, `tailor_review`,
    #: the escalated revision, and so on. `None` as an adapter returns it: the
    #: adapter knows only that it was called, so `UsageRecorder` stamps the
    #: label, being the one party holding both the task name and the bill.
    #: Per-call audit rows read it (T092); a totals-only record could not say
    #: which node spent what, which is exactly what run `cd27b092`'s $0.36
    #: could not answer.
    task: str | None = None


@dataclass(frozen=True, slots=True)
class Completion[T: BaseModel]:
    """A validated result and what it cost.

    `value` has already been validated against the schema the caller passed;
    there is no path through this seam that returns unvalidated text.
    """

    value: T
    usage: Usage


class StructuredCompletion(Protocol):
    """One structured completion. One call in, one validated object out.

    Four properties, each answering a requirement rather than a preference:

    * **`schema` is required and the return is typed.** FR-025 and Principle VI
      become structural (O1).
    * **`task` is a name, not a model.** Model choice resolves from
      configuration keyed by task, which is what lets **slice 005** express
      docs/08 §3.2.3 — its escalation from Sonnet to Opus after a failed
      revision is a different task name, `tailor_revise_escalated`, rather than
      a branch in workflow code (O3). That is now built, not planned.
    * **Usage is returned, not logged internally** (O4).
    * **It is a Protocol**, so `domain/` and `application/` import no provider
      code. Principle V becomes a property of the import graph, asserted by a
      test, rather than a rule someone remembers (O5).

    Multi-step orchestration, tool use and self-critique live **above** this
    seam, in `application/agents/`, and as of slice 005 they exist: the
    tailoring graph loops, reacts to its own output and revises. It does all of
    that by calling `complete()` repeatedly. This signature has no memory, no
    conversation and no tools, and the graph adds none — it holds the state
    itself and passes a fresh prompt each time.

    **This paragraph is a description, not a guarantee.** It once read as though
    the boundary were enforced; nothing executable ever asserted it, and
    `CLAUDE.md` repeated the overstatement until slice 005 corrected both
    (T081, T082). What *is* enforced, by
    `tests/unit/test_architecture.py::test_the_application_layer_imports_no_provider_sdk`,
    is the narrower and more useful property: no module under `application/`
    imports a provider SDK, so nothing above this seam can reach a model except
    through it. A caller that looped without saying so would still be caught by
    that test the moment it tried to talk to a provider directly.
    """

    async def complete[T: BaseModel](
        self,
        *,
        task: str,
        schema: type[T],
        prompt: str,
    ) -> Completion[T]:
        """Run `task`, returning an instance of `schema`.

        Raises when the provider's output cannot be validated against `schema`.
        That is extraction failure, never partial acceptance (O2).
        """
        ...


def safe_validation_errors(exc: Exception) -> list[dict[str, str]]:
    """Which field failed and why — never the value that failed.

    Added after the first real tailoring run failed with `error:
    "ValidationError"` and nothing else. That named the exception class and not
    one useful fact: not the field, not the constraint, not whether the model
    had returned prose or a well-formed object missing a key. Diagnosing it took
    a reproduction; it should have taken one line of the log.

    Three deliberate exclusions, because this record travels into logs a third
    party operates and the value that failed is model output derived from a CV:

    * **`include_input=False`** drops the offending value. This is the whole
      privacy guarantee and it is asserted by a test.
    * **`include_context=False`** drops constraint context, which can echo input
      for some error types.
    * **`msg` is kept only for `value_error`**, where the text is our own
      validator's sentence — "a overstated finding must name the item it
      concerns" is the entire diagnosis. Pydantic's *parsing* messages can quote
      a fragment of the input (`uuid_parsing` reports the character it choked
      on), so those are dropped in favour of `type`, which is a fixed code.
    """
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        # Not a pydantic failure — a JSONDecodeError, say. `type(exc).__name__`
        # is already logged beside this and says everything there is to say.
        return []

    reported: list[dict[str, str]] = []
    for error in errors(include_url=False, include_context=False, include_input=False):
        entry = {
            "at": ".".join(str(part) for part in error.get("loc", ())),
            "type": str(error.get("type", "")),
        }
        if entry["type"] == "value_error":
            entry["why"] = str(error.get("msg", ""))
        reported.append(entry)
    return reported


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UsageRecorder:
    """A `StructuredCompletion` that remembers what every call cost.

    **Added because the first real tailoring run reported `0 tokens, $0` for a
    run that made three provider calls and was billed for all three.** Usage was
    summed from the graph's return value, and a graph that raises does not
    return — so a failed run's accounting was not merely incomplete, it was
    silently zero. A run that reads as free is worse than one that reads as
    unrecorded: nobody investigates a free run.

    This wraps the seam rather than changing it. The graph, the state and the
    nodes are untouched, and `state.usage` still accumulates exactly as research
    R3 requires — this is simply the record that survives an exception, and it is
    what `tailor_resume` reports from on **both** paths, so success and failure
    cannot drift into two different sums.

    **It duck-types on `.usage`** rather than importing `ExtractionFailedError`,
    which lives in `infrastructure/`. An exception that carries a `Usage` is one
    the provider billed for; one that does not never reached the provider's
    accounting, and inventing a zero-token entry for it would make the call count
    wrong in the other direction.

    Recording is **not** recovering: the exception is always re-raised. Whether a
    failed call should be retried is a separate decision, deliberately not taken
    in slice 005.
    """

    inner: StructuredCompletion
    calls: list[Usage] = field(default_factory=list)

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        # Each entry is stamped with the task that made the call — the adapter
        # cannot do it, knowing only that it was called, and without the label
        # the per-call audit rows (T092) could not say which node spent what.
        # The stamped copy lives only in `calls`; the caller's `result.usage`
        # travels on unchanged.
        try:
            result = await self.inner.complete(task=task, schema=schema, prompt=prompt)
        except Exception as exc:
            billed = getattr(exc, "usage", None)
            if isinstance(billed, Usage):
                self.calls.append(billed.model_copy(update={"task": task}))
            raise
        self.calls.append(result.usage.model_copy(update={"task": task}))
        return result

    @property
    def total_input_tokens(self) -> int:
        return sum(call.input_tokens for call in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(call.output_tokens for call in self.calls)

    @property
    def total_cost(self) -> Decimal:
        """Decimal throughout. An audit value accumulated over many calls."""
        return sum((call.cost for call in self.calls), start=Decimal("0"))

    @property
    def any_fixture(self) -> bool:
        return any(call.is_fixture for call in self.calls)


__all__ = [
    "Completion",
    "StructuredCompletion",
    "Usage",
    "UsageRecorder",
    "safe_validation_errors",
]
