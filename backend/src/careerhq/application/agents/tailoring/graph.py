"""The workflow: four nodes, one conditional edge, bounded at two revisions.

```
[plan] --> [draft] --> [review] --> clears? --yes--> END
               ^                        |
               |                        no, budget remains
               +------- [revise] <------+
```

**Every node is state-in, state-out.** It builds a prompt, awaits the completion
seam, and folds the result into state. No node holds a database session, writes
a row, imports a provider SDK, or decides a business outcome that survives the
run. Contract O2, and the import-graph test enforces the provider half of it.

**The conditional edge is the entire self-critique mechanism**, and it reads
`finalisation_rules`, so the threshold and the bound live in versioned
application code rather than in the orchestrator.

Compiled **without a checkpointer**. Approval starts no further graph execution,
so durable pause/resume has no requirement behind it, and a second persistent
representation of a workflow whose state CareerHQ already owns would leave no
answer to which one is authoritative (design §3.2, research R1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from careerhq.application.agents.tailoring.prompts import (
    build_draft_prompt,
    build_plan_prompt,
    build_review_prompt,
    build_revise_prompt,
)
from careerhq.application.agents.tailoring.state import RaisedFinding, TailoringState
from careerhq.application.finalisation_rules import should_revise, task_for_revision
from careerhq.application.ports import StructuredCompletion
from careerhq.domain.schemas.tailoring import (
    ReviewFinding,
    ReviewResult,
    TailoredDraft,
    TailoringPlan,
)

#: Task names. Declared here rather than inline so `test_task_model_config.py`
#: can find them by AST and require each to have an `llm_model_<task>` entry —
#: the fallback is Opus, and a missing entry costs ~2.5x while saying nothing.
TASK_PLAN = "tailor_plan"
TASK_DRAFT = "tailor_draft"
TASK_REVIEW = "tailor_review"

Node = Callable[[TailoringState], Awaitable[dict[str, Any]]]


def active_findings(state: TailoringState) -> list[ReviewFinding]:
    """The findings that describe the draft **as it now stands**.

    `state.findings` accumulates across passes on purpose: it is the evidence
    the guardrail ran, and persistence needs all of it. The revision decision
    needs something narrower. `clears_review` fails on any `ungrounded`
    finding, so feeding it the whole history made a fabrication caught on pass
    0 permanently unclearable — the gate could never be passed again however
    well the Reviser fixed it, and the run spent its entire budget every time.

    Selecting the current pass is sound because of what the Reviewer is shown:
    `_REVIEW` is built from `compose_resume`, the **resulting resume**, not
    from a diff. Every pass is therefore a complete re-judgement of the whole
    document. A claim that is still unsupported is re-reported and still
    blocks; one the Reviser fixed is simply absent, which is the Reviewer
    saying so rather than this function assuming it.

    Note this is deliberately *not* in `finalisation_rules`: those rules judge
    findings and have no business reading the pass label, which is state
    bookkeeping. The unwrapping has always happened on this side of the call.
    """
    return [raised.finding for raised in state.findings if raised.attempt == state.attempt]


def build_tailoring_graph(completion: StructuredCompletion) -> Any:
    """Compile the graph, with the seam bound into its nodes.

    The seam arrives as an argument rather than being imported, which is what
    lets a test drive the whole loop with a scripted double and no provider
    (FR-045).
    """

    async def plan(state: TailoringState) -> dict[str, Any]:
        result = await completion.complete(
            task=TASK_PLAN, schema=TailoringPlan, prompt=build_plan_prompt(state)
        )
        return {"plan": result.value.model_dump(mode="json"), "usage": [result.usage]}

    async def draft(state: TailoringState) -> dict[str, Any]:
        result = await completion.complete(
            task=TASK_DRAFT, schema=TailoredDraft, prompt=build_draft_prompt(state)
        )
        return {"items": list(result.value.items), "usage": [result.usage]}

    async def review(state: TailoringState) -> dict[str, Any]:
        result = await completion.complete(
            task=TASK_REVIEW, schema=ReviewResult, prompt=build_review_prompt(state)
        )
        return {
            "confidence": result.value.confidence,
            # Also appended to the per-pass record: `confidence` keeps only the
            # latest value — the edge and the final score both mean "the
            # current draft" — so without this accumulator the first pass's
            # judgement of a revised run is destroyed before persistence.
            "confidences": [result.value.confidence],
            # Appended, not replaced: an objection raised on attempt one and
            # fixed on attempt two still happened, and is the evidence the
            # guardrail ran. Each finding is paired **here** with the pass that
            # raised it — this node is the one place that knows which attempt
            # is running, and the model-facing schema must not carry a field
            # the model has no honest basis to fill.
            "findings": [
                RaisedFinding(finding=f, attempt=state.attempt) for f in result.value.findings
            ],
            "usage": [result.usage],
        }

    async def revise(state: TailoringState) -> dict[str, Any]:
        # The escalation from Sonnet to Opus is a **task name**, resolved to a
        # model by configuration. Not a branch on a model, and not a decision
        # this node makes (contract O4).
        task = task_for_revision(state.attempt)
        result = await completion.complete(
            task=task, schema=TailoredDraft, prompt=build_revise_prompt(state)
        )
        return {
            # A **delta**, by the prompt's own rule 4: only the items being
            # changed. `state.items` carries `merge_drafted_items` as its
            # reducer, which folds this over the standing draft — without it,
            # every draft decision not re-emitted here was silently lost.
            "items": list(result.value.items),
            "attempt": state.attempt + 1,
            "usage": [result.usage],
        }

    def after_review(state: TailoringState) -> str:
        """The self-critique loop, in one decision.

        Delegates to `finalisation_rules` rather than deciding here, so the
        threshold and the bound stay versioned application code. Exhausting the
        budget returns `END` — a **normal exit**, not an error.
        """
        if should_revise(
            confidence=state.confidence,
            # Unwrapped here: the rules judge the Reviewer's findings, and the
            # pass label is state bookkeeping they have no business reading.
            #
            # **The current pass only.** `state.findings` accumulates for the
            # audit record, but `clears_review` fails on any `ungrounded`
            # finding — so passing the history made a fabrication caught on
            # pass 0 permanently unclearable, and every such run spent its
            # whole budget on revisions with nothing left to fix. The Reviewer
            # re-judges the composed resume each pass, so a claim that is
            # still unsupported is re-reported and still blocks (T096).
            findings=active_findings(state),
            attempt=state.attempt,
        ):
            return "revise"
        return END

    graph: StateGraph[TailoringState, None, TailoringState, TailoringState] = StateGraph(
        TailoringState
    )
    graph.add_node("plan", plan)
    graph.add_node("draft", draft)
    graph.add_node("review", review)
    graph.add_node("revise", revise)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "draft")
    graph.add_edge("draft", "review")
    graph.add_conditional_edges("review", after_review, {"revise": "revise", END: END})
    graph.add_edge("revise", "review")

    return graph.compile()


__all__ = [
    "TASK_DRAFT",
    "TASK_PLAN",
    "TASK_REVIEW",
    "active_findings",
    "build_tailoring_graph",
]
