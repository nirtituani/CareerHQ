"""What flows between the nodes.

CareerHQ's vocabulary, deliberately **not** LangChain message objects. The state
is what `tailor_resume.py` reads in order to persist, so expressing it in the
orchestrator's types would make the use case depend on the orchestrator — which
is the coupling contract O1 exists to prevent.

**Two keys carry append reducers, and that is load-bearing.** LangGraph merges
node return values into state key by key, and a key with no reducer is
*overwritten*. Measured against the installed 1.2.11 (research R3): three nodes
each returning one element left `['c']`.

Applied to `usage`, that silently keeps one record out of up to seven — an
incomplete audit trail under Principle V, a cost figure wrong by up to 7x, and
nothing raises. It reads as a cheap run. `findings` has the same shape and the
same consequence: the Reviewer's earlier objections would vanish, leaving a run
that looks like it never caught anything.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any

from careerhq.application.ports import Usage
from careerhq.domain.schemas.tailoring import DraftedItem, ReviewFinding


@dataclass
class TailoringState:
    """One run's working state.

    Not frozen: LangGraph constructs a new instance per merge, and the nodes
    never mutate what they are given — they return partial updates. Freezing it
    would add a constraint the runtime does not need and does not check.
    """

    # -- inputs, set once before the graph runs ---------------------------
    #: The posting, and the requirements the match analysis already extracted.
    job: dict[str, Any] = field(default_factory=dict)
    #: The profile's facts, rendered once. Every node reads it; none refetch it.
    master: str = ""
    #: The existing match analysis, **read-only** (FR-011). Its verdicts are what
    #: tell the plan which gaps must not be misrepresented.
    match: dict[str, Any] = field(default_factory=dict)

    # -- produced by the nodes --------------------------------------------
    plan: dict[str, Any] | None = None
    items: list[DraftedItem] = field(default_factory=list)
    confidence: int = 0

    #: Which revision this is: 0 before any, 1 after the first, 2 after the
    #: escalated one. The conditional edge reads it, and it selects the task
    #: name that performs the next revision.
    attempt: int = 0

    #: Guidance actually consumed, recorded so FR-016 has something to persist
    #: and slice 007 has something to measure.
    guidelines: list[dict[str, str]] = field(default_factory=list)

    # -- accumulated across calls -----------------------------------------
    #: See the module docstring. Without `operator.add` this keeps one entry.
    usage: Annotated[list[Usage], operator.add] = field(default_factory=list)
    #: Findings from **every** review pass, not only the last. A fabrication
    #: caught on attempt one and fixed on attempt two still happened, and the
    #: record of it is the evidence the guardrail ran.
    findings: Annotated[list[ReviewFinding], operator.add] = field(default_factory=list)


__all__ = ["TailoringState"]
