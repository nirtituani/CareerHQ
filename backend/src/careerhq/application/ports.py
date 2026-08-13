"""Ports the application layer depends on, implemented in `infrastructure/`.

The specification for this file is
`specs/003-data-foundation/contracts/extraction-seam.md`. Read that for the
reasoning; what follows is the shape it requires.

**This is the artifact slice 004 inherits**, which is why it is defined with one
caller rather than discovered with five.
"""

from __future__ import annotations

from dataclasses import dataclass
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
      configuration keyed by task, which is what lets slice 004 express
      docs/08 §3.2.3 — its escalation from Sonnet to Opus after a failed
      revision is a different task name, not a branch in workflow code (O3).
    * **Usage is returned, not logged internally** (O4).
    * **It is a Protocol**, so `domain/` and `application/` import no provider
      code. Principle V becomes a property of the import graph, asserted by a
      test, rather than a rule someone remembers (O5).

    Multi-step orchestration, tool use, retries with feedback and self-critique
    are **slice 004**. A caller that needs the model to react to its own previous
    output belongs in the agent runtime, not here — that boundary is the scope
    guard this slice relies on.
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


__all__ = ["Completion", "StructuredCompletion", "Usage"]
