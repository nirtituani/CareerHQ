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


@dataclass(frozen=True, slots=True)
class RaisedFinding:
    """One Reviewer finding, paired with the pass that raised it.

    The pairing happens **here, in state, at append time** — the review node is
    the one place that knows which pass is running. It deliberately does not
    live in the model-facing `ReviewFinding` schema: the provider fills that
    schema, and the model has no honest basis to say which attempt it is. A
    field it would have to be told the answer to is a field it can get wrong.

    Without this, every persisted finding was stamped with the run's *final*
    attempt, and a fabrication caught on the first review and fixed on the
    second was indistinguishable from one raised at the end. The information
    was destroyed in state, upstream of persistence — which is why a write-time
    fix alone could not work (T093).
    """

    finding: ReviewFinding
    #: The state's `attempt` at the moment of review: 0 for the first pass,
    #: 1 after one revision, 2 after the escalated one. The same 0-2 scale as
    #: `TailoringRun.attempts`, so the two read together.
    attempt: int


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
    #: This is the **grounding** source: a claim is true if it traces to
    #: something here, including facts no draft touched.
    master: str = ""
    #: The same facts, structured — `_render_master`'s second return value,
    #: which the use case already computes to build version rows. Carried here
    #: so `compose_resume` can show the Reviewer the resume that *results* from
    #: a draft rather than the draft alone. No new query; nothing refetches.
    master_items: list[dict[str, Any]] = field(default_factory=list)
    #: The existing match analysis, **read-only** (FR-011). Its verdicts are what
    #: tell the plan which gaps must not be misrepresented.
    match: dict[str, Any] = field(default_factory=dict)

    # -- produced by the nodes --------------------------------------------
    plan: dict[str, Any] | None = None
    items: list[DraftedItem] = field(default_factory=list)
    #: The **latest** review's confidence — deliberately overwritten per pass,
    #: because the conditional edge and the version's final score both mean
    #: "the current draft's judgement". The per-pass history is `confidences`.
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
    #: record of it is the evidence the guardrail ran. Each entry carries the
    #: pass that raised it — see `RaisedFinding` for why the pairing is made
    #: here rather than in the model-facing schema.
    findings: Annotated[list[RaisedFinding], operator.add] = field(default_factory=list)
    #: Every review pass's confidence, in pass order. `confidence` above keeps
    #: only the latest value by design; without this accumulator the first
    #: pass's judgement of a revised run is destroyed before anything can
    #: persist it (T093).
    confidences: Annotated[list[int], operator.add] = field(default_factory=list)


__all__ = ["RaisedFinding", "TailoringState"]
