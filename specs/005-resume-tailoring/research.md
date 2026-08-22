# Research — Slice 005, Resume Tailoring

What the design assumed, checked against reality. Where research contradicted the design, the
design is corrected here and the contradiction is left visible.

The approved design is
[`docs/superpowers/specs/2026-08-22-resume-tailoring-design.md`](../../docs/superpowers/specs/2026-08-22-resume-tailoring-design.md).
Decisions already settled there are not re-litigated; this document records only what needed
finding out.

---

## R1 — LangGraph: the version, and what declining the checkpointer actually means

**Checked against PyPI**, per the project rule that nine pinned versions across this repository did
not exist when first written down.

| Package | Latest | Requires Python |
|---|---|---|
| `langgraph` | **1.2.11** | `>=3.10` |
| `langgraph-checkpoint` | 4.2.0 | `>=3.10` |
| `langchain-core` | 1.6.0 | `>=3.10,<4.0` |

The backend is `>=3.12`, so all are compatible. Pin `langgraph>=1.2.11,<1.3`.

**`langgraph` 1.2.11 pulls in five transitive dependencies**: `langchain-core<2,>=1.4.7`,
`langgraph-checkpoint<5,>=4.1`, `langgraph-prebuilt`, `langgraph-sdk`, and `xxhash`.

**This corrects the design's framing.** §3.2 says the checkpointer is declined, which reads as
though the dependency is avoided. It is not — `langgraph-checkpoint` arrives whether or not it is
used, because it carries the in-memory saver the runtime itself needs.

What is actually declined is **`langgraph-checkpoint-postgres`**, a *separate* package that is not
a transitive dependency and will not be installed. That is the one that would create a second
persistent representation of a workflow, which is the thing §3.2 objects to. The distinction
matters because "we don't depend on the checkpointer" is falsifiable by reading the lockfile, and
someone will read it.

**Decision**: pin `langgraph>=1.2.11,<1.3`. Do not add `langgraph-checkpoint-postgres`. Record in
`pyproject.toml`, beside the `litellm` comment, why the Postgres saver is absent — an absent
dependency with no note is indistinguishable from an oversight.

---

## R2 — The import guard is weaker than the design claimed, and `langchain-core` is why it matters

The design's first draft asserted that a node reaching for `ChatAnthropic` would fail the suite.
**It would not.** `tests/unit/test_architecture.py::test_the_application_layer_imports_no_provider_sdk`
checks exactly one package:

```python
forbidden = ("litellm",)
```

Adding LangGraph makes this materially worse rather than merely incomplete. `langchain-core`
arrives transitively and carries the `BaseChatModel` abstraction, so `langchain_anthropic` becomes
a one-line install away from working, and the idiomatic LangGraph example everyone copies binds a
model inside the node. The guard is the only thing standing between that idiom and Principle V.

**Decision**: widen `forbidden` to `("litellm", "anthropic", "openai", "langchain_anthropic",
"langchain_openai", "langchain_community")` before the first node is written, and land it in the
**same commit** as the LangGraph dependency. A guard added after the code it governs is a guard
that has already been bypassed once.

`langchain_core` itself is **not** forbidden: LangGraph's own types come from it, and banning it
would ban the orchestrator. The provider bindings are the boundary, not the abstraction.

**Watch it fail.** Per the project rule that a gate nobody has watched fail is not a gate: add
`import anthropic` to a node, confirm the test names the file, remove it.

**Alternatives considered.** Forbidding `langchain_core` outright — rejected, it would forbid
LangGraph. Checking for `BaseChatModel` subclassing at runtime — rejected, it catches only one of
several ways to reach a provider, and an import-graph assertion catches them all statically.

---

## R3 — Graph state: a dataclass, and the reducer question

LangGraph accepts a `TypedDict`, a dataclass, or a Pydantic model as the state schema. The design
specifies a frozen dataclass, deliberately not LangChain message objects, because the state is
CareerHQ's vocabulary and is what the use case reads to persist.

**One thing genuinely needs verifying against the installed version**, because it decides whether
`usage` accumulates correctly: LangGraph merges node return values into state key by key, and a key
with no reducer is **overwritten** rather than appended. `usage` must accumulate one entry per
call across up to seven calls, so it needs an explicit append reducer
(`Annotated[list[Usage], operator.add]`) or every node must return the whole accumulated list.

