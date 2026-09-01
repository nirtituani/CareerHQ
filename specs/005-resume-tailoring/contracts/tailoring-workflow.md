# Contract — the tailoring workflow

The boundary between LangGraph and CareerHQ, stated so that violating it is visible in a diff.

Companion to `specs/003-data-foundation/contracts/extraction-seam.md`, which this **extends without
modifying**. That contract's docstring reserved this slice: *"A caller that needs the model to react
to its own previous output belongs in the agent runtime, not here."*

---

## O1 — LangGraph orchestrates; it owns nothing

| LangGraph is responsible for | CareerHQ is responsible for |
|---|---|
| The graph, its nodes and edges | Persistent run and version state |
| Transitions and conditional branching | Draft, review and final content |
| The bounded revision loop | Human approval state |
| Executing the workflow | Audit: model, usage, cost |
| A visual representation of the workflow | Business invariants, ownership, authorization |

**The test of this contract**: deleting every LangGraph import and re-implementing the graph as a
loop must require no schema change and no change to any use case. If it would, state has leaked
into the orchestrator.

## O2 — Nodes are state-in, state-out

A node builds a prompt, awaits the completion seam, and folds the result into state.

```python
async def draft(state: TailoringState) -> dict[str, Any]:
    result = await seam.complete(
        task="tailor_draft",
        schema=TailoredDraft,
        prompt=build_draft_prompt(state),
    )
    return {"draft": result.value, "usage": [result.usage]}
```

A node **MUST NOT**:

- hold a database session, or read or write any table;
- import a provider SDK or a LangChain model binding (enforced by
  `test_the_application_layer_imports_no_provider_sdk`, widened in this slice — research R2);
- decide business outcomes that survive the run, such as what is discarded or approved.

A node **MAY** call the completion seam and the guideline source, both of which are ports.

**Why the return is a partial dict**: LangGraph merges node returns into state key by key. `usage`
and `findings` carry append reducers because a key without one is *overwritten*, which would
silently keep only the last of up to seven usage records (research R3).

## O3 — Persistence and finalisation happen in the use case

The graph returns final state and writes nothing. `tailor_resume.py` applies the finalisation rules
and performs every write, in one transaction.

This is the design's one corrected defect and the easiest to reintroduce: a terminal `finalize`
node that "just writes the result" satisfies every other rule here while breaking this one.

**The severity split runs before any row is written** (FR-018), so a discarded claim has no
persisted representation to leak from.

**The split is judged on the final review pass's findings only** (`v2-final-pass-severity`, PR #28).
The Reviewer re-judges the whole composed resume on every pass, so the last pass is a complete
statement about the draft as it stands: a claim caught on an earlier pass and fixed by revision
survives as an ordinary proposal, while one still ungrounded at the final pass is re-reported there
and discarded. Every pass's findings persist regardless — the accumulated history is the audit
record, and only the discard decision is pass-scoped.

## O4 — Model choice is a task name, never a model

Nodes pass `task="tailor_draft"`. They never name a model, and escalation is a **different task
name** (`tailor_revise` → `tailor_revise_escalated`), not a branch on attempt count inside a node.

Five names, five `llm_model_<task>` entries. A missing entry falls back to Opus and runs at ~2.5×
for no gain, silently — a test asserts every task name used in application code has one.

## O5 — Usage is returned, never logged internally

Unchanged from the extraction seam's O4. Each node folds its `Usage` into state; the use case
writes the totals in the same transaction as the work. Principle V's audit lands where the data
does.

## O6 — Guidance arrives through a replaceable source

```python
class GuidelineSource(Protocol):
    async def guidelines_for(self, *, context: GuidelineQuery) -> Sequence[Guideline]: ...

@dataclass(frozen=True, slots=True)
class Guideline:
    text: str
    source: str
```

Static rubric in 005; retrieval in 006. **No node, edge, state field, or rule changes when the
implementation is swapped** — that is the 005/006 boundary, and this signature is what enforces it.

`source` is populated from the first implementation, because adding it later would change what the
prompt builders consume. The signature deliberately excludes `top_k`, scores, and embedding
parameters: those are retrieval's vocabulary, and putting them here would be designing 006 inside
005.

## O7 — The graph is bounded and terminates

At most **two revisions**, checked by the conditional edge, not extendable at run time. Exhausting
the budget is a normal exit to finalisation, not an error.

**A test drives the full path** — review → revise → review → revise → review → end — against the
fixture gateway, and asserts seven usage records. This requires the fixture gateway to return a
*sequence* per task name (research R10); without that the escalation path and the exhausted-budget
path are untestable, and both carry release-blocking requirements.

## O8 — Match analysis is read-only

The plan node consumes it; nothing writes it under any outcome, including failure (FR-011). Slice
004's calibration is measured over its history, and a tailoring run that touched it would corrupt a
measurement nobody would think to re-check.
