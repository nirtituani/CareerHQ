# Contract: the structured completion seam

**This is the artifact slice 004 inherits.** It is written to be implemented against without
re-reading the plan, because the cost of getting it wrong is paid there rather than here.

Designed in [research.md](../research.md) R1. Required by FR-024 to FR-028 and Constitution
Principles V and VI.

---

## Shape

Declared in `application/ports.py`, implemented only under `infrastructure/ai/`.

```
StructuredCompletion (Protocol)

    async complete(
        task:    TaskName,        # what is being done — not which model does it
        schema:  type[T],         # T is a Pydantic model; REQUIRED
        prompt:  <rendered input>,
    ) -> Completion[T]


Completion[T]
    value: T                      # already validated against `schema`
    usage: Usage

Usage
    model: str                    # the model actually used, resolved from `task`
    input_tokens: int
    output_tokens: int
    cost: Decimal
    is_fixture: bool              # True only from the fixture adapter
```

## Obligations

**O1 — A schema is required and the return is typed.** There is no call shape that yields
unvalidated text. FR-025 and Principle VI are structural, not remembered.

**O2 — Validation failure is extraction failure.** Output that does not satisfy `schema` raises;
it is never partially accepted, never repaired by hand, and never shown as though understood.
The caller surfaces it as FR-008 ("extraction produced nothing usable"), because a model that
returned malformed output has told you it did not understand the document.

**O3 — `task` selects the model; callers never name one.** Model choice resolves from
configuration keyed by task name. This is the property that makes docs/08 §3.2.3 expressible:

| Slice 004 node | Task name | Model per §3.2.3 |
|---|---|---|
| Analyze job description | `analyze_job` | Sonnet |
| Draft tailored content | `draft` | Sonnet |
| Revise (first attempt) | `revise` | Sonnet |
| Revise (after one failure) | `revise_escalated` | **Opus** |
| Reviewer | `review` | **Opus** |
| *(this slice)* CV extraction | `cv_extraction` | Sonnet |

The escalation is a **different task name**, not a branch inside business code. That keeps
§3.2.3 in configuration where it can be changed and costed, instead of scattered through the
workflow. Had `complete()` taken a model identifier, every call site would hardcode one.

**O4 — Usage is returned, never logged inside the adapter.** The application layer records it in
the same transaction as the work it paid for (FR-026). Infrastructure stays dumb; the audit trail
lands where the data does.

**O5 — Exactly one module imports the provider library.** `infrastructure/ai/litellm_gateway.py`
is intended to be the only file in the codebase importing `litellm`. **Assert this with a test
over the import graph.** Principle V then holds as a property of the source tree rather than as
reviewer vigilance — the same mechanism that keeps `domain/` free of framework imports.

**O6 — Substitutable without network.** The API resolves the implementation through a FastAPI
dependency, so tests override it exactly as slice 001 overrides `get_verified_google_claims`
(FR-027). The suite must pass with no API key, no network, and no nondeterministic output.

**O7 — Absence is reported, not crashed on.** With no provider configured, readiness reports
`ai_provider: not_configured` and the call fails at the point of use naming the missing setting
(FR-028). Never a startup crash, never a silent degradation to empty output.

## Implementations

| Adapter | When | Behaviour |
|---|---|---|
| `LiteLLMGateway` | Provider configured | Real call. The only importer of `litellm` (O5) |
| `FixtureGateway` | `AI_PROVIDER=fixture`, explicit | Canned structured values. Sets `is_fixture=True`, which propagates to `ImportedResume.is_fixture` and is shown in the interface |
| Test fake | Dependency override | Per-test canned values; may assert on the `task` and `schema` it received |

`FixtureGateway` is **never** selected by the absence of a key. Silently returning canned data
when a key is missing would mean a user uploads their real CV and reviews invented content —
FR-008 exists to prevent exactly that, and inventing content is the same failure with better
manners.

## What this contract does not cover

Multi-step orchestration, tool use, retries with feedback, and self-critique are **slice 004**.
This seam is one call in, one validated object out. If a caller needs the model to react to its
own previous output, that caller belongs in the agent runtime, not here — and that boundary is
the scope guard the spec relies on.
