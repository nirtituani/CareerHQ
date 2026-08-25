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

### Measured (T006) — the prediction held exactly

Probed against the **installed** `langgraph 1.2.11` / `langchain-core 1.6.0` /
`langgraph-checkpoint 4.2.0`, with a three-node graph writing to two keys, one carrying
`Annotated[list[str], operator.add]` and one bare:

| Key | Result after three nodes each returning one element |
|---|---|
| no reducer | `['c']` — **overwritten** |
| `operator.add` | `['a', 'b', 'c']` — appended |

So the failure mode is real and silent: across a seven-call run, a bare `usage` key keeps **one**
record. The audit would be incomplete, the cost figure wrong by up to 7x, nothing would raise, and
the run would look cheap.

Also confirmed in the same probe: **the graph compiles and invokes with no checkpointer at all**,
which is what R1's decision depends on.

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

### Measured, 2026-08-25 (a) — a run that **failed at review**. Not a valid measurement.

Run `cd27b092`, version `a8f1e4b7`, against a real posting and the author's real profile.

| | Measured | Target |
|---|---|---|
| Input tokens | **30,028** | — |
| Output tokens | **21,641** | — |
| Cost | **$0.361819** | SC-006: $0.30 |
| Elapsed | **3m 28.9s** | SC-001: 90s typical, 3min full budget |
| Calls | 3 — plan, draft, review | up to 7 |
| Attempts | **0** — it never revised | up to 2 |

**Read this as a floor, not a result.** It is three calls of a possible seven, with the revision
budget untouched, and it already exceeds both targets: **1.21× the cost ceiling** and over the
three-minute allowance that was meant to cover a *full* revision budget. A first-pass-clear run is
the cheap path, and this is more expensive than the ceiling set for the expensive one.

**Neither number is a valid measurement of a working run**, because this run did not work — it died
in review on the `source_item_id` defect. It is recorded because a failed run's cost is still a
cost, and because it is the only figure this project has for what a *failure* costs. It must not be
compared against SC-006 or SC-001, and the run below is what those targets are measured against.

**R8's lesson repeated exactly.** Slice 004 projected ~1,500 output tokens and measured 2,811, 87%
low. `docs/08` projected ~$0.17 for a whole run; three calls of one cost **$0.36**. The estimate was
low again, in the same direction, by a similar factor.

**21,641 output tokens across three calls is the number to look at first** when cost work begins.
It is the half of the bill this document already identified as the lever, and it is far larger than
the diff-shaped output the schemas were designed to produce. Whether that is the draft returning
more items than expected, or the reviewer writing long findings, is not yet known — the run records
totals, not a per-call breakdown.

**No target has been changed.** SC-006 stays at $0.30 and SC-001 at 90s/3min. Recording a miss is
what slice 004 did with SC-004, and adjusting a number to fit its first measurement would make the
target meaningless.

### Measured, 2026-08-25 (b) — **the first valid measurement**: a run that completed

Run `2615363e`, version `a8f1e4b7` — **the same job and the same profile as (a) above**, so the two
are directly comparable. It cleared review on the first pass and its output was approved by the
owner.

| | Measured | Target | |
|---|---|---|---|
| Cost | **$0.295450** | SC-006: $0.30 | **met**, by $0.0046 |
| Elapsed | **2m 49.6s** (169.6s) | SC-001: 90s typical | **missed**, 1.88× |
| Input tokens | **34,888** | — | |
| Output tokens | **15,512** | — | |
| Calls | **3** — plan, draft, review | up to 7 | |
| Revisions | **0** — first-pass clear | up to 2 | |
| Proposals produced | **4**, of 35 master items | — | |
| Confidence | 78 | threshold 70 | cleared |
| Findings recorded | 7 | — | |

**This is the number SC-006 is measured against, and it passes — narrowly.** $0.0046 of headroom is
1.5%, on the **cheapest path the workflow has**: three calls of a possible seven, with both
revisions unused. A single revision adds a draft and an Opus review, and the failed run (a) shows
what three calls alone can cost when output runs long. **The ceiling should be read as met by this
run, not as met in general.** SC-006 is left at $0.30 precisely so that the first run to exceed it
is recorded as exceeding it.

**SC-001's 90-second target is missed and is recorded as missed**, not adjusted. 169.6s is under the
three-minute allowance, but that allowance was written for a **full revision budget** and this run
used none of it. The honest reading is that the *typical* case is nearly twice its target, and that
the three-minute ceiling has about ten seconds of margin for a path that does two more calls than
this one did.

**Against (a), the failed run, on identical inputs:**

| | (a) failed | (b) succeeded |
|---|---|---|
| Cost | $0.361819 | **$0.295450** — 18% less |
| Output tokens | 21,641 | **15,512** — 28% fewer |
| Input tokens | 30,028 | 34,888 — 16% more |
| Elapsed | 3m 28.9s | 2m 49.6s |