**This is a real failure mode, not a formality.** Getting it wrong silently loses every usage
record except the last — which means Principle V's audit trail is incomplete, the cost figure is
wrong by a factor of up to seven, and *nothing raises*. It looks exactly like a cheap run.

**Decision**: use an append reducer for `usage` and for `findings`. **Verify the reducer semantics
against the installed version before building the graph** — a task, not an assumption — and assert
it with a test that runs a two-revision graph against a fake seam and counts seven usage entries.

---

## R4 — Five task names, and the escalation that is not a branch

`ports.py` takes `task` as a *name*, and `model_for_task` resolves configuration keyed by it. That
is what makes `docs/08` §3.2.3's escalation configuration rather than workflow code.

| Task name | Model | Step |
|---|---|---|
| `tailor_plan` | Sonnet | Strategy |
| `tailor_draft` | Sonnet | Drafting |
| `tailor_review` | **Opus** | Review |
| `tailor_revise` | Sonnet | First revision |
| `tailor_revise_escalated` | **Opus** | Second revision |

**All five need an `llm_model_<task>` entry.** `model_for_task` falls back to
`llm_provider_model`, which is Opus — so a missing entry runs at roughly 2.5× the price for no
gain, silently. This has already caught CV extraction once in this project, which is why it is
written here as a checklist item rather than a caution.

**A test asserts every task name used in application code has a configuration entry**, rather than
trusting five entries to be typed correctly. The failure mode is silent and expensive; the test is
four lines.

---

## R5 — Cost and latency: the design's numbers are unverified, and the last estimate was wrong

`docs/08` estimates ~$0.17 per tailoring run. That predates this loop's shape.

**The bill this loop can actually run up**: worst case is seven calls — plan, draft, review,
revise, review, revise, review — of which **three are Opus reviews of a full draft**. Reviews are
the expensive calls, because a review reads the entire draft *and* the profile.

**The relevant precedent is that this project's last estimate was low.** Slice 004's R8 projected
~1,500 output tokens and measured **2,811** — off by 87%, in the direction that costs money. Its
*share* prediction was right (79%, inside the predicted 57–86%); its magnitude was not.

**Decision**: SC-006's $0.30 ceiling is a **target awaiting measurement**, not a design constraint.
Measure on the first real run, both paths — first-pass clear, and full revision budget — and record
the measurement here the way R8 recorded its own. If the ceiling is missed, mark it missed in
`spec.md` rather than adjusting the number, which is what slice 004 did with SC-004.

**The lever, if one is needed**, is already known and is not "use a cheaper reviewer": output is
57–86% of cost and the slow half of a completion. **Draft and Revise must return item
identifiers with changed text, never the whole resume re-emitted.** Asking a model to retype text
it was given cost 52 seconds and a proxy timeout in slice 003. This is a hard requirement of the
schemas, not an optimisation to apply later.

---

## R6 — The static rubric, and what it must not become

Slice 006 replaces the guideline source with retrieval. Until then it is a constant.

**Decision**: a short, explicit rubric in application code — strong-verb openings, quantified
outcomes where the profile supplies numbers, no invented metrics, mirror the posting's vocabulary
where the profile genuinely supports it, and lead each experience with what is relevant to *this*
posting. Ten to fifteen rules, each with a `source` naming where it came from.

**`source` is populated from the first implementation** even though it is a constant. The design
(§3.4) gives the reason: adding the field in 006 would change what the prompt builders consume,
which is exactly the compounding node-input change the 005/006 boundary exists to prevent.

**What it must not become**: a long document, or one that varies by job. Both are 006's job, and
building either here would make the port's shape wrong — the static implementation would start
needing the retrieval vocabulary (`top_k`, scores) that §3.4 deliberately keeps out of the
signature.

---

## R7 — Reusing the background-execution pattern, and the three bugs it already paid for

Match analysis established the pattern: create the row synchronously, run the work in
`BackgroundTasks`, poll a status, reap what stalls. Tailoring reuses it wholesale. The pattern
arrives with three defects already found and fixed, each of which passed a green suite:

