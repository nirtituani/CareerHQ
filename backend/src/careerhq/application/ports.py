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


__all__ = ["Completion", "StructuredCompletion", "Usage"]