The input rose because `[id: …]` was added to every profile line between the two runs — roughly 400
tokens on a master that appears in every prompt. That was the price of a proposal being able to map
back to the line it changes at all, and this run is the evidence it was worth paying: (a) produced
nothing placeable, (b) produced four proposals a person approved.

Output falling by 28% on the same inputs is **not yet explained** and should not be assumed
repeatable — one run is one sample. It is consistent with the reviewer writing shorter findings when
it can attach them to an item rather than restating which line it means, but nothing here measures
that. The run stores totals, not a per-call breakdown, so the question stays open.

**What is still outstanding.** T085 asks for **both** paths measured; this is the first-pass-clear
path only. The full-revision-budget path — seven calls, three of them Opus reviews — has never run.

### Measured, 2026-08-25 (c) — a completing run **with one revision**, on a second real job

Run `6356fb4e`, version `c582d938`, a different posting and the same profile as (a) and (b). It took
one revision, cleared review on the second pass, and finished `awaiting_approval`.

| | Measured | Target | |
|---|---|---|---|
| Cost | **$0.464942** | SC-006: $0.30 | **missed**, 1.55× |
| Elapsed | **4m 20.5s** (260.5s) | SC-001: 90s typical / 3min full budget | **missed**, both |
| Input tokens | **41,621** | — | |
| Output tokens | **23,908** | — | |
| Calls | **5** — plan, draft, review, revise, review | up to 7 | |
| Revisions | **1** | up to 2 | |
| Final status | `awaiting_approval`, run `succeeded` | — | |
| Confidence | **76** | threshold 70 | cleared |
| Proposals produced | **1**, of 35 master items | — | |
| Findings recorded | **12** — 4 `overstated`, 8 `uncovered` | — | |

**This is the run above the ceiling that (b) did not have.** One revision cost 57% more than (b)'s
first-pass-clear run and took 53% longer, on five calls of a possible seven. The worst case — two
revisions, seven calls, three of them Opus reviews — has still never been measured and is higher
again.

**Both targets are recorded as missed and neither is changed.** SC-006 stays at $0.30 and SC-001 at
90s/3min. Two runs now sit either side of the cost ceiling, which is a more useful position than one
beneath it: the ceiling is doing its job, and what it is telling us is that a single revision breaks
it. That is a finding about the workflow's cost, not a reason to move the number.

**The id mapping held on a second job.** The one proposal produced carries a `source_item_id` naming
a real master item, and all four `overstated` findings are attached to real item rows — 0 unplaceable
ids, 0 proposals without one. This is the objectively checkable part of the fix working outside the
job it was developed against.

**A caveat on the `attempt` column.** All 12 findings are stamped `attempt = 1`, which is the run's
final attempt rather than the pass that caught each one — `run_tailoring` writes `result["attempt"]`
to every row. So this data cannot distinguish a concern raised on the first review from one raised on
the second. Noted here so the figures above are not over-read; not acted on.

### Manual QA observations from run (c) — one reader, one run, **not measurements**

Notes taken by the author while reading the draft on screen, recorded because a person reading real
output is the only check FR-017 has and because there is nothing else yet.

**What these are not.** They are not evidence about the quality of the agent's output. Nothing was
scored against a rubric, there was no second reader, no counterfactual draft was produced, and n = 1.
A single reader agreeing with a single draft is the weakest evidence this project accepts anywhere
else, and it is recorded as an observation rather than a conclusion for that reason. Turning notes
of this kind into a measurement is what slice 007 exists to do.

The reader's observations, as stated:

- **One proposal against 34 items left unchanged.** The counts are measured; whether that is the
  right amount of change for this posting is the reader's judgement and is not established here.
- **The reviewer surfaced several `Not addressed` gaps rather than proposing experience to fill
  them.** That eight `uncovered` findings exist is measured; reading them as the agent declining to
  invent is the reader's interpretation. AI-008 is enforced by the discard rule and its tests, not
  by this observation.
- **The surviving proposal kept the profile's own hedging** around RAG and agentic work — the
  reader's note is that exploratory language was not upgraded into claims of production experience.
- **The reviewer flagged wording the reader judged stronger than the profile supports**, around
  production Python, AWS and AI experience. Four `overstated` findings are measured; that they name
  the right claims is the reader's assessment.

None of the above changes an implementation, a prompt, a schema or a target.

**One cost is now known and accepted**: rendering `[id: …]` onto every profile line adds ~1,540
characters (~400 tokens) to the master, which appears in all four prompts — roughly 1,600 input
tokens per run. That is the price of the workflow being able to map a proposal back to the line it
changes at all, so it is not a candidate for the cost work.

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