1. **`is` against an enum on a value read from the database.** Status columns are `String(16)`; a
   row loaded in a fresh session returns a plain `str`, so `status is not MatchStatus.PENDING`
   matched nothing and every analysis sat `pending` forever while 270 tests stayed green. The tests
   missed it because they pass the session that created the row, whose identity map still holds the
   enum member. **Use `==`, and exercise every status path against a re-read record** (FR-047).
2. **A lazy relationship on a freshly added object** raises `MissingGreenlet` as a 500 when
   serialising a just-created record. A version has items and findings — the same shape. Assign
   collections at construction.
3. **A stuck run could not be recovered**, because the in-flight guard answered 409 to the one
   action that would have recovered it. Hit three times, each needing SQL by hand. **The reaper is
   built in this slice from the start**, not added after it bites.

**One thing that does not carry over.** A tailoring run is far longer than an analysis, so the
abandonment threshold cannot simply be copied. An hour is fine for a run that should take 90
seconds, but the reaper must not release a run that is legitimately in its second revision. The
threshold is a named constant with the reasoning beside it.

**Alternatives considered.** Celery, which the constitution lists under technology constraints —
rejected for this slice on the same grounds slice 004 rejected it (R7): it adds a broker, a worker
process and a deployment surface to solve a problem `BackgroundTasks` already solves at this
volume. Revisit when a run must survive a process restart, which is a real requirement this slice
does not have.

---

## R8 — The lifecycle needs a state that `docs/03` does not have

`docs/03` §10.1 draws `Draft → Tailoring → Reviewing → Ready`, and **`Reviewing` means two
different things**: the agent is self-critiquing, and the agent has finished and it is the owner's
turn. One is a machine working for tens of seconds; the other is a human queue that may last days.
They have different next actions and different interfaces.

**Decision**: add **`Awaiting approval`** between `Reviewing` and `Ready`, and amend `docs/03`
§10.1 in this slice. A lifecycle described in two places will disagree.

`Exported` and `Submitted` are slice 006 and are **not** added to the enum here. A state nothing
can reach is a claim the code does not support.

---

## R9 — What the Reviewer returns, and why severity is a closed set

The finalisation split (FR-018 vs FR-019) is only enforceable if the Reviewer's output distinguishes
the two classes structurally. A free-text concern cannot be routed.

**Decision**: every finding carries a `kind` from a closed set —

| kind | Means | Finalisation |
|---|---|---|
| `ungrounded` | The claim traces to nothing in the profile | **Discarded before persistence** (FR-018) |
| `overstated` | The profile supports it; the wording inflates it | Shown, flagged (FR-019) |
| `uncovered` | A requirement the draft fails to address | Shown against the draft (FR-019) |

**`ungrounded` must quote what it objects to**, for the same reason slice 004 required every
verdict but one to quote the profile: a verdict with no evidence lets the model invent the
*absence*. A finding that says "this is unsupported" without saying which words are unsupported
cannot be tested, cannot be shown, and cannot be checked by a person.

**The lesson slice 004 paid for applies directly.** Demanding a structured field the model cannot
honestly fill produces validation failures where *the model was right* — `unverified` could not
carry a shortfall reason, because the profile's silence gives no basis for choosing one. So
`uncovered` findings attach to the **draft**, not to an item: there is no item to attach them to,
and inventing one would repeat that error exactly.

---

## R10 — Where the fixture gateway has to grow

FR-045 forbids live provider calls in tests, and the existing `fixture_gateway` returns canned
objects keyed by task. A four-node loop needs something it has not needed before: **the same task
name returning different results on successive calls**, so that a test can drive review → revise →
review and reach the escalated path.

**Decision**: extend the fixture gateway to accept a *sequence* per task name, consuming one entry
per call. Without it, the two-revision path and the exhausted-attempts path are untestable, and
those are precisely the paths where FR-013's bound and FR-018's discard rule live — the requirements
whose failure is a release blocker.

This is the same trap slice 004 recorded: a branch was never exercised because the existing test
accepted `{202, 409}` and always got 409. An untestable path is an untested path.
